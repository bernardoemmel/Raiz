"""API pública da Raíz (/v1): o pedido de lote para as empresas clientes e os agentes de IA delas. Paga, sem plano
grátis (decisão do fundador, 12/11/2026).

- Chave de API por empresa, só na API REST (cabeçalho X-Chave-API ou Authorization: Bearer raiz_...); a conta da
  empresa se abre com o CNPJ (validado, guardado só em hash e mascarado) e os termos de uso aceitos, por uma pessoa no
  login por e-mail. 3 créditos de teste por CNPJ; depois, cada chamada custa o preço da tabela versionada
  (raiz/regras/padroes/api_publica.yaml) e sai do saldo; sem saldo, 402 com o link de uma recarga por Pix que uma
  pessoa paga (o agente nunca paga). Chamada que falha não custa (estorno).
- Liberação, igual ao app: montar lote e ver o detalhe das fazendas só depois do sinal pago por Pix e do contrato
  aceito com a cláusula de não contornar. Pagar a API não pula essa trava.
- Anti-raspagem: limite por empresa (SlowAPI, por minuto, dia e mês; 429 com Retry-After), registro de quem viu qual
  fazenda, alerta ao fundador e bloqueio automático do padrão de varredura; uso em volume é licença de dados.
- Os números agregados por município ficam só no site público (grátis), não aqui.
- Erros no padrão RFC 9457 (application/problem+json) dizendo o que corrigir. Nunca devolve nome, CPF, CNPJ ou
  contato de dono de fazenda; o contato com os donos passa pela Raíz.
"""

import html
import logging
import os
import time
from collections.abc import Callable
from typing import Annotated, Any, Literal
from urllib.parse import parse_qsl, urlsplit

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from raiz.pedidos import servico as S
from raiz.pedidos.campos import CamposPedido
from raiz.publica import apresentacao as AP
from raiz.publica import chaves as K
from raiz.publica import conta as CT
from raiz.publica.contrato import RESUMO
from raiz.publica.oauth import acesso_interno
from raiz.publica.problemas import ERROS_COMUNS, problema

VERSAO = "1.1.0"
log = logging.getLogger(__name__)

PRODUTOS = """
## Os 4 produtos que só a Raíz tem

1. **Certidão lida por IA, com "já comprometida"** (`GET /v1/fazendas/{cod}/analise`): matrícula lida e conferida
   (ônus, contrato averbado de arrendamento ou de carbono), sobreposição com projeto de carbono, terra pública, terra
   indígena, quilombo e REDD+ jurisdicional, e se a fazenda já está comprometida. Para **advogados**, **bancos**
   (garantia rural) e **Fiagro** (lastro).
2. **Valor de restauração por fazenda** (na mesma análise e nas opções do lote): método, custo, captura, crédito
   líquido P10/P50/P90, TIR, preço de equilíbrio, reserva de não permanência e rebanho. Para **desenvolvedores de
   restauração**, **bancos** e **Fiagro**.
3. **Nível de interesse do dono** (nas opções e no andamento): do sem contato ao contrato firme, sem dado pessoal.
   Para **tradings** (EUDR) e **frigoríficos** com meta FLAG.
4. **Previsões conferidas com o real** (`GET /v1/previsoes/precisao`): acerto, erro e cobertura da faixa P10 a P90
   por modelo e versão. Para **seguradoras** e **bancos** (risco de modelo).
"""

DESCRICAO = f"""
API pública da **Raíz**: o cliente pede, por exemplo, **"1 milhão de créditos de carbono líquidos no Pará, no
cronograma do ProFloresta+"** e a Raíz monta o melhor lote no mapa inteiro, em **3 opções** (mais barata, mais segura,
mais compacta), com créditos P10/P50/P90, hectares, fazendas (pequenas agrupadas, nunca descartadas), custo por crédito,
TIR, chance de cada marco, mistura do caminho da terra e fazendas de reserva.

**Paga, sem plano grátis.** Uma pessoa da empresa abre a conta com o CNPJ e aceita os termos (`POST /v1/conta`) e cria
a chave do agente (`POST /v1/chaves`). 3 créditos de teste por empresa; depois, cada chamada custa o preço da tabela
(`GET /v1/conta`). Sem saldo: **402** com o link de uma recarga por Pix, que uma pessoa paga. Chamada que falha não
custa.

**Liberação, igual ao app:** montar lote e ver o detalhe das fazendas só depois do **sinal pago por Pix** e do
**contrato com a cláusula de não contornar**. Nunca devolvemos nome, CPF, CNPJ ou contato de dono.

**Limites e anti-raspagem:** limite por empresa por minuto, dia e mês (**429** com `Retry-After`); registro de quem
viu qual fazenda; bloqueio automático de quem varre a base. Uso em volume é licença de dados. Os números agregados por
município ficam só no site público.

**Erros** no padrão RFC 9457 (`application/problem+json`), sempre com `corrigir`.
{PRODUTOS}"""

TAGS = [
    {"name": "Pedido de lote", "description": "Quanto existe na base, montar o lote e comparar as 3 opções."},
    {"name": "Interesse dos donos", "description": "A Raíz busca o interesse dos donos em ondas; o andamento."},
    {"name": "Reserva", "description": "O agente prepara; uma pessoa da empresa aprova e paga."},
    {"name": "Produto 1 e 2: análise da fazenda", "description": "Certidão lida por IA com \"já comprometida\", "
     "sobreposição e valor de restauração da fazenda (R$ 1.500, linha 3 do modelo)."},
    {"name": "Produto 4: previsões conferidas", "description": "Acerto das previsões da Raíz contra o real."},
    {"name": "Conta da empresa", "description": "CNPJ, termos, saldo, extrato, liberação, chaves e chamadas."},
]  # fmt: skip

TERMOS = """Termos de uso da API e do MCP da Raíz ({versao})

1. A conta é da empresa (CNPJ). A chave é da empresa: não revenda nem compartilhe.
2. É proibido montar base própria com os dados da Raíz: copiar, varrer ou guardar em massa fazendas, municípios ou
   resultados para reconstruir o mapa. A Raíz registra quem consultou o quê e bloqueia o padrão de varredura. Uso em
   volume é licença de dados, com preço separado e aprovação do fundador.
3. Montar lote e ver o detalhe das fazendas exige o sinal pago e o contrato com a cláusula de não contornar.
4. A Raíz nunca entrega nome, CPF, CNPJ ou contato de dono. O contato com os donos passa pela Raíz.
5. Toda chamada custa o preço da tabela vigente (versão gravada em cada lançamento); chamada que falha é estornada.
6. Pagamentos (recarga, sinal, reserva) são aprovados e feitos por uma pessoa da empresa, nunca pelo agente.
7. Os números são estimativas com faixa P10 a P90 e versão do modelo; não são laudo nem oferta firme.
"""

EXEMPLO_PEDIDO = {
    "meta": {"tipo": "creditos", "valor": 1_000_000}, "cronograma": "profloresta",
    "onde": {"ufs": ["PA"], "biomas": ["Amazônia"]}, "dinheiro": {"custo_max_usd_credito": 60, "preco_venda_usd": 55},
    "metodos": ["regeneracao_assistida", "semeadura_direta", "plantio_total"],
    "terra": ["matricula_conferida", "matricula_a_conferir", "concessao"], "interesse": "qualquer",
}  # fmt: skip
EXEMPLOS_PEDIDO = {"um_milhao_no_para": {"summary": "1 milhão de créditos no Pará (ProFloresta+)",
                                         "value": EXEMPLO_PEDIDO}}  # fmt: skip
EXEMPLO_BASE = {
    "fazendas": 3120, "hectares": 158_400.5, "creditos": {"p10": 9_850_000, "p50": 14_200_000, "p90": 17_900_000},
    "por_caminho": [{"caminho": "matricula_a_conferir", "fazendas": 410, "creditos_p50": 2_150_000}],
}  # fmt: skip
EXEMPLO_CONTA = {
    "cnpj": "12.***.***/0001-**", "testes_restantes": 3, "saldo_rs": 0.0, "liberada": False,
    "precos": {"consultar_disponibilidade": 40, "pedir_lote": 400, "analise_fazenda": 1500}, "bloqueada": False,
}  # fmt: skip


def _ok(exemplo: Any, descricao: str = "Tudo certo") -> dict:
    return {200: {"description": descricao, "content": {"application/json": {"example": exemplo}}}, **ERROS_COMUNS}


class AbrirConta(BaseModel):
    cnpj: str = Field(description="CNPJ da empresa (guardado só em hash e mascarado).", examples=["12.***.***/0001-**"])
    aceito_termos: bool = Field(description="A empresa aceita os termos de uso (GET /v1/termos).")


class NovaChave(BaseModel):
    rotulo: str | None = Field(None, description="Qual agente usa a chave.", examples=["agente de compras"])


class Solicitar(BaseModel):
    opcao: Literal["barata", "segura", "compacta"] = Field("segura", description="A opção que vai para os donos.")


class Mudanca(BaseModel):
    opcao: Literal["barata", "segura", "compacta"]
    acao: Literal["tirar", "trocar"]
    cod_imovel: str
    por: str | None = None


SOLICITAR_PADRAO = Solicitar()


def _criar_limitador(uri: str):
    """Valkey pelo cliente Redis: conexão/leitura de 0,5 s, nenhuma repetição ou fallback local.

    Suporta explicitamente redis://, rediss:// e redis+unix://. memory:// permanece
    disponível para um único processo/testes. Outros backends exigem política de prazo própria.
    """
    from slowapi import Limiter

    esquema = urlsplit(uri).scheme
    opcoes = {"wrap_exceptions": True}
    if esquema in {"redis", "rediss", "redis+unix"}:
        from redis.backoff import NoBackoff
        from redis.retry import Retry

        # redis.from_url dá precedência à query. Não permitir que ela desfaça o prazo ou habilite retries.
        protegidas = {"socket_timeout", "socket_connect_timeout", "health_check_interval", "redis_connect_func"}
        if any(k in protegidas or k.startswith("retry") for k, _ in parse_qsl(urlsplit(uri).query)):
            raise ValueError("a URL do limitador não pode alterar prazos nem repetições")
        opcoes.update(
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
            retry=Retry(NoBackoff(), 0),
            retry_on_timeout=False,
            retry_on_error=[],
            health_check_interval=0,
        )
    elif esquema != "memory":
        raise ValueError("limitador admite memory://, redis://, rediss:// ou redis+unix://")
    limiter = Limiter(
        key_func=_cliente,
        storage_uri=uri,
        storage_options=opcoes,
        swallow_errors=False,
        in_memory_fallback_enabled=False,
    )
    # SlowAPI também lê RATELIMIT_* do ambiente/.env; rejeitar configuração que libere chamadas em falha.
    if not limiter.enabled or limiter._swallow_errors or limiter._in_memory_fallback_enabled:
        raise ValueError("o limitador exige armazenamento ativo, sem ignorar erros ou fallback em memória")
    return limiter


def criar(engine_de: Callable[[Request], Any], verificador=None) -> FastAPI:
    """A aplicação da API pública (montada em /v1 pela aplicação principal)."""
    from limits.errors import StorageError
    from slowapi.errors import RateLimitExceeded

    app = FastAPI(title="Raíz: API pública do pedido de lote", version=VERSAO, description=RESUMO + "\n" + PRODUTOS,
                  openapi_tags=TAGS, docs_url="/docs", redoc_url="/redoc", openapi_url="/openapi.json",
                  servers=[{"url": "/v1", "description": "esta instalação"}])  # fmt: skip
    lim = CT.premissas()["limites"]
    limiter = _criar_limitador(os.environ.get("RAIZ_API_LIMIT_STORAGE_URI", "memory://"))
    LIMITE = f"{lim['por_minuto']}/minute;{lim['por_dia']}/day;{lim['por_mes']}/month"
    app.state.limiter = limiter

    def instancia(request: Request) -> str:
        # Template da rota: nunca o token de aprovação nem um valor livre no caminho.
        return getattr(request.scope.get("route"), "path", "/v1")

    @app.exception_handler(StorageError)
    async def _armazenamento_limite(request: Request, ex: StorageError):
        return problema(
            503,
            "limite_indisponivel",
            "não foi possível verificar o limite da empresa",
            "repita mais tarde com a mesma Idempotency-Key",
            instancia(request),
            headers={"Retry-After": "1"},
        )

    @app.exception_handler(CT.ErroConta)
    async def _conta(request: Request, ex: CT.ErroConta):
        return problema(ex.status, ex.slug, ex.detalhe, ex.corrigir, instancia(request), **ex.extra)

    from raiz.publica.aprovacao import ErroAprovacao
    from raiz.publica.email_login import ErroEnvioLogin

    @app.exception_handler(ErroEnvioLogin)
    async def _email(request: Request, ex: ErroEnvioLogin):
        return problema(
            503, "email_indisponivel", "não foi possível enviar o link de entrada", "tente novamente mais tarde"
        )

    @app.exception_handler(ErroAprovacao)
    async def _aprovacao(request: Request, ex: ErroAprovacao):
        return problema(ex.status, "aprovacao", str(ex), "confira a sessão, o prazo e as condições da reserva")

    @app.exception_handler(S.ErroPedido)
    async def _pedido(request: Request, ex: S.ErroPedido):
        msg = str(ex)
        st = 404 if "não encontrad" in msg else 422
        return problema(st, "pedido", msg, "confira o id do pedido e o estado dele (GET /v1/pedidos/{id})",
                        instancia(request))  # fmt: skip

    @app.exception_handler(HTTPException)
    async def _http(request: Request, ex: HTTPException):
        d = ex.detail if isinstance(ex.detail, dict) else {"mensagem": str(ex.detail)}
        return problema(ex.status_code, d.get("slug", f"http_{ex.status_code}"), d.get("mensagem", ""),
                        d.get("corrigir", "confira o pedido"), instancia(request), headers=ex.headers)  # fmt: skip

    @app.exception_handler(RequestValidationError)
    async def _validacao(request: Request, ex: RequestValidationError):
        campos = [".".join(str(x) for x in e.get("loc", []) if x != "body") + f": {e.get('msg')}" for e in ex.errors()]
        return problema(422, "dados_invalidos", "o corpo ou os parâmetros não passaram na validação",
                        "corrija: " + "; ".join(campos[:10]), instancia(request), campos=campos[:20])  # fmt: skip

    @app.exception_handler(RateLimitExceeded)
    async def _limite(request: Request, ex: RateLimitExceeded):
        try:
            espera = int(ex.limit.limit.get_expiry())
        except Exception:  # noqa: BLE001
            espera = 60
        return problema(429, "limite", f"passou do limite da empresa ({ex.detail})",
                        f"espere {espera} s e repita; uso em volume é licença de dados", instancia(request),
                        headers={"Retry-After": str(espera)})  # fmt: skip

    def acesso(request: Request,
               x_chave_api: Annotated[str | None, Header(description="Chave de API da empresa (raiz_...).")] = None,
               authorization: Annotated[str | None, Header(description="Bearer raiz_... ou a sessão do login.")] = None,
               ) -> K.Acesso:  # fmt: skip
        eng = engine_de(request)
        bruto = (x_chave_api or (authorization or "").removeprefix("Bearer ").strip()).strip()
        a = acesso_interno(request)
        if a is None:
            a = K.acesso_da_chave(eng, bruto) if bruto.startswith(K.PREFIXO) else None
        if a is None and bruto and not bruto.startswith(K.PREFIXO):
            cid = S.cliente_da_sessao(eng, bruto)
            a = K.Acesso(int(cid), None, "sessao") if cid is not None else None
        if a is None:
            raise HTTPException(401, {"slug": "sem_credencial", "mensagem": "faltou a chave de API da empresa ou ela "
                                      "foi revogada", "corrigir": "mande a chave em X-Chave-API (ou Authorization: "
                                      "Bearer raiz_...); uma pessoa da empresa cria em POST /v1/chaves"})  # fmt: skip
        request.state.acesso = a
        request.state.cliente_id = a.cliente_id
        # Antes das dependências de cobrança/liberação: recusas também contam.
        if not getattr(request.state, "_rate_limiting_complete", False):
            limiter._check_request_limit(request, request.scope.get("endpoint"), False)
            request.state._rate_limiting_complete = True
        return a

    def pessoa(a: Annotated[K.Acesso, Depends(acesso)]) -> K.Acesso:
        if a.via != "sessao":
            raise HTTPException(
                403,
                {
                    "slug": "so_pessoa",
                    "mensagem": "só uma pessoa da empresa (login por e-mail) faz isto",
                    "corrigir": "entre pelo e-mail (POST /entrar) e use a sessão",
                },
            )
        return a

    def cobrar(ferramenta: str, liberacao: bool = False):
        def dep(request: Request, a: Annotated[K.Acesso, Depends(acesso)]) -> int | None:
            eng = engine_de(request)
            request.state.ferramenta = ferramenta
            from raiz.publica.rotas_agentes import exigir_escopo

            if ferramenta in {
                "consultar_disponibilidade",
                "pedir_lote",
                "comparar_lotes",
                "acompanhar_contato",
                "preparar_reserva",
            }:
                exigir_escopo(eng, a, ferramenta)
            if liberacao:
                CT.exigir_liberacao(eng, a.cliente_id)
            lanc = CT.cobrar(eng, a.cliente_id, ferramenta, _base(request))
            request.state.lancamento = lanc
            request.state.preco = CT.valor_cobrado(eng, lanc)
            return lanc

        return dep

    @app.middleware("http")
    async def registrar(request: Request, call_next):
        t0 = time.monotonic()
        try:
            resp = await call_next(request)
        except Exception as ex:  # noqa: BLE001 - falha interna também deve estornar e não revelar dados
            log.error("falha interna na API pública (%s)", type(ex).__name__)
            resp = problema(
                500,
                "falha_interna",
                "não foi possível concluir a chamada",
                "a chamada não será cobrada; tente novamente",
                instancia(request),
            )
        a = getattr(request.state, "acesso", None)
        if a is None:
            return resp
        from raiz import restauracao as R
        from raiz.pedidos.premissas import versao_modelo

        eng = engine_de(request)
        ferr = getattr(request.state, "ferramenta", None)
        rota = request.scope.get("route")
        pp = request.scope.get("path_params") or {}
        lanc = getattr(request.state, "lancamento", None)
        pago = resp.status_code < 400
        try:
            if not pago:
                CT.estornar(eng, lanc)
            cid = K.registrar(eng, cliente_id=a.cliente_id, chave_id=a.chave_id, via=a.via,
                              ferramenta=ferr or getattr(rota, "name", "") or "?", metodo=request.method,
                              rota=getattr(rota, "path", request.url.path),
                              pedido_id=pp.get("pedido_id") or getattr(request.state, "pedido_id", None),
                              cod_imovel=pp.get("cod_imovel"), alcance=getattr(request.state, "alcance", None),
                              status=resp.status_code, ms=int(1000 * (time.monotonic() - t0)),
                              preco_rs=getattr(request.state, "preco", None) if pago and lanc else 0.0,
                              versao_modelo=versao_modelo(), versao_premissas=R.versao(),
                              agente_modelo=request.headers.get("x-agente-modelo"))  # fmt: skip
            if pago:
                CT.registrar_exposicao(eng, cid, a.cliente_id, getattr(request.state, "cods_expostos", []))
                if ferr:
                    CT.vigiar_raspagem(eng, a.cliente_id)
        except Exception as ex:  # noqa: BLE001 - não registrar corpo, token nem dados pessoais de uma exceção
            log.error("registro da chamada falhou (%s)", type(ex).__name__)
        return resp

    def ok(x: Any) -> JSONResponse:
        from raiz.publica.privacidade import para_resposta

        return JSONResponse(para_resposta(x))

    Acesso = Annotated[K.Acesso, Depends(acesso)]
    Pessoa = Annotated[K.Acesso, Depends(pessoa)]
    Pid = Annotated[str, Path(description="Id do pedido (uuid).")]

    @app.get("/", tags=["Pedido de lote"], summary="Sobre a API")
    def sobre() -> dict:
        return {"nome": "Raíz", "versao": VERSAO, "documentacao": "/v1/docs", "openapi": "/v1/openapi.json",
                "termos": "/v1/termos", "precos": CT.premissas()["precos"]}  # fmt: skip

    @app.get("/termos", tags=["Conta da empresa"], summary="Termos de uso", response_class=HTMLResponse)
    def termos() -> HTMLResponse:
        t = TERMOS.format(versao=CT.premissas()["termos_versao"])
        return HTMLResponse(f"<pre style='white-space:pre-wrap;font-family:system-ui'>{html.escape(t)}</pre>")

    @app.post(
        "/conta",
        tags=["Conta da empresa"],
        summary="Abrir a conta da empresa (CNPJ e termos)",
        responses=_ok(EXEMPLO_CONTA, "Conta aberta com 3 créditos de teste"),
    )
    @limiter.shared_limit(LIMITE, scope="empresa")
    def abrir_conta(corpo: AbrirConta, request: Request, a: Pessoa) -> JSONResponse:
        return ok(CT.abrir(engine_de(request), a.cliente_id, corpo.cnpj, corpo.aceito_termos))

    @app.get(
        "/conta", tags=["Conta da empresa"], summary="Saldo, testes, liberação e preços", responses=_ok(EXEMPLO_CONTA)
    )
    @limiter.shared_limit(LIMITE, scope="empresa")
    def ver_conta(request: Request, a: Acesso) -> JSONResponse:
        return ok(CT.exigir(engine_de(request), a.cliente_id))

    @app.get("/conta/extrato", tags=["Conta da empresa"], summary="Extrato (testes, débitos, estornos, recargas)")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def extrato(request: Request, a: Acesso) -> JSONResponse:
        CT.exigir(engine_de(request), a.cliente_id)
        return ok(CT.extrato(engine_de(request), a.cliente_id))

    @app.post("/conta/contrato", tags=["Conta da empresa"], summary="Aceitar o contrato de não contornar")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def contrato(request: Request, a: Pessoa) -> JSONResponse:
        return ok(CT.aceitar_contrato(engine_de(request), a.cliente_id))

    @app.post("/conta/sinal", tags=["Conta da empresa"], summary="Gerar o Pix do sinal (uma pessoa paga)")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def sinal(request: Request, a: Acesso) -> JSONResponse:
        eng = engine_de(request)
        CT.exigir(eng, a.cliente_id)
        return ok(CT.criar_cobranca(eng, a.cliente_id, "sinal", float(CT.premissas()["liberacao"]["sinal_rs"]),
                                    _base(request)))  # fmt: skip

    @app.post("/conta/recarga", tags=["Conta da empresa"], summary="Gerar uma recarga do saldo (uma pessoa paga)")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def recarga(
        request: Request,
        a: Acesso,
        valor_rs: Annotated[float | None, Query(gt=0, le=999999999999, allow_inf_nan=False)] = None,
    ) -> JSONResponse:
        eng = engine_de(request)
        CT.exigir(eng, a.cliente_id)
        v = max(float(valor_rs or 0), float(CT.premissas()["recarga"]["minimo_rs"]))
        return ok(CT.criar_cobranca(eng, a.cliente_id, "recarga", v, _base(request)))

    @app.get(
        "/cobrancas/{token}",
        tags=["Conta da empresa"],
        summary="Página do Pix (para uma pessoa)",
        response_class=HTMLResponse,
    )
    def pagina_cobranca(token: str, request: Request) -> HTMLResponse:
        c = CT.cobranca_pelo_link(engine_de(request), token)
        if c is None:
            return HTMLResponse("<p>Link inválido.</p>", status_code=404)
        titulo = "Recarga do saldo da API" if c["finalidade"] == "recarga" else "Sinal da liberação"
        return HTMLResponse(f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Pix da Raíz
</title></head><body style="font-family:system-ui;max-width:560px;margin:40px auto;padding:0 16px"><h1>{titulo}</h1>
<p>Valor: R$ {c["valor_rs"]:.2f}. Situação: {html.escape(c["estado"])}.</p><p>Pix copia e cola:</p>
<textarea readonly rows="4" style="width:100%">{html.escape(c["pix_copia_cola"] or "")}</textarea></body></html>""")

    @app.post("/chaves", tags=["Conta da empresa"], summary="Criar a chave do agente (a chave aparece uma vez)")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def nova_chave(corpo: NovaChave, request: Request, a: Pessoa) -> dict:
        return K.criar(engine_de(request), a.cliente_id, corpo.rotulo)

    @app.get("/chaves", tags=["Conta da empresa"], summary="Chaves da empresa (só o prefixo)")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def listar_chaves(request: Request, a: Pessoa) -> list[dict]:
        return K.listar(engine_de(request), a.cliente_id)

    @app.delete("/chaves/{prefixo}", tags=["Conta da empresa"], summary="Revogar uma chave")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def revogar(prefixo: str, request: Request, a: Pessoa) -> dict:
        if not K.revogar(engine_de(request), a.cliente_id, prefixo):
            raise HTTPException(404, {"slug": "chave", "mensagem": "chave não encontrada ou já revogada",
                                      "corrigir": "confira o prefixo em GET /v1/chaves"})  # fmt: skip
        return {"revogada": prefixo}

    @app.get("/chamadas", tags=["Conta da empresa"], summary="O que os agentes da empresa fizeram")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def chamadas(request: Request, a: Acesso, pedido_id: str | None = None) -> JSONResponse:
        CT.exigir(engine_de(request), a.cliente_id)
        return ok(K.chamadas(engine_de(request), a.cliente_id, pedido_id))

    @app.post(
        "/disponibilidade",
        tags=["Pedido de lote"],
        summary="Quanto existe na base (consultar_disponibilidade)",
        responses=_ok(EXEMPLO_BASE),
    )
    @limiter.shared_limit(LIMITE, scope="empresa")
    def disponibilidade(campos: Annotated[CamposPedido, Body(openapi_examples=EXEMPLOS_PEDIDO)], request: Request,
                        a: Acesso, _c: Annotated[Any, Depends(cobrar("consultar_disponibilidade"))]) -> JSONResponse:  # fmt: skip  # noqa: E501
        """Totais do pedido (sem fazenda, sem número por município). Vale crédito de teste."""
        request.state.alcance = {"ufs": campos.onde.ufs, "municipios": [str(m) for m in campos.onde.municipios],
                                 "biomas": campos.onde.biomas, "meta": campos.meta.valor}  # fmt: skip
        return ok(AP.base(S.base_disponivel(engine_de(request), a.cliente_id, campos)))

    @app.post("/pedidos", tags=["Pedido de lote"], summary="Montar o lote em 3 opções (pedir_lote)")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def pedir_lote(
        campos: Annotated[CamposPedido, Body(openapi_examples=EXEMPLOS_PEDIDO)],
        request: Request,
        a: Acesso,
        idempotency_key: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        """Pessoa usa o painel; agentes recebem o protocolo persistido do trabalho."""
        if a.via != "sessao":
            return _trabalho(request, a, "pedir_lote", campos.model_dump(mode="json"), idempotency_key)
        cobrar("pedir_lote", liberacao=True)(request, a)
        p = S.criar_pedido(engine_de(request), a.cliente_id, campos)
        request.state.pedido_id = p["id"]
        request.state.cods_expostos = [i["cod_imovel"] for o in p.get("opcoes") or [] for i in o.get("itens") or []]
        return ok(AP.pedido(p))

    @app.get("/pedidos", tags=["Pedido de lote"], summary="Pedidos da empresa (sem custo)")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def listar(request: Request, a: Acesso) -> JSONResponse:
        CT.exigir(engine_de(request), a.cliente_id)
        return ok(AP.resumos(S.pedidos_do_cliente(engine_de(request), a.cliente_id)))

    @app.get("/pedidos/{pedido_id}", tags=["Pedido de lote"], summary="Detalhe do pedido")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def detalhe(
        pedido_id: Pid,
        request: Request,
        a: Acesso,
        _c: Annotated[Any, Depends(cobrar("comparar_lotes", liberacao=True))],
    ) -> JSONResponse:
        pedido = S.obter_pedido(engine_de(request), pedido_id, a.cliente_id)
        request.state.cods_expostos = [i["cod_imovel"] for o in pedido["opcoes"] for i in o.get("itens", [])]
        return ok(AP.pedido(pedido))

    @app.get("/pedidos/{pedido_id}/alertas", tags=["Pedido de lote"])
    @limiter.shared_limit(LIMITE, scope="empresa")
    def alertas_pedido(pedido_id: Pid, request: Request, a: Acesso) -> JSONResponse:
        CT.exigir_liberacao(engine_de(request), a.cliente_id)
        return ok(AP.alertas(S.obter_pedido(engine_de(request), pedido_id, a.cliente_id)["alertas"]))

    @app.post("/pedidos/{pedido_id}/revisoes", tags=["Pedido de lote"])
    @limiter.shared_limit(LIMITE, scope="empresa")
    def solicitar_revisao(
        pedido_id: Pid, request: Request, a: Pessoa, cod_imovel: Annotated[str, Body()], motivo: Annotated[str, Body()]
    ) -> JSONResponse:
        from raiz import salvaguardas as SG

        CT.exigir_liberacao(engine_de(request), a.cliente_id)
        return ok(AP.revisao(SG.solicitar_revisao(engine_de(request), pedido_id, a.cliente_id, cod_imovel, motivo)))

    @app.get("/pedidos/{pedido_id}/revisoes", tags=["Pedido de lote"])
    @limiter.shared_limit(LIMITE, scope="empresa")
    def revisoes(pedido_id: Pid, request: Request, a: Pessoa) -> JSONResponse:
        from raiz import salvaguardas as SG

        CT.exigir_liberacao(engine_de(request), a.cliente_id)
        return ok([AP.revisao(r) for r in SG.listar_revisoes(engine_de(request), pedido_id, a.cliente_id)])

    @app.get("/notificacoes", tags=["Conta da empresa"])
    @limiter.shared_limit(LIMITE, scope="empresa")
    def notificacoes(request: Request, a: Pessoa) -> JSONResponse:
        CT.exigir(engine_de(request), a.cliente_id)
        return ok(AP.notificacoes(S.notificacoes(engine_de(request), a.cliente_id)))

    @app.get("/pedidos/{pedido_id}/opcoes", tags=["Pedido de lote"], summary="As 3 opções lado a lado (comparar_lotes)")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def comparar(pedido_id: Pid, request: Request, a: Acesso,
                 _c: Annotated[Any, Depends(cobrar("comparar_lotes", liberacao=True))]) -> JSONResponse:  # fmt: skip
        ops = S.obter_pedido(engine_de(request), pedido_id, a.cliente_id)["opcoes"]
        request.state.cods_expostos = [i["cod_imovel"] for o in ops for i in o.get("itens") or []]
        return ok(AP.opcoes(ops))

    @app.patch("/pedidos/{pedido_id}", tags=["Pedido de lote"])
    @app.post("/pedidos/{pedido_id}/lote", tags=["Pedido de lote"], summary="Tirar ou trocar uma fazenda")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def mudar(pedido_id: Pid, m: Mudanca, request: Request, a: Acesso,
              _c: Annotated[Any, Depends(cobrar("comparar_lotes", liberacao=True))]) -> JSONResponse:  # fmt: skip
        return ok(AP.pedido(S.mudar_lote(engine_de(request), pedido_id, a.cliente_id, m.model_dump())))

    @app.post(
        "/pedidos/{pedido_id}/solicitar-interesse",
        tags=["Interesse dos donos"],
        summary="A Raíz busca o interesse dos donos",
    )
    @limiter.shared_limit(LIMITE, scope="empresa")
    def solicitar(pedido_id: Pid, request: Request, a: Acesso,
                  _c: Annotated[Any, Depends(cobrar("solicitar_interesse", liberacao=True))],
                  corpo: Annotated[Solicitar, Body()] = SOLICITAR_PADRAO) -> JSONResponse:  # fmt: skip
        return ok(AP.pedido(S.solicitar_interesse(engine_de(request), pedido_id, a.cliente_id, corpo.opcao)))

    @app.get("/pedidos/{pedido_id}/andamento", tags=["Interesse dos donos"], summary="Andamento (acompanhar_contato)")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def andamento(
        pedido_id: Pid,
        request: Request,
        a: Acesso,
        _c: Annotated[Any, Depends(cobrar("acompanhar_contato", liberacao=True))],
    ) -> JSONResponse:
        return ok(AP.andamento(S.andamento(engine_de(request), pedido_id, a.cliente_id)))

    @app.post("/pedidos/{pedido_id}/reservar", tags=["Reserva"], summary="Preparar a reserva (uma pessoa aprova)")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def reservar(
        pedido_id: Pid,
        request: Request,
        a: Acesso,
        idempotency_key: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        from raiz.publica.rotas_agentes import base_publica

        if a.via != "sessao":
            return _trabalho(request, a, "preparar_reserva", {"pedido_id": pedido_id}, idempotency_key)
        cobrar("preparar_reserva", liberacao=True)(request, a)
        return ok(S.reservar(engine_de(request), pedido_id, a.cliente_id, base_url=base_publica()))

    @app.get("/pedidos/{pedido_id}/reserva", tags=["Reserva"], summary="Situação da reserva (sem custo)")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def reserva(pedido_id: Pid, request: Request, a: Acesso) -> JSONResponse:
        CT.exigir_liberacao(engine_de(request), a.cliente_id)
        return ok(S.cobranca_do_pedido(engine_de(request), pedido_id, a.cliente_id))

    @app.get("/reservas/confirmar/{token}", tags=["Reserva"], response_class=HTMLResponse)
    def pagina_confirmar(token: str) -> HTMLResponse:
        import re

        from raiz.publica.pagina_aprovacao import pagina

        if not re.fullmatch(r"[A-Za-z0-9_-]{20,100}", token):
            raise HTTPException(404, "link inválido")
        return pagina(token)

    @app.get("/reservas/confirmar/{token}/resumo", tags=["Reserva"])
    @limiter.shared_limit(LIMITE, scope="empresa")
    def resumo_confirmacao(token: str, request: Request, a: Pessoa):
        from raiz.publica.aprovacao import ver

        CT.exigir_liberacao(engine_de(request), a.cliente_id)
        return JSONResponse(ver(engine_de(request), token, a.cliente_id), headers={"Cache-Control": "no-store"})

    @app.post("/reservas/confirmar/{token}/entrar", tags=["Reserva"])
    @limiter.shared_limit("5/minute", scope="login_aprovacao")
    def entrar_aprovacao(token: str, request: Request, email: Annotated[str, Body(embed=True)]):
        from sqlalchemy import text

        from raiz.pessoal import Cofre
        from raiz.publica.rotas_agentes import base_publica

        if S.ENVIO_LINK is None:
            raise HTTPException(503, "envio de login por e-mail indisponível")
        with engine_de(request).connect() as con:
            esperado = con.execute(
                text("""select pc.email_hmac from negocio.reserva r
                join pessoal.cliente_contato pc on pc.cliente_id=r.cliente_id
                where r.confirmacao_hash=:h and r.estado='aguardando_confirmacao'
                and r.confirmacao_expira > now()"""),
                {"h": S._hash(token)},
            ).scalar()
        if esperado is not None and Cofre().indice(email.strip().lower()) == esperado:
            S.pedir_link(engine_de(request), email, base_publica() + f"/reservas/confirmar/{token}")
        return JSONResponse({"enviado": True}, headers={"Cache-Control": "no-store"})

    @app.post("/reservas/confirmar/{token}", tags=["Reserva"])
    @limiter.shared_limit(LIMITE, scope="empresa")
    def confirmar(token: str, request: Request, a: Pessoa):
        from raiz.publica.aprovacao import aprovar

        CT.exigir_liberacao(engine_de(request), a.cliente_id)
        return JSONResponse(aprovar(engine_de(request), token, a.cliente_id), headers={"Cache-Control": "no-store"})

    @app.get("/recibos/jwks.json", tags=["Reserva"])
    def chave_recibo():
        from raiz.publica.recibos import jwk

        return {"keys": [jwk()]}

    @app.get(
        "/fazendas/{cod_imovel}/ficha",
        tags=["Produto 1 e 2: análise da fazenda"],
        summary="Reler ficha já adquirida, sem nova tarifa",
    )
    @limiter.shared_limit(LIMITE, scope="empresa")
    def consultar_ficha(cod_imovel: str, request: Request, a: Acesso) -> JSONResponse:
        """Mesma ficha da prospecção, com fontes, datas e ausências. Não compra nem desbloqueia acesso."""
        from raiz import prospeccao_servico
        from raiz.prospeccao_acesso import ErroAcesso
        from raiz.publica.rotas_agentes import exigir_escopo

        eng = engine_de(request)
        request.state.ferramenta = "consultar_ficha"
        exigir_escopo(eng, a, "consultar_ficha")
        CT.exigir_liberacao(eng, a.cliente_id)
        try:
            prospeccao_servico.limitar_consulta(eng, a.cliente_id)
            ficha = prospeccao_servico.consultar_ficha(
                eng, a.cliente_id, cod_imovel, canal="site" if a.via == "sessao" else a.via
            )
        except ErroAcesso as ex:
            raise HTTPException(
                ex.status,
                {
                    "slug": "ficha_indisponivel",
                    "mensagem": str(ex),
                    "corrigir": "confira a liberação desta ficha na sua conta; esta leitura não compra acesso",
                },
                headers={"Retry-After": str(ex.retry_after)} if ex.retry_after is not None else None,
            ) from None
        request.state.cods_expostos = [ficha["codigo_car"]]
        resposta = ok(ficha)
        resposta.headers["Cache-Control"] = "private, no-store"
        resposta.headers["Vary"] = "Authorization, X-Chave-API"
        return resposta

    @app.get(
        "/fazendas/{cod_imovel}/analise",
        tags=["Produto 1 e 2: análise da fazenda"],
        summary="Análise de uma fazenda (R$ 1.500)",
    )
    @limiter.shared_limit(LIMITE, scope="empresa")
    def analise(cod_imovel: str, request: Request, a: Acesso,
                _c: Annotated[Any, Depends(cobrar("analise_fazenda", liberacao=True))]) -> JSONResponse:  # fmt: skip
        """Certidão lida por IA, sobreposição, "já comprometida" e simulação P10/P50/P90. Sem dado pessoal."""
        from raiz.publica.fazenda import analisar

        x = analisar(engine_de(request), cod_imovel)
        if x is None:
            raise HTTPException(404, {"slug": "fazenda", "mensagem": "fazenda não encontrada na base da Raíz",
                                      "corrigir": "confira o código do CAR"})  # fmt: skip
        request.state.cods_expostos = [x["cod_imovel"]]
        return ok(AP.analise(x))

    @app.get("/previsoes/precisao", tags=["Produto 4: previsões conferidas"], summary="Acerto das previsões da Raíz")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def precisao(request: Request, a: Acesso,
                 _c: Annotated[Any, Depends(cobrar("precisao_previsoes"))]) -> JSONResponse:  # fmt: skip
        from raiz.aprendizado.registro import placar

        with engine_de(request).connect() as con:
            linhas = [dict(r._mapping) for r in placar(con)]
        return ok([{k: (float(v) if hasattr(v, "as_integer_ratio") else v) for k, v in li.items()} for li in linhas])

    def _trabalho(request, a, ferramenta, corpo, chave):
        from raiz.publica import trabalhos as T
        from raiz.publica.rotas_agentes import base_publica, exigir_escopo

        eng = engine_de(request)
        exigir_escopo(eng, a, ferramenta)
        if not chave:
            raise CT.ErroConta(
                "idempotencia_obrigatoria", "falta Idempotency-Key", "gere uma chave para a intenção", 422
            )
        if ferramenta == "preparar_reserva":
            corpo = {**corpo, "base_url": base_publica()}
        r = T.submeter(eng, a.cliente_id, ferramenta, corpo, chave)
        request.state.ferramenta = ferramenta
        request.state.pedido_id = r["pedido_id"]
        return JSONResponse(r, status_code=202, headers={"Location": f"/v1/operacoes/{r['pedido_id']}"})

    from raiz.publica.rotas_agentes import instalar

    instalar(app, engine_de, acesso, limiter, LIMITE, verificador)
    from raiz.publica.rotas_webhooks import instalar as instalar_webhooks

    instalar_webhooks(app, engine_de, pessoa, limiter, LIMITE)
    return app


def _cliente(request: Request) -> str:
    a = getattr(request.state, "acesso", None)
    return f"empresa:{a.cliente_id}" if a is not None else f"ip:{request.client.host if request.client else '?'}"


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/").removesuffix("/v1")
