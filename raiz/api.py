"""API da Raíz (FastAPI). Desenho do agent-service-toolkit (MIT): o checkpointer abre no início do serviço e o grafo
é retomado pelo thread_id quando há pausa pendente.

- /saude e /whatsapp (webhook, assinatura conferida pelo PyWa) não pedem token.
- O resto pede `Authorization: Bearer <RAIZ_API_TOKEN>`; sem token configurado, essas rotas ficam fechadas.
Rodar: uv run raiz api
"""

from __future__ import annotations

import contextlib
import hmac
import logging

from fastapi import Depends, FastAPI, Header, HTTPException
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
    engine: Engine | None = None, grafo=None, deps: aceite.Dependencias | None = None, whatsapp: bool = True
) -> FastAPI:
    """Com grafo e deps prontos (testes), usa-os; senão abre o checkpointer cifrado no Postgres."""

    @contextlib.asynccontextmanager
    async def ciclo(app: FastAPI):
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
    app.state.engine, app.state.grafo, app.state.deps = engine, grafo, deps

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
                        "select id, contato_id, cod_imovel, tipo, texto, criado_em from pessoal.mensagem_saida "
                        "where estado = 'aguardando_aprovacao' order by id"
                    )
                )
                .mappings()
                .all()
            )
        return [dict(r) for r in rs]

    @app.post("/mensagens/{mensagem_id}/aprovar", dependencies=seguro)
    def aprovar(mensagem_id: int, corpo: Decisao) -> dict:
        from raiz.whatsapp import aprovar as _aprovar
        from raiz.whatsapp import enviador_pywa, enviar_aprovadas

        try:
            _aprovar(app.state.engine, mensagem_id, corpo.quem)
        except ValueError as ex:
            raise HTTPException(409, str(ex)) from ex
        enviadas = 0
        if getattr(app.state, "wa", None) is not None:
            enviadas = enviar_aprovadas(app.state.engine, enviador_pywa(app.state.wa))
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

    return app
