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

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from raiz.pedidos import servico as S
from raiz.pedidos.campos import CamposPedido
from raiz.publica import chaves as K
from raiz.publica import conta as CT
from raiz.publica.privacidade import limpar, sem_dado_pessoal
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


def criar(engine_de: Callable[[Request], Any]) -> FastAPI:
    """A aplicação da API pública (montada em /v1 pela aplicação principal)."""
    from slowapi import Limiter
    from slowapi.errors import RateLimitExceeded

    app = FastAPI(title="Raíz: API pública do pedido de lote", version=VERSAO, description=DESCRICAO,
                  openapi_tags=TAGS, docs_url="/docs", redoc_url="/redoc", openapi_url="/openapi.json",
                  servers=[{"url": "/v1", "description": "esta instalação"}])  # fmt: skip
    lim = CT.premissas()["limites"]
    limiter = Limiter(key_func=_cliente, storage_uri=os.environ.get("RAIZ_API_LIMIT_STORAGE_URI", "memory://"))
    LIMITE = f"{lim['por_minuto']}/minute;{lim['por_dia']}/day;{lim['por_mes']}/month"
    app.state.limiter = limiter

    @app.exception_handler(CT.ErroConta)
    async def _conta(request: Request, ex: CT.ErroConta):
        return problema(ex.status, ex.slug, ex.detalhe, ex.corrigir, str(request.url.path), **ex.extra)

    @app.exception_handler(S.ErroPedido)
    async def _pedido(request: Request, ex: S.ErroPedido):
        msg = str(ex)
        st = 404 if "não encontrad" in msg else 422
        return problema(st, "pedido", msg, "confira o id do pedido e o estado dele (GET /v1/pedidos/{id})",
                        str(request.url.path))  # fmt: skip

    @app.exception_handler(HTTPException)
    async def _http(request: Request, ex: HTTPException):
        d = ex.detail if isinstance(ex.detail, dict) else {"mensagem": str(ex.detail)}
        return problema(ex.status_code, d.get("slug", f"http_{ex.status_code}"), d.get("mensagem", ""),
                        d.get("corrigir", "confira o pedido"), str(request.url.path), headers=ex.headers)  # fmt: skip

    @app.exception_handler(RequestValidationError)
    async def _validacao(request: Request, ex: RequestValidationError):
        campos = [".".join(str(x) for x in e.get("loc", []) if x != "body") + f": {e.get('msg')}" for e in ex.errors()]
        return problema(422, "dados_invalidos", "o corpo ou os parâmetros não passaram na validação",
                        "corrija: " + "; ".join(campos[:10]), str(request.url.path), campos=campos[:20])  # fmt: skip

    @app.exception_handler(RateLimitExceeded)
    async def _limite(request: Request, ex: RateLimitExceeded):
        try:
            espera = int(ex.limit.limit.get_expiry())
        except Exception:  # noqa: BLE001
            espera = 60
        return problema(429, "limite", f"passou do limite da empresa ({ex.detail})",
                        f"espere {espera} s e repita; uso em volume é licença de dados", str(request.url.path),
                        headers={"Retry-After": str(espera)})  # fmt: skip

    def acesso(request: Request,
               x_chave_api: Annotated[str | None, Header(description="Chave de API da empresa (raiz_...).")] = None,
               authorization: Annotated[str | None, Header(description="Bearer raiz_... ou a sessão do login.")] = None,
               ) -> K.Acesso:  # fmt: skip
        eng = engine_de(request)
        bruto = (x_chave_api or (authorization or "").removeprefix("Bearer ").strip()).strip()
        a = K.acesso_da_chave(eng, bruto) if bruto.startswith(K.PREFIXO) else None
        if a is None and bruto and not bruto.startswith(K.PREFIXO):
            cid = S.cliente_da_sessao(eng, bruto)
            a = K.Acesso(int(cid), None, "sessao") if cid is not None else None
        if a is None:
            raise HTTPException(401, {"slug": "sem_credencial", "mensagem": "faltou a chave de API da empresa ou ela "
                                      "foi revogada", "corrigir": "mande a chave em X-Chave-API (ou Authorization: "
                                      "Bearer raiz_...); uma pessoa da empresa cria em POST /v1/chaves"})  # fmt: skip
        request.state.acesso = a
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
                str(request.url.path),
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
        return JSONResponse(limpar(sem_dado_pessoal(x)))

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
        return ok(S.base_disponivel(engine_de(request), a.cliente_id, campos))

    @app.post("/pedidos", tags=["Pedido de lote"], summary="Montar o lote em 3 opções (pedir_lote)")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def pedir_lote(campos: Annotated[CamposPedido, Body(openapi_examples=EXEMPLOS_PEDIDO)], request: Request,
                   a: Acesso, _c: Annotated[Any, Depends(cobrar("pedir_lote", liberacao=True))]) -> JSONResponse:  # fmt: skip  # noqa: E501
        """Pede a liberação (sinal pago e contrato de não contornar)."""
        p = S.criar_pedido(engine_de(request), a.cliente_id, campos)
        request.state.pedido_id = p["id"]
        request.state.cods_expostos = [i["cod_imovel"] for o in p.get("opcoes") or [] for i in o.get("itens") or []]
        return ok(p)

    @app.get("/pedidos", tags=["Pedido de lote"], summary="Pedidos da empresa (sem custo)")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def listar(request: Request, a: Acesso) -> JSONResponse:
        CT.exigir(engine_de(request), a.cliente_id)
        return ok(S.pedidos_do_cliente(engine_de(request), a.cliente_id))

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
        return ok(pedido)

    @app.get("/pedidos/{pedido_id}/alertas", tags=["Pedido de lote"])
    @limiter.shared_limit(LIMITE, scope="empresa")
    def alertas_pedido(pedido_id: Pid, request: Request, a: Acesso) -> JSONResponse:
        CT.exigir_liberacao(engine_de(request), a.cliente_id)
        return ok(S.obter_pedido(engine_de(request), pedido_id, a.cliente_id)["alertas"])

    @app.get("/notificacoes", tags=["Conta da empresa"])
    @limiter.shared_limit(LIMITE, scope="empresa")
    def notificacoes(request: Request, a: Pessoa) -> JSONResponse:
        CT.exigir(engine_de(request), a.cliente_id)
        return ok(S.notificacoes(engine_de(request), a.cliente_id))

    @app.get("/pedidos/{pedido_id}/opcoes", tags=["Pedido de lote"], summary="As 3 opções lado a lado (comparar_lotes)")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def comparar(pedido_id: Pid, request: Request, a: Acesso,
                 _c: Annotated[Any, Depends(cobrar("comparar_lotes", liberacao=True))]) -> JSONResponse:  # fmt: skip
        ops = S.obter_pedido(engine_de(request), pedido_id, a.cliente_id)["opcoes"]
        request.state.cods_expostos = [i["cod_imovel"] for o in ops for i in o.get("itens") or []]
        return ok(ops)

    @app.patch("/pedidos/{pedido_id}", tags=["Pedido de lote"])
    @app.post("/pedidos/{pedido_id}/lote", tags=["Pedido de lote"], summary="Tirar ou trocar uma fazenda")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def mudar(pedido_id: Pid, m: Mudanca, request: Request, a: Acesso,
              _c: Annotated[Any, Depends(cobrar("comparar_lotes", liberacao=True))]) -> JSONResponse:  # fmt: skip
        return ok(S.mudar_lote(engine_de(request), pedido_id, a.cliente_id, m.model_dump()))

    @app.post(
        "/pedidos/{pedido_id}/solicitar-interesse",
        tags=["Interesse dos donos"],
        summary="A Raíz busca o interesse dos donos",
    )
    @limiter.shared_limit(LIMITE, scope="empresa")
    def solicitar(pedido_id: Pid, request: Request, a: Acesso,
                  _c: Annotated[Any, Depends(cobrar("solicitar_interesse", liberacao=True))],
                  corpo: Annotated[Solicitar, Body()] = SOLICITAR_PADRAO) -> JSONResponse:  # fmt: skip
        return ok(S.solicitar_interesse(engine_de(request), pedido_id, a.cliente_id, corpo.opcao))

    @app.get("/pedidos/{pedido_id}/andamento", tags=["Interesse dos donos"], summary="Andamento (acompanhar_contato)")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def andamento(
        pedido_id: Pid,
        request: Request,
        a: Acesso,
        _c: Annotated[Any, Depends(cobrar("acompanhar_contato", liberacao=True))],
    ) -> JSONResponse:
        return ok(S.andamento(engine_de(request), pedido_id, a.cliente_id))

    @app.post("/pedidos/{pedido_id}/reservar", tags=["Reserva"], summary="Preparar a reserva (uma pessoa aprova)")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def reservar(pedido_id: Pid, request: Request, a: Acesso,
                 _c: Annotated[Any, Depends(cobrar("preparar_reserva", liberacao=True))]) -> JSONResponse:  # fmt: skip
        por = None if a.via == "sessao" else f"{a.via}:{a.chave_id}"
        return ok(S.reservar(engine_de(request), pedido_id, a.cliente_id, por_agente=por,
                             base_url=_base(request) + "/v1"))  # fmt: skip

    @app.get("/pedidos/{pedido_id}/reserva", tags=["Reserva"], summary="Situação da reserva (sem custo)")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def reserva(pedido_id: Pid, request: Request, a: Acesso) -> JSONResponse:
        CT.exigir_liberacao(engine_de(request), a.cliente_id)
        return ok(S.cobranca_do_pedido(engine_de(request), pedido_id, a.cliente_id))

    @app.get(
        "/reservas/confirmar/{token}",
        tags=["Reserva"],
        summary="Página de aprovação (para uma pessoa)",
        response_class=HTMLResponse,
    )
    def pagina_confirmar(token: str) -> HTMLResponse:
        t = html.escape(token)
        return HTMLResponse(f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Aprovar a reserva
</title></head><body style="font-family:system-ui;max-width:560px;margin:40px auto;padding:0 16px"><h1>Aprovar a
reserva do grupo</h1><p>O agente de IA da sua empresa preparou a reserva de um grupo de fazendas na Raíz. Ao aprovar,
sai o Pix da reserva. Se não foi você quem autorizou, não aprove.</p><form method="post"
action="/v1/reservas/confirmar/{t}"><button type="submit">Aprovar e gerar o Pix</button></form></body></html>""")

    @app.post(
        "/reservas/confirmar/{token}",
        tags=["Reserva"],
        summary="Aprovar (uma pessoa da empresa)",
        response_class=HTMLResponse,
    )
    def confirmar(token: str, request: Request) -> HTMLResponse:
        try:
            c = S.confirmar_reserva(engine_de(request), token)
        except S.ErroPedido as ex:
            return HTMLResponse(f"<p>{html.escape(str(ex))}</p>", status_code=410)
        pixc = (c.get("pix") or {}).get("copia_e_cola") or ""
        return HTMLResponse(f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Reserva aprovada
</title></head><body style="font-family:system-ui;max-width:560px;margin:40px auto;padding:0 16px"><h1>Reserva
aprovada</h1><p>Valor: R$ {c["valor_brl"]:.2f}.</p><p>Pix copia e cola:</p><textarea readonly rows="4"
style="width:100%">{html.escape(pixc)}</textarea></body></html>""")

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
        return ok(x)

    @app.get("/previsoes/precisao", tags=["Produto 4: previsões conferidas"], summary="Acerto das previsões da Raíz")
    @limiter.shared_limit(LIMITE, scope="empresa")
    def precisao(request: Request, a: Acesso,
                 _c: Annotated[Any, Depends(cobrar("precisao_previsoes"))]) -> JSONResponse:  # fmt: skip
        from raiz.aprendizado.registro import placar

        with engine_de(request).connect() as con:
            linhas = [dict(r._mapping) for r in placar(con)]
        return ok([{k: (float(v) if hasattr(v, "as_integer_ratio") else v) for k, v in li.items()} for li in linhas])

    return app


def _cliente(request: Request) -> str:
    a = getattr(request.state, "acesso", None)
    return f"empresa:{a.cliente_id}" if a is not None else f"ip:{request.client.host if request.client else '?'}"


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/").removesuffix("/v1")
