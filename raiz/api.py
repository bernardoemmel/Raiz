"""API da Raíz (FastAPI). Desenho do agent-service-toolkit (MIT): o checkpointer abre no início do serviço e o grafo
é retomado pelo thread_id quando há pausa pendente.

- /saude, /eventos, /eventos.ics e /whatsapp (webhook com assinatura PyWa) não pedem token.
- O resto pede `Authorization: Bearer <RAIZ_API_TOKEN>`; sem token configurado, essas rotas ficam fechadas.
- Rotas do front (raiz/front_api.py): /municipios, /imoveis/..., /geo/... com os nomes de coluna dos CSV do motor.
Rodar: uv run raiz api
"""

from __future__ import annotations

import contextlib
import hmac
import logging
import os

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import Engine, text

from raiz.agentes import aceite
from raiz.config import config

log = logging.getLogger(__name__)


class Inicio(BaseModel):
    contato_id: int
    proposta: dict | None = None


class Proposta(BaseModel):
    area_ha: float
    prazo_anos: int
    pagamento: str
    quem_paga: str | None = None


class TextoDono(BaseModel):
    texto: str


class Decisao(BaseModel):
    quem: str


class Resolucao(BaseModel):
    quem: str
    resposta: dict


def _exigir_token(authorization: str | None = Header(default=None)) -> None:
    esperado = config().api_token
    if esperado is None:
        raise HTTPException(503, "API fechada: defina RAIZ_API_TOKEN")
    dado = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(dado.encode(), esperado.get_secret_value().encode()):
        raise HTTPException(401, "token inválido")


def criar_app(
    engine: Engine | None = None,
    grafo=None,
    deps: aceite.Dependencias | None = None,
    whatsapp: bool = True,
    armazem=None,
) -> FastAPI:
    """Com grafo e deps prontos (testes), usa-os; senão abre o checkpointer cifrado no Postgres."""

    @contextlib.asynccontextmanager
    async def ciclo(app: FastAPI):
        async with contextlib.AsyncExitStack() as assinc:
            mcp = getattr(app.state, "mcp", None)
            if mcp is not None:  # o servidor MCP por HTTP precisa do gerenciador de sessões rodando
                await assinc.enter_async_context(mcp.session_manager.run())
            with contextlib.ExitStack() as pilha:
                if app.state.grafo is None:
                    from raiz.agentes.memoria import checkpointer
                    from raiz.banco import engine as engine_padrao
                    from raiz.modelos.cascata import cascata_padrao

                    cp = pilha.enter_context(checkpointer())
                    app.state.engine = app.state.engine or engine_padrao()
                    app.state.grafo = aceite.construir(cp)
                    app.state.deps = aceite.Dependencias(app.state.engine, cascata_padrao())
                yield

    app = FastAPI(title="Raíz", lifespan=ciclo)
    from raiz.privacidade import configurar_log

    configurar_log()
    app.state.engine, app.state.grafo, app.state.deps = engine, grafo, deps
    from raiz.pedidos import servico as pedidos_servico
    from raiz.publica.email_login import enviador

    if pedidos_servico.ENVIO_LINK is None:
        pedidos_servico.ENVIO_LINK = enviador()
    app.state.armazem = armazem  # arquivos do motor (raiz/executor/armazem.py); padrão: o da configuração

    if whatsapp:
        from raiz.whatsapp import criar_cliente, ligar_webhook

        wa = criar_cliente(app)
        app.state.wa = wa
        if wa is not None:
            ligar_webhook(wa, lambda: (app.state.engine, app.state.grafo, app.state.deps))

    @app.get("/saude")
    def saude() -> dict:
        try:
            with app.state.engine.connect() as con:
                con.execute(text("select 1"))
            return {"ok": True}
        except Exception as ex:  # noqa: BLE001
            raise HTTPException(503, f"banco fora do ar: {type(ex).__name__}") from ex

    seguro = [Depends(_exigir_token)]

    @app.post("/aceites/{cod_imovel}/iniciar", dependencies=seguro)
    def iniciar(cod_imovel: str, corpo: Inicio) -> dict:
        try:
            aceite.iniciar(app.state.grafo, app.state.deps, cod_imovel, corpo.contato_id, corpo.proposta)
        except ValueError as ex:
            raise HTTPException(409, str(ex)) from ex
        return _estado(cod_imovel)

    @app.post("/aceites/{cod_imovel}/proposta", dependencies=seguro)
    def proposta(cod_imovel: str, corpo: Proposta) -> dict:
        try:
            aceite.enviar_proposta(app.state.grafo, app.state.deps, cod_imovel, corpo.model_dump(exclude_none=True))
        except ValueError as ex:
            raise HTTPException(409, str(ex)) from ex
        return _estado(cod_imovel)

    @app.post("/aceites/{cod_imovel}/responder", dependencies=seguro)
    def responder(cod_imovel: str, corpo: TextoDono) -> dict:
        """Resposta do dono que chegou por outro canal (telefone, visita): o fundador digita."""
        try:
            aceite.responder(app.state.grafo, app.state.deps, cod_imovel, corpo.texto)
        except ValueError as ex:
            raise HTTPException(409, str(ex)) from ex
        return _estado(cod_imovel)

    @app.get("/aceites/{cod_imovel}", dependencies=seguro)
    def estado(cod_imovel: str) -> dict:
        return _estado(cod_imovel)

    def _estado(cod_imovel: str) -> dict:
        with app.state.engine.connect() as con:
            r = (
                con.execute(
                    text("select estado, etapa, motivo, atualizado_em from negocio.aceite where cod_imovel = :c"),
                    {"c": cod_imovel},
                )
                .mappings()
                .first()
            )
        if r is None:
            raise HTTPException(404, "sem aceite para este imóvel")
        return {
            "cod_imovel": cod_imovel,
            **dict(r),
            "esperando": aceite.pausa(app.state.grafo, cod_imovel, app.state.deps),
        }

    @app.get("/mensagens/pendentes", dependencies=seguro)
    def pendentes() -> list[dict]:
        with app.state.engine.connect() as con:
            rs = (
                con.execute(
                    text(
                        "select id, contato_id, cod_imovel, tipo, texto, legibilidade, criado_em "
                        "from pessoal.mensagem_saida where estado = 'aguardando_aprovacao' order by id"
                    )
                )
                .mappings()
                .all()
            )
        return [dict(r) for r in rs]

    @app.post("/mensagens/{mensagem_id}/aprovar", dependencies=seguro)
    def aprovar(mensagem_id: int, corpo: Decisao) -> dict:
        from raiz.whatsapp import aprovar as _aprovar
        from raiz.whatsapp import enviador_pywa, enviar_aprovadas, pedidor_localizacao_pywa

        try:
            _aprovar(app.state.engine, mensagem_id, corpo.quem)
        except ValueError as ex:
            raise HTTPException(409, str(ex)) from ex
        enviadas = 0
        if getattr(app.state, "wa", None) is not None:
            enviadas = enviar_aprovadas(
                app.state.engine, enviador_pywa(app.state.wa), pedir_localizacao=pedidor_localizacao_pywa(app.state.wa)
            )
        return {"aprovada": mensagem_id, "enviadas": enviadas}

    @app.post("/mensagens/{mensagem_id}/descartar", dependencies=seguro)
    def descartar(mensagem_id: int, corpo: Decisao) -> dict:
        from raiz.whatsapp import descartar as _descartar

        _descartar(app.state.engine, mensagem_id, corpo.quem)
        return {"descartada": mensagem_id}

    @app.get("/revisoes", dependencies=seguro)
    def revisoes() -> list[dict]:
        with app.state.engine.connect() as con:
            rs = (
                con.execute(
                    text(
                        "select id, tarefa, chave, motivo, conteudo, criado_em from operacao.fila_revisao "
                        "where estado = 'aberta' order by id"
                    )
                )
                .mappings()
                .all()
            )
        return [dict(r) for r in rs]

    @app.post("/revisoes/{revisao_id}/resolver", dependencies=seguro)
    def resolver(revisao_id: int, corpo: Resolucao) -> dict:
        from raiz.modelos.cascata import resolver_revisao

        try:
            with app.state.engine.begin() as con:
                resolver_revisao(con, revisao_id, corpo.resposta, corpo.quem)
        except ValueError as ex:
            raise HTTPException(409, str(ex)) from ex
        return {"resolvida": revisao_id}

    # rotas do front (front/README.md, "Depois (API)"): dados do PostGIS com CPF/CNPJ mascarados
    from raiz import front_api

    def _engine_do_app(request) -> Engine:
        if request.app.state.engine is None:
            from raiz.banco import engine as engine_padrao

            request.app.state.engine = engine_padrao()
        return request.app.state.engine

    app.include_router(front_api.roteador(_engine_do_app), dependencies=seguro)
    # Calendário de fontes oficiais: somente campos públicos, sem a parte privada da vigilância.
    from raiz.calendario import api as calendario_api

    app.include_router(calendario_api.roteador(_engine_do_app))
    from raiz.documentos.certidao import api as certidao_api

    app.include_router(certidao_api.roteador(_engine_do_app, _exigir_token))
    # processamento do motor dentro do produto (agente Dados) e números do Brasil e dos estados
    from raiz.executor import painel

    def _armazem_do_app(request):
        if request.app.state.armazem is None:
            from raiz.executor.armazem import do_config

            request.app.state.armazem = do_config()
        return request.app.state.armazem

    app.include_router(painel.roteador(_engine_do_app, _armazem_do_app), dependencies=seguro)
    app.include_router(painel.roteador_publico(_armazem_do_app))
    # pedido de lote (docs/cena-alvo.md): rotas do cliente (sessão própria), internas (token da API) e o aviso de
    # pagamento do Pix (segredo do webhook)
    from raiz.pedidos import api as pedidos_api

    cfg = config()
    base_login = (
        getattr(cfg, "login_base_url", None)
        or os.environ.get("RAIZ_FRONT_URL")
        or getattr(cfg, "api_origens", "").split(",")[0].strip()
    )
    app.include_router(pedidos_api.roteador_cliente(_engine_do_app, base_url=base_login))
    app.include_router(pedidos_api.roteador_interno(_engine_do_app), dependencies=seguro)
    app.include_router(pedidos_api.roteador_webhook(_engine_do_app))
    # Ficha da terra: sessão individual e créditos pagos, separados do token operacional da API.
    from raiz import prospeccao_api, prospeccao_webhook

    app.include_router(prospeccao_api.roteador(_engine_do_app))
    app.include_router(prospeccao_webhook.roteador(_engine_do_app))
    # backoffice do fundador, só leitura (saúde, custo do mês contra orçamento, filas, logs por fazenda) e
    # reconhecimento dos alertas de operação (raiz/operacao/backoffice.py, raiz/operacao/alertas.py)
    from raiz.operacao import backoffice

    app.include_router(backoffice.roteador(_engine_do_app), dependencies=seguro)
    app.include_router(backoffice.roteador_publico())
    # painel de acerto das previsões congeladas, no formato do hub (raiz/aprendizado/hub.py)
    from raiz.aprendizado import hub as hub_acerto

    app.include_router(hub_acerto.roteador(_engine_do_app), dependencies=seguro)
    app.include_router(hub_acerto.roteador_publico())
    # vigilância das fazendas e dos projetos (raiz/vigilancia): alertas por imóvel, perdas de projeto com o prazo da
    # Verra, rascunho do relatório de perda, avisos e marcação verdadeiro/falso. Lê o estado publicado no Release
    # vigilancia (parte privada com RAIZ_VIGILANCIA_CHAVE), não o PostGIS
    from raiz.vigilancia import api as vigilancia_api

    app.include_router(vigilancia_api.roteador(), dependencies=seguro)
    # API pública (/v1) para as empresas clientes e os agentes de IA delas: chave por empresa ou login por e-mail,
    # limite por chave, cada chamada gravada; OpenAPI em /v1/openapi.json. O servidor MCP fica em /mcp.
    from raiz.publica import api as publica_api

    def _engine_principal(request) -> Engine:
        if app.state.engine is None:
            from raiz.banco import engine as engine_padrao

            app.state.engine = engine_padrao()
        return app.state.engine

    from fastapi.responses import PlainTextResponse

    from raiz.publica.contrato import RESUMO
    from raiz.publica.telemetria import TelemetriaMiddleware, configurar_telemetria

    configurar_telemetria()

    @app.get("/llms.txt", response_class=PlainTextResponse, include_in_schema=False)
    def llms():
        return RESUMO

    verificador = None
    if os.environ.get("RAIZ_OAUTH_ISSUER") and os.environ.get("RAIZ_MCP_RESOURCE"):
        from raiz.publica.oauth import VerificadorKeycloak, rotas_metadados
        from raiz.publica.rotas_agentes import base_publica
        from raiz.publica.servidor_mcp import ApiRaiz, app_http

        def eng():
            return _engine_principal(None)

        verificador = VerificadorKeycloak(eng)
        app.state.mcp, mcp_app = app_http(
            ApiRaiz(app=app, url=base_publica().removesuffix("/v1"), engine_de=eng),
            config().mcp_hosts,
            verificador=verificador,
        )
        app.router.routes.extend(rotas_metadados(verificador))
        app.mount("/mcp", mcp_app)
    else:

        @app.post("/mcp/", include_in_schema=False)
        def mcp_fechado():
            from raiz.publica.problemas import problema

            return problema(503, "oauth_nao_configurado", "MCP aguarda configuração do Keycloak", "avise a Raíz")

    app.mount("/v1", publica_api.criar(_engine_principal, verificador))
    # link público, cartão e vídeo pelo código curto: sem token (só município, hectares, selo e código antes do aceite)
    from raiz import publico

    app.include_router(publico.roteador(_engine_do_app))
    # JSON grande (São Félix: 26 MB) vai comprimido; o Starlette já não comprime resposta parcial (206), e o PMTiles
    # fica de fora (os ladrilhos já vêm comprimidos e o leitor pede por Range)
    from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES, GZipMiddleware

    app.add_middleware(
        GZipMiddleware,
        minimum_size=2048,
        exclude_content_types=(*DEFAULT_EXCLUDED_CONTENT_TYPES, "application/vnd.pmtiles"),
    )
    origens = [o.strip() for o in getattr(config(), "api_origens", "").split(",") if o.strip()]
    from raiz.publica.oauth import acesso_interno
    from raiz.seguranca_api import SegurancaAPI

    app.add_middleware(
        SegurancaAPI,
        limite=getattr(config(), "api_limite_minuto", 120),
        login_limite=getattr(config(), "api_login_limite_minuto", 10),
        origens=origens,
        autenticada_interna=lambda scope: acesso_interno(Request(scope)) is not None,
    )
    # O último middleware fica por fora e registra também recusas do limite global.
    app.add_middleware(TelemetriaMiddleware)
    return app
