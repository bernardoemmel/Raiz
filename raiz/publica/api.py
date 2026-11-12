"""API pública da Raíz (/v1): o pedido de lote para as empresas clientes e os agentes de IA delas.

Entrar: chave de API da empresa (cabeçalho X-Chave-API ou Authorization: Bearer raiz_...) ou a sessão do login por
e-mail (Authorization: Bearer <token>). Cada chave tem limite de chamadas por minuto e por dia; cada chamada fica
gravada (empresa, ferramenta, pedido, versão do modelo e o modelo do agente, quando ele diz) para o aprendizado.

Regras: nunca devolve nome, CPF, CNPJ ou contato de dono (o contato passa pela Raíz); a reserva pedida por agente
nasce "aguardando confirmação" e só uma pessoa da empresa confirma, pelo link no e-mail cadastrado, e aí sai o Pix.
Documentação: /v1/docs (Swagger), /v1/redoc e /v1/openapi.json; servidor MCP em /mcp (raiz/publica/servidor_mcp.py).
"""

import html
import re
import time
from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Path, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from raiz.pedidos import servico as S
from raiz.pedidos.campos import CamposPedido
from raiz.publica import chaves as K

VERSAO = "1.0.0"
PESSOAL = re.compile(r"(^|_)(nome|cpf|cnpj|telefone|celular|email|e_mail|contato|proprietario|whatsapp|endereco)"
                     r"($|_)", re.I)  # fmt: skip

DESCRICAO = """
API pública da **Raíz**: o cliente (desenvolvedor de restauração, empresa com meta FLAG, frigorífico, fundo ou banco)
pede, por exemplo, **"1 milhão de créditos de carbono líquidos no Pará, no cronograma do ProFloresta+"** e a Raíz
monta o melhor lote no mapa inteiro, em **3 opções** (mais barata, mais segura, mais compacta), com créditos
P10/P50/P90, hectares, fazendas (pequenas agrupadas, nunca descartadas), custo por crédito, TIR, chance de cumprir cada
marco, mistura do caminho da terra e fazendas de reserva.

**Feita para agentes de IA:** as rotas seguem o caminho do pedido (base → lote → opções → interesse dos donos →
andamento) e há um servidor MCP com as mesmas ferramentas em `/mcp`.

**Como entrar:** chave de API da empresa no cabeçalho `X-Chave-API` (ou `Authorization: Bearer raiz_...`), criada por
uma pessoa da empresa em `POST /v1/chaves`, ou a sessão do login por e-mail (`Authorization: Bearer <token>`). Limite
padrão por chave: 30 chamadas por minuto e 2.000 por dia (resposta 429 com `Retry-After`).

**Privacidade:** nunca devolvemos nome, CPF, CNPJ ou contato de dono de fazenda. O contato com os donos passa pela
Raíz.

**Dinheiro:** a reserva do grupo pedida por um agente nasce **aguardando confirmação**; uma pessoa da empresa confirma
pelo link enviado ao e-mail cadastrado e só então sai o Pix. O agente nunca conclui pagamento.

Opcional: diga o modelo do seu agente no cabeçalho `X-Agente-Modelo` (gravado com a chamada, para o aprendizado).
"""

TAGS = [
    {
        "name": "Pedido de lote",
        "description": "Quanto existe na base, montar o lote, as 3 opções e a troca de fazenda.",
    },
    {"name": "Interesse dos donos", "description": "Buscar o interesse dos donos em ondas e acompanhar o andamento."},
    {"name": "Reserva", "description": "Reserva do grupo pronto: o agente pede, uma pessoa da empresa confirma."},
    {"name": "Fazendas", "description": "A explicação de uma fazenda, sem dados pessoais."},
    {"name": "Chaves de API", "description": "Chaves da empresa para os agentes de IA (uma pessoa cria e revoga)."},
]

# --- exemplos (OpenAPI) ---------------------------------------------------------------------------------------------

EXEMPLO_PEDIDO = {
    "meta": {"tipo": "creditos", "valor": 1_000_000},
    "cronograma": "profloresta",
    "onde": {"ufs": ["PA"], "biomas": ["Amazônia"]},
    "dinheiro": {"custo_max_usd_credito": 60, "preco_venda_usd": 55},
    "metodos": ["regeneracao_assistida", "semeadura_direta", "plantio_total"],
    "terra": ["matricula_conferida", "matricula_a_conferir", "concessao"],
    "interesse": "qualquer",
}
EXEMPLOS_PEDIDO = {
    "um_milhao_no_para": {
        "summary": "1 milhão de créditos no Pará (ProFloresta+)",
        "value": EXEMPLO_PEDIDO,
    },
    "flag_frigorifico": {
        "summary": "Meta FLAG de um frigorífico: só fornecedores da cadeia",
        "value": {
            "meta": {"tipo": "flag_t_ano", "valor": 50_000},
            "cronograma": "livre",
            "onde": {
                "ufs": ["PA", "MT"],
                "so_fornecedores_cadeia": True,
                "fornecedores": ["PA-1504950-0E3B6098A40D44F7B85CFB563EB6A45A"],
            },
            "metodos": ["silvipastoril", "agrofloresta"],
        },  # fmt: skip
    },
}
EXEMPLO_BASE = {
    "fazendas": 3120, "hectares": 158_400.5, "pequenas": 2604,
    "creditos": {"p10": 9_850_000, "p50": 14_200_000, "p90": 17_900_000},
    "por_caminho": [{"caminho": "matricula_a_conferir", "fazendas": 410, "creditos_p50": 2_150_000}],
    "alcanca_meta": True, "falta": 0, "afrouxar": [], "na_unidade_da_meta": 14_200_000,
}  # fmt: skip
EXEMPLO_OPCAO = {
    "id": "barata", "creditos": {"p10": 760_000, "p50": 1_140_000, "p90": 1_480_000}, "hectares": 5945.3,
    "fazendas": 28, "pequenas": 24, "tir": {"p10": 1.2, "p50": 6.3, "p90": 9.8},
    "custo_usd_credito": {"p10": 41.2, "p50": 47.9, "p90": 61.0}, "pico_caixa_usd": 7_800_000,
    "marcos": [{"ano": 7, "fracao": 0.12, "chance": 0.62, "multa_esperada_rs": 394_502}],
    "multa_esperada_usd": 1_550_000, "mistura_terra": [{"caminho": "matricula_a_conferir", "fracao": 1.0}],
    "metodos": [{"metodo": "semeadura_direta", "fazendas": 20}], "alcanca_meta": True, "falta": 0,
    "abaixo_equilibrio": {"fazendas": 0, "aviso": None},
    "itens": [{"cod_imovel": "PA-1504950-0E3B6098A40D44F7B85CFB563EB6A45A", "papel": "lote", "hectares": 150.2,
               "creditos": {"p10": 22_000, "p50": 32_500, "p90": 41_000}, "metodo": "semeadura_direta",
               "caminho": "matricula_a_conferir", "interesse": "sem_contato", "pequena": False}],
}  # fmt: skip
EXEMPLO_PEDIDO_CRIADO = {
    "id": "6f1c2a9e-0b7d-4c55-9a51-2f4e0e2c1b77", "status": "lote_montado", "campos": EXEMPLO_PEDIDO,
    "base": EXEMPLO_BASE, "opcoes": [EXEMPLO_OPCAO], "opcao_escolhida": None, "reservado_ate": None, "alertas": [],
    "versao_modelo": "pedidos-2026a+1994a821+otimizador-2026a+restauracao-2026c+2430e38c",
}  # fmt: skip
EXEMPLO_ANDAMENTO = {
    "pedido": "6f1c2a9e-0b7d-4c55-9a51-2f4e0e2c1b77", "status": "buscando_interesse",
    "meta": 1_000_000, "com_interesse": 0.42, "com_aceite": 0.10, "com_contrato": 0.0,
    "ondas": [{"onda": 1, "contatados": 64, "responderam": 30}], "recusas": [{"motivo": "prefere o gado", "n": 6}],
}  # fmt: skip
EXEMPLO_RESERVA = {
    "pedido": "6f1c2a9e-0b7d-4c55-9a51-2f4e0e2c1b77", "valor_brl": 35_672.0, "hectares": 5945.3, "prazo_dias": 60,
    "estado": "aguardando_confirmacao", "aguardando_confirmacao": True, "pix": None, "pago": False,
    "confirmacao": "Uma pessoa da empresa precisa confirmar a reserva pelo link enviado ao e-mail cadastrado; só então "
                   "sai o Pix. O agente de IA não confirma nem paga.",
}  # fmt: skip
EXEMPLO_FAZENDA = {
    "cod_imovel": "PA-1504950-0E3B6098A40D44F7B85CFB563EB6A45A", "municipio": "Nova Esperança do Piriá", "uf": "PA",
    "bioma": "Amazônia", "hectares": 600.4, "area_para_restaurar_ha": 150.2, "metodo": "semeadura_direta",
    "caminho_terra": "matricula_a_conferir", "risco_terra": "medio",
    "creditos_ate_ano_25": {"p10": 22_000, "p50": 32_500, "p90": 41_000}, "custo_usd_credito": 47.1,
    "preco_equilibrio_usd": 74.2, "tir_com_fundo_clima_pct": {"p10": 1.9, "p50": 7.6, "p90": 11.0},
    "reserva_nao_permanencia_pct": 12.0, "rebanho_cabecas": 180, "explicacao": "Semeadura direta em 150 ha de pasto...",
}  # fmt: skip


def _exemplo(exemplo: Any, descricao: str = "Tudo certo") -> dict:
    return {200: {"description": descricao, "content": {"application/json": {"example": exemplo}}}}


ERROS = {
    401: {"description": "Sem chave ou sessão válida", "content": {"application/json": {"example": {
        "mensagem": "mande a chave da empresa em X-Chave-API ou a sessão em Authorization: Bearer"}}}},
    429: {"description": "Passou do limite da chave", "content": {"application/json": {"example": {
        "mensagem": "limite de 30 chamadas por minuto da chave raiz_AbCdEf12: tente de novo em 60 s"}}}},
}  # fmt: skip


# --- corpo das rotas ------------------------------------------------------------------------------------------------


class Solicitar(BaseModel):
    opcao: Literal["barata", "segura", "compacta"] = Field(
        "segura", description="Qual das 3 opções vai para a busca de interesse dos donos."
    )


class Mudanca(BaseModel):
    opcao: Literal["barata", "segura", "compacta"] = Field(description="A opção a mudar.")
    acao: Literal["tirar", "trocar"] = Field(description="Tirar a fazenda do lote ou trocá-la por outra.")
    cod_imovel: str = Field(description="Código do CAR da fazenda.")
    por: str | None = Field(None, description="Na troca: o código do CAR da fazenda que entra.")


class NovaChave(BaseModel):
    rotulo: str | None = Field(
        None, description="Para a empresa saber qual agente usa a chave.", examples=["agente de compras de carbono"]
    )
    limite_minuto: int = Field(30, ge=1, le=600, description="Chamadas por minuto.")
    limite_dia: int = Field(2000, ge=1, le=100_000, description="Chamadas por dia.")


SOLICITAR_PADRAO = Solicitar()


def sem_dado_pessoal(x: Any) -> Any:
    """Tira de qualquer resposta as chaves com cara de dado pessoal (nome, CPF, CNPJ, contato), por garantia."""
    if isinstance(x, dict):
        return {k: sem_dado_pessoal(v) for k, v in x.items() if not PESSOAL.search(str(k))}
    if isinstance(x, list):
        return [sem_dado_pessoal(v) for v in x]
    return x


def _erro(ex: S.ErroPedido) -> HTTPException:
    msg = str(ex)
    return HTTPException(404 if "não encontrad" in msg else 422, {"mensagem": msg})


def criar(engine_de: Callable[[Request], Any]) -> FastAPI:
    """A aplicação da API pública (montada em /v1 pela aplicação principal)."""
    app = FastAPI(title="Raíz: API pública do pedido de lote", version=VERSAO, description=DESCRICAO,
                  openapi_tags=TAGS, docs_url="/docs", redoc_url="/redoc", openapi_url="/openapi.json",
                  contact={"name": "Raíz", "url": "https://github.com/bernardoemmel/Raiz"},
                  servers=[{"url": "/v1", "description": "esta instalação"}])  # fmt: skip

    def acesso(request: Request, x_chave_api: Annotated[str | None, Header(
                   description="Chave de API da empresa (raiz_...).")] = None,
               authorization: Annotated[str | None, Header(
                   description="Bearer raiz_... (chave) ou Bearer <sessão do login por e-mail>.")] = None,
               ) -> K.Acesso:  # fmt: skip
        eng = engine_de(request)
        bruto = (x_chave_api or (authorization or "").removeprefix("Bearer ").strip()).strip()
        a = K.acesso_da_chave(eng, bruto) if bruto.startswith(K.PREFIXO) else None
        if a is None and bruto and not bruto.startswith(K.PREFIXO):
            cid = S.cliente_da_sessao(eng, bruto)
            a = K.Acesso(int(cid), None, "sessao") if cid is not None else None
        if a is None:
            raise HTTPException(401, {"mensagem": "mande a chave da empresa em X-Chave-API ou a sessão em "
                                                  "Authorization: Bearer"})  # fmt: skip
        request.state.acesso = a
        passou, espera = K.excedeu(eng, a)
        if passou:
            lim = f"{a.limite_minuto} chamadas por minuto" if espera == 60 else f"{a.limite_dia} chamadas por dia"
            raise HTTPException(429, {"mensagem": f"limite de {lim} da chave: tente de novo em {espera} s"},
                                headers={"Retry-After": str(espera)})  # fmt: skip
        return a

    def pessoa(a: Annotated[K.Acesso, Depends(acesso)]) -> K.Acesso:
        if a.via != "sessao":
            raise HTTPException(403, {"mensagem": "só uma pessoa da empresa (login por e-mail) mexe nas chaves"})
        return a

    @app.middleware("http")
    async def registrar(request: Request, call_next):
        t0 = time.monotonic()
        resp = await call_next(request)
        a = getattr(request.state, "acesso", None)
        rota = request.scope.get("route")
        if a is not None:
            from raiz.pedidos.premissas import versao_modelo

            pp = request.scope.get("path_params") or {}
            via = "mcp" if request.headers.get("x-raiz-via") == "mcp" else a.via
            try:
                K.registrar(engine_de(request), cliente_id=a.cliente_id, chave_id=a.chave_id, via=via,
                            ferramenta=request.headers.get("x-raiz-ferramenta") or getattr(rota, "name", "") or "?",
                            metodo=request.method, rota=getattr(rota, "path", request.url.path),
                            pedido_id=pp.get("pedido_id") or getattr(request.state, "pedido_id", None),
                            cod_imovel=pp.get("cod_imovel"), status=resp.status_code,
                            ms=int(1000 * (time.monotonic() - t0)), versao_modelo=versao_modelo(),
                            agente_modelo=request.headers.get("x-agente-modelo"))  # fmt: skip
            except Exception:  # noqa: BLE001 - o registro nunca derruba a resposta ao cliente
                pass
        return resp

    def ok(x: Any) -> JSONResponse:
        return JSONResponse(sem_dado_pessoal(x))

    Acesso = Annotated[K.Acesso, Depends(acesso)]
    Pid = Annotated[str, Path(description="Id do pedido (uuid).", examples=["6f1c2a9e-0b7d-4c55-9a51-2f4e0e2c1b77"])]

    @app.get(
        "/",
        tags=["Pedido de lote"],
        summary="Sobre a API",
        responses=_exemplo({"nome": "Raíz", "versao": VERSAO, "documentacao": "/v1/docs", "mcp": "/mcp"}),
    )
    def sobre() -> dict:
        """Onde estão a documentação, o servidor MCP e o caminho do pedido."""
        return {"nome": "Raíz", "versao": VERSAO, "documentacao": "/v1/docs", "openapi": "/v1/openapi.json",
                "mcp": "/mcp", "caminho": ["POST /v1/base", "POST /v1/pedidos", "GET /v1/pedidos/{id}/opcoes",
                                           "POST /v1/pedidos/{id}/solicitar-interesse",
                                           "GET /v1/pedidos/{id}/andamento"]}  # fmt: skip

    @app.post(
        "/base", tags=["Pedido de lote"], summary="Quanto existe na base", responses={**_exemplo(EXEMPLO_BASE), **ERROS}
    )
    def base(campos: Annotated[CamposPedido, Body(openapi_examples=EXEMPLOS_PEDIDO)], request: Request,
             a: Acesso) -> JSONResponse:  # fmt: skip
        """Filtra o mapa inteiro pelo pedido e responde, sem salvar nada: fazendas, hectares e créditos líquidos
        P10/P50/P90 que atendem, por caminho da terra e por interesse do dono. Se não alcança a meta, diz quanto
        falta e o que afrouxar (do que mais soma ao que menos)."""
        try:
            return ok(S.base_disponivel(engine_de(request), a.cliente_id, campos))
        except S.ErroPedido as ex:
            raise _erro(ex) from ex

    @app.post(
        "/pedidos",
        tags=["Pedido de lote"],
        summary="Montar o lote (3 opções)",
        responses={**_exemplo(EXEMPLO_PEDIDO_CRIADO, "Pedido criado com as 3 opções"), **ERROS},
    )
    def montar(campos: Annotated[CamposPedido, Body(openapi_examples=EXEMPLOS_PEDIDO)], request: Request,
               a: Acesso) -> JSONResponse:  # fmt: skip
        """Cria o pedido e monta o melhor lote em 3 opções do mesmo otimizador (HiGHS): mais barata, mais segura e
        mais compacta, cada uma com 10 a 20% de fazendas de reserva. Pequenas entram agrupadas, nunca descartadas.
        A versão do modelo e das premissas fica gravada no pedido."""
        try:
            p = S.criar_pedido(engine_de(request), a.cliente_id, campos)
            request.state.pedido_id = p["id"]  # para o registro da chamada
            return ok(p)
        except S.ErroPedido as ex:
            raise _erro(ex) from ex

    @app.get("/pedidos", tags=["Pedido de lote"], summary="Pedidos da empresa",
             responses={**_exemplo([{"id": EXEMPLO_PEDIDO_CRIADO["id"], "titulo": "1 milhão de créditos em PA",
                                     "status": "lote_montado"}]), **ERROS})  # fmt: skip
    def listar(request: Request, a: Acesso) -> JSONResponse:
        """Os pedidos da empresa, do mais novo ao mais antigo."""
        return ok(S.pedidos_do_cliente(engine_de(request), a.cliente_id))

    @app.get(
        "/pedidos/{pedido_id}",
        tags=["Pedido de lote"],
        summary="Um pedido",
        responses={**_exemplo(EXEMPLO_PEDIDO_CRIADO), **ERROS},
    )
    def obter(pedido_id: Pid, request: Request, a: Acesso) -> JSONResponse:
        """O pedido com a base, as 3 opções, o estado, os alertas e a versão do modelo."""
        try:
            return ok(S.obter_pedido(engine_de(request), pedido_id, a.cliente_id))
        except S.ErroPedido as ex:
            raise _erro(ex) from ex

    @app.get(
        "/pedidos/{pedido_id}/opcoes",
        tags=["Pedido de lote"],
        summary="Ver as 3 opções",
        responses={**_exemplo([EXEMPLO_OPCAO]), **ERROS},
    )
    def opcoes(pedido_id: Pid, request: Request, a: Acesso) -> JSONResponse:
        """Só as 3 opções do pedido (mais barata, mais segura, mais compacta), com as fazendas de cada uma."""
        try:
            return ok(S.obter_pedido(engine_de(request), pedido_id, a.cliente_id)["opcoes"])
        except S.ErroPedido as ex:
            raise _erro(ex) from ex

    @app.post(
        "/pedidos/{pedido_id}/lote",
        tags=["Pedido de lote"],
        summary="Tirar ou trocar uma fazenda",
        responses={**_exemplo(EXEMPLO_PEDIDO_CRIADO), **ERROS},
    )
    def mudar(pedido_id: Pid, m: Annotated[Mudanca, Body(openapi_examples={"tirar": {"summary": "Tirar uma fazenda",
              "value": {"opcao": "barata", "acao": "tirar", "cod_imovel": EXEMPLO_OPCAO["itens"][0]["cod_imovel"]}}})],
              request: Request, a: Acesso) -> JSONResponse:  # fmt: skip
        """Tira ou troca uma fazenda numa opção e refaz os números (a reserva entra no lugar)."""
        try:
            return ok(S.mudar_lote(engine_de(request), pedido_id, a.cliente_id, m.model_dump()))
        except S.ErroPedido as ex:
            raise _erro(ex) from ex

    @app.post("/pedidos/{pedido_id}/solicitar-interesse", tags=["Interesse dos donos"],
              summary="Solicitar o interesse dos donos",
              responses={**_exemplo({"pedido": EXEMPLO_PEDIDO_CRIADO["id"], "status": "buscando_interesse",
                                     "onda": 1, "contatados": 64}), **ERROS})  # fmt: skip
    def solicitar(pedido_id: Pid, request: Request, a: Acesso,
                  corpo: Annotated[Solicitar, Body(openapi_examples={"segura": {"summary": "Opção mais segura",
                                                                                 "value": {"opcao": "segura"}}})]
                  = SOLICITAR_PADRAO) -> JSONResponse:  # fmt: skip
        """A Raíz contata os donos da opção em ondas (WhatsApp, carta ou parceiro local, com o termo de LGPD), troca
        quem recusa pela reserva e avisa quando o grupo com interesse fecha a meta. O cliente nunca contata o dono."""
        try:
            return ok(S.solicitar_interesse(engine_de(request), pedido_id, a.cliente_id, corpo.opcao))
        except S.ErroPedido as ex:
            raise _erro(ex) from ex

    @app.get(
        "/pedidos/{pedido_id}/andamento",
        tags=["Interesse dos donos"],
        summary="Andamento do pedido",
        responses={**_exemplo(EXEMPLO_ANDAMENTO), **ERROS},
    )
    def andamento(pedido_id: Pid, request: Request, a: Acesso) -> JSONResponse:
        """Quanto da meta já tem dono interessado, com aceite e com contrato; as ondas, as recusas e os motivos
        (sem nome nem CPF)."""
        try:
            return ok(S.andamento(engine_de(request), pedido_id, a.cliente_id))
        except S.ErroPedido as ex:
            raise _erro(ex) from ex

    @app.post(
        "/pedidos/{pedido_id}/reservar",
        tags=["Reserva"],
        summary="Pedir a reserva do grupo pronto",
        responses={**_exemplo(EXEMPLO_RESERVA, "Reserva aguardando a confirmação de uma pessoa"), **ERROS},
    )
    def reservar(pedido_id: Pid, request: Request, a: Acesso) -> JSONResponse:
        """Pede a reserva do grupo pronto. Com a chave de API (agente), a reserva nasce **aguardando confirmação**:
        o link de uso único vai para o e-mail cadastrado da empresa e só uma pessoa confirma; aí sai o Pix. O agente
        não recebe o link nem conclui o pagamento. Na sessão de uma pessoa, sai o Pix na hora."""
        por = None if a.via == "sessao" else f"chave:{a.chave_id}"
        if request.headers.get("x-raiz-via") == "mcp" and por is None:
            por = "mcp"
        base_url = str(request.base_url).rstrip("/")
        try:
            return ok(S.reservar(engine_de(request), pedido_id, a.cliente_id, por_agente=por,
                                 base_url=f"{base_url}/v1"))  # fmt: skip
        except S.ErroPedido as ex:
            raise _erro(ex) from ex

    @app.get(
        "/pedidos/{pedido_id}/reserva",
        tags=["Reserva"],
        summary="Situação da reserva",
        responses={**_exemplo(EXEMPLO_RESERVA), **ERROS},
    )
    def reserva(pedido_id: Pid, request: Request, a: Acesso) -> JSONResponse:
        """Valor, prazo, estado (aguardando confirmação, aguardando pagamento, ativa) e o Pix quando já existe."""
        try:
            return ok(S.cobranca_do_pedido(engine_de(request), pedido_id, a.cliente_id))
        except S.ErroPedido as ex:
            raise _erro(ex) from ex

    @app.get(
        "/reservas/confirmar/{token}",
        tags=["Reserva"],
        summary="Página de confirmação (para uma pessoa)",
        response_class=HTMLResponse,
        include_in_schema=True,
    )
    def pagina_confirmar(token: str) -> HTMLResponse:
        """A página que a pessoa da empresa abre pelo link do e-mail: mostra o pedido e um botão para confirmar."""
        t = html.escape(token)
        return HTMLResponse(f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Confirmar a reserva</title></head>
<body style="font-family:system-ui;max-width:560px;margin:40px auto;padding:0 16px">
<h1>Confirmar a reserva do grupo</h1><p>O agente de IA da sua empresa pediu a reserva de um grupo de fazendas na Raíz.
Ao confirmar, sai o Pix da reserva. Se não foi você quem autorizou, não confirme.</p>
<form method="post" action="/v1/reservas/confirmar/{t}"><button type="submit" style="font-size:18px;padding:10px 18px">
Confirmar e gerar o Pix</button></form></body></html>""")

    @app.post(
        "/reservas/confirmar/{token}",
        tags=["Reserva"],
        summary="Confirmar (uma pessoa da empresa)",
        response_class=HTMLResponse,
    )
    def confirmar(token: str, request: Request) -> HTMLResponse:
        """Confirma a reserva pedida pelo agente (link de uso único, 48 horas) e gera o Pix."""
        try:
            c = S.confirmar_reserva(engine_de(request), token)
        except S.ErroPedido as ex:
            return HTMLResponse(f"<p>{html.escape(str(ex))}</p>", status_code=410)
        pixc = (c.get("pix") or {}).get("copia_e_cola") or ""
        return HTMLResponse(
            f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Reserva
confirmada</title></head><body style="font-family:system-ui;max-width:560px;margin:40px auto;padding:0 16px">
<h1>Reserva confirmada</h1><p>Valor: R$ {c["valor_brl"]:,.2f}. Prazo: {c["prazo_dias"]} dias depois do pagamento.</p>
<p>Pix copia e cola:</p><textarea readonly rows="4" style="width:100%">{html.escape(pixc)}</textarea>
</body></html>""".replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
        )

    @app.get(
        "/fazendas/{cod_imovel}",
        tags=["Fazendas"],
        summary="Explicar uma fazenda",
        responses={**_exemplo(EXEMPLO_FAZENDA), **ERROS},
    )
    def fazenda(cod_imovel: Annotated[str, Path(description="Código do CAR (com ou sem pontos e traços).",
                                                 examples=[EXEMPLO_FAZENDA["cod_imovel"]])],
                request: Request, a: Acesso) -> JSONResponse:  # fmt: skip
        """O que a Raíz sabe da fazenda, sem dado pessoal: tamanho, área para restaurar, método, caminho da terra e
        risco, créditos P10/P50/P90, custo, TIR, reserva, rebanho e o porquê, em texto curto."""
        from raiz.publica.fazenda import explicar

        x = explicar(engine_de(request), cod_imovel)
        if x is None:
            raise HTTPException(404, {"mensagem": "fazenda não encontrada na base da Raíz"})
        return ok(x)

    @app.post("/chaves", tags=["Chaves de API"], summary="Criar uma chave da empresa",
              responses=_exemplo({"chave": "raiz_AbCdEf12...", "prefixo": "raiz_AbCdEf12", "limite_minuto": 30,
                                  "limite_dia": 2000}, "A chave aparece só agora: guarde"))  # fmt: skip
    def nova_chave(corpo: NovaChave, request: Request, a: Annotated[K.Acesso, Depends(pessoa)]) -> dict:
        """Uma pessoa da empresa (login por e-mail) cria a chave do agente de IA. A chave aparece só nesta resposta."""
        return K.criar(engine_de(request), a.cliente_id, corpo.rotulo, corpo.limite_minuto, corpo.limite_dia)

    @app.get("/chaves", tags=["Chaves de API"], summary="Chaves da empresa")
    def listar_chaves(request: Request, a: Annotated[K.Acesso, Depends(pessoa)]) -> list[dict]:
        """As chaves (só o prefixo), quando foram criadas, usadas e revogadas."""
        return K.listar(engine_de(request), a.cliente_id)

    @app.delete("/chaves/{prefixo}", tags=["Chaves de API"], summary="Revogar uma chave")
    def revogar(prefixo: str, request: Request, a: Annotated[K.Acesso, Depends(pessoa)]) -> dict:
        if not K.revogar(engine_de(request), a.cliente_id, prefixo):
            raise HTTPException(404, {"mensagem": "chave não encontrada ou já revogada"})
        return {"revogada": prefixo}

    @app.get("/chamadas", tags=["Chaves de API"], summary="O que os agentes da empresa fizeram")
    def chamadas(request: Request, a: Acesso, pedido_id: str | None = None) -> list[dict]:
        """Cada chamada da empresa (ferramenta, pedido, quando, versão do modelo), para conferir o agente."""
        return K.chamadas(engine_de(request), a.cliente_id, pedido_id)

    def openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema
        from fastapi.openapi.utils import get_openapi

        s = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes,
                        tags=TAGS, servers=app.servers, contact=app.contact)  # fmt: skip
        s.setdefault("components", {})["securitySchemes"] = {
            "chave": {"type": "apiKey", "in": "header", "name": "X-Chave-API",
                      "description": "Chave de API da empresa (raiz_...)."},
            "sessao": {"type": "http", "scheme": "bearer",
                       "description": "Chave (raiz_...) ou sessão do login por e-mail."},
        }  # fmt: skip
        s["security"] = [{"chave": []}, {"sessao": []}]
        app.openapi_schema = s
        return s

    app.openapi = openapi
    return app
