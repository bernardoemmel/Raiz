"""Servidor MCP da Raíz, em cima da mesma API pública (/v1), com o SDK oficial do Model Context Protocol em Python
(pacote `mcp`, licença MIT; NOTICE.md). Ferramentas: buscar_base, montar_lote, ver_opcoes, solicitar_interesse,
andamento_do_pedido, explicar_fazenda e pedir_reserva (só pede: uma pessoa da empresa confirma pelo link no e-mail).

Duas formas de ligar (docs/agentes-ia.md):
- remoto, por HTTP (streamable HTTP) em /mcp na própria API: a chave da empresa vai no cabeçalho Authorization ou
  X-Chave-API de cada chamada (Claude, ChatGPT e outros clientes de MCP remoto);
- local, por stdio (`raiz mcp`): a chave vem de RAIZ_CHAVE_API e a API de RAIZ_API_URL (Claude Desktop, Claude Code).

Cada chamada sai para a API com X-Raiz-Via: mcp e X-Raiz-Ferramenta: <ferramenta> e fica gravada (empresa, ferramenta,
pedido, versão do modelo e o modelo do agente) no registro de chamadas, para o aprendizado. Nada aqui devolve nome,
CPF, CNPJ ou contato de dono.
"""

from __future__ import annotations

import os
from typing import Any, Literal

import httpx
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

INSTRUCOES = """Você está ligado à Raíz, que acha no mapa do Brasil as fazendas para restaurar com crédito de carbono e
monta o melhor lote para um pedido (por exemplo, 1 milhão de créditos líquidos no Pará, no cronograma do ProFloresta+).
Caminho: buscar_base (quanto existe), montar_lote (cria o pedido com 3 opções: mais barata, mais segura, mais compacta),
ver_opcoes, explicar_fazenda (uma fazenda, sem dado pessoal), solicitar_interesse (a Raíz contata os donos em ondas;
nunca o cliente) e andamento_do_pedido. pedir_reserva só pede: uma pessoa da empresa confirma pelo link no e-mail e aí
sai o Pix; você não confirma nem paga. Créditos sempre em P10/P50/P90 (o P50 é o caminho do meio). Pequenas fazendas
entram agrupadas, nunca descartadas. Nunca há nome, CPF, CNPJ ou contato de dono nas respostas."""

Metodo = Literal["regeneracao_assistida", "semeadura_direta", "plantio_total", "agrofloresta", "silvipastoril"]
Terra = Literal["matricula_conferida", "matricula_a_conferir", "concessao", "assentamento", "posse_em_titulacao"]
Opcao = Literal["barata", "segura", "compacta"]


class ErroRaiz(ToolError):
    """Erro da API que o agente precisa ler (sem chave, limite da chave, pedido não encontrado...)."""


class ApiRaiz:
    """Cliente da API pública. `transporte`: para falar com a API no mesmo processo (httpx.ASGITransport)."""

    def __init__(self, url: str | None = None, chave: str | None = None, transporte: httpx.AsyncBaseTransport | None
                 = None, agente_modelo: str | None = None):  # fmt: skip
        self.url = (url or os.environ.get("RAIZ_API_URL") or "http://127.0.0.1:8000").rstrip("/")
        self.chave = chave if chave is not None else os.environ.get("RAIZ_CHAVE_API")
        self.transporte = transporte
        self.agente_modelo = agente_modelo or os.environ.get("RAIZ_AGENTE_MODELO")

    async def chamar(self, metodo: str, rota: str, ferramenta: str, ctx: Context | None = None,
                     corpo: dict | None = None) -> Any:  # fmt: skip
        h = {"X-Raiz-Via": "mcp", "X-Raiz-Ferramenta": ferramenta}
        recebidos = {}
        if ctx is not None:
            try:
                recebidos = {k.lower(): v for k, v in (ctx.headers or {}).items()}
            except (ValueError, AttributeError):
                recebidos = {}
        chave = recebidos.get("x-chave-api") or recebidos.get("authorization", "").removeprefix("Bearer ").strip()
        chave = chave or self.chave
        if not chave:
            raise ErroRaiz("falta a chave de API da empresa (cabeçalho X-Chave-API ou RAIZ_CHAVE_API)")
        h["X-Chave-API"] = chave
        modelo = recebidos.get("x-agente-modelo") or self.agente_modelo or _cliente_mcp(ctx)
        if modelo:
            h["X-Agente-Modelo"] = modelo
        async with httpx.AsyncClient(base_url=self.url, transport=self.transporte, timeout=120) as cli:
            r = await cli.request(metodo, f"/v1{rota}", json=corpo, headers=h)
        if r.status_code >= 400:
            try:
                msg = r.json().get("detail", {}).get("mensagem") or r.text
            except (ValueError, AttributeError):
                msg = r.text
            raise ErroRaiz(f"{r.status_code}: {msg}")
        return r.json()


def _cliente_mcp(ctx: Context | None) -> str | None:
    """Nome e versão do cliente de MCP (ex.: Claude, ChatGPT), quando ele se apresenta."""
    try:
        info = ctx.session.client_params.client_info  # type: ignore[union-attr]
        return f"{info.name} {info.version}".strip()
    except AttributeError:
        return None


def _campos(meta_valor: float, meta_tipo: str, ufs: list[str] | None, municipios: list[str] | None,
            biomas: list[str] | None, cronograma: str, custo_max_usd_credito: float | None, tir_min_pct: float | None,
            preco_venda_usd: float, metodos: list[str] | None, terra: list[str] | None, interesse: str,
            distancia_max_km: float | None, max_donos: int | None) -> dict:  # fmt: skip
    c: dict[str, Any] = {
        "meta": {"tipo": meta_tipo, "valor": meta_valor},
        "cronograma": cronograma,
        "onde": {"ufs": ufs or [], "municipios": municipios or [], "biomas": biomas or ["Amazônia"]},
        "dinheiro": {
            "custo_max_usd_credito": custo_max_usd_credito,
            "tir_min": tir_min_pct,
            "preco_venda_usd": preco_venda_usd,
        },  # fmt: skip
        "interesse": interesse,
        "forma": {"distancia_max_km": distancia_max_km, "max_donos": max_donos},
    }
    if metodos:
        c["metodos"] = metodos
    if terra:
        c["terra"] = terra
    return c


def _resumo_opcao(o: dict) -> dict[str, Any]:
    """A opção sem a lista inteira de fazendas (o agente pede a fazenda que quiser em explicar_fazenda)."""
    itens = o.get("itens") or []
    return {**{k: v for k, v in o.items() if k != "itens"},
            "fazendas_no_lote": [i["cod_imovel"] for i in itens if i.get("papel") == "lote"],
            "fazendas_de_reserva": [i["cod_imovel"] for i in itens if i.get("papel") == "reserva"]}  # fmt: skip


def criar_servidor(api: ApiRaiz | None = None) -> MCPServer:
    """O servidor MCP com as ferramentas do pedido de lote, todas chamando a API pública."""
    api = api or ApiRaiz()
    mcp = MCPServer(name="raiz", title="Raíz: pedido de lote de crédito de carbono", instructions=INSTRUCOES,
                    website_url="https://github.com/bernardoemmel/Raiz", version="1.0.0")  # fmt: skip

    @mcp.tool()
    async def buscar_base(
        ctx: Context,
        meta_valor: float = 1_000_000,
        meta_tipo: Literal["creditos", "hectares", "flag_t_ano"] = "creditos",
        ufs: list[str] | None = None,
        municipios: list[str] | None = None,
        biomas: list[str] | None = None,
        cronograma: Literal["profloresta", "livre"] = "profloresta",
        custo_max_usd_credito: float | None = None,
        tir_min_pct: float | None = None,
        preco_venda_usd: float = 55,
        metodos: list[Metodo] | None = None,
        terra: list[Terra] | None = None,
        interesse: Literal["qualquer", "interessados", "com_aceite"] = "qualquer",
        distancia_max_km: float | None = None,
        max_donos: int | None = None,
    ) -> dict[str, Any]:
        """Quanto existe na base da Raíz para um pedido, sem salvar nada: fazendas, hectares e créditos líquidos
        P10/P50/P90, por caminho da terra e por interesse do dono; se não alcança a meta, quanto falta e o que
        afrouxar. Ex.: meta_valor=1000000 créditos, ufs=["PA"], cronograma="profloresta"."""
        c = _campos(meta_valor, meta_tipo, ufs, municipios, biomas, cronograma, custo_max_usd_credito, tir_min_pct,
                    preco_venda_usd, metodos, terra, interesse, distancia_max_km, max_donos)  # fmt: skip
        return await api.chamar("POST", "/base", "buscar_base", ctx, c)

    @mcp.tool()
    async def montar_lote(
        ctx: Context,
        meta_valor: float = 1_000_000,
        meta_tipo: Literal["creditos", "hectares", "flag_t_ano"] = "creditos",
        ufs: list[str] | None = None,
        municipios: list[str] | None = None,
        biomas: list[str] | None = None,
        cronograma: Literal["profloresta", "livre"] = "profloresta",
        custo_max_usd_credito: float | None = None,
        tir_min_pct: float | None = None,
        preco_venda_usd: float = 55,
        metodos: list[Metodo] | None = None,
        terra: list[Terra] | None = None,
        interesse: Literal["qualquer", "interessados", "com_aceite"] = "qualquer",
        distancia_max_km: float | None = None,
        max_donos: int | None = None,
    ) -> dict[str, Any]:
        """Cria o pedido e monta o melhor lote em 3 opções (mais barata, mais segura, mais compacta), cada uma com
        créditos P10/P50/P90, hectares, fazendas, custo por crédito, TIR, chance de cada marco e fazendas de reserva.
        Devolve o id do pedido (para ver_opcoes, solicitar_interesse e andamento_do_pedido)."""
        c = _campos(meta_valor, meta_tipo, ufs, municipios, biomas, cronograma, custo_max_usd_credito, tir_min_pct,
                    preco_venda_usd, metodos, terra, interesse, distancia_max_km, max_donos)  # fmt: skip
        p = await api.chamar("POST", "/pedidos", "montar_lote", ctx, c)
        return {"pedido_id": p["id"], "status": p["status"], "base": p.get("base"),
                "opcoes": [_resumo_opcao(o) for o in p.get("opcoes") or []],
                "versao_modelo": p.get("versao_modelo")}  # fmt: skip

    @mcp.tool()
    async def ver_opcoes(ctx: Context, pedido_id: str, com_fazendas: bool = False) -> dict[str, Any]:
        """As 3 opções do pedido. Com com_fazendas=true, cada fazenda do lote e da reserva com hectares, créditos,
        método e caminho da terra (sem dado pessoal)."""
        ops = await api.chamar("GET", f"/pedidos/{pedido_id}/opcoes", "ver_opcoes", ctx)
        return {"pedido_id": pedido_id, "opcoes": ops if com_fazendas else [_resumo_opcao(o) for o in ops]}

    @mcp.tool()
    async def solicitar_interesse(ctx: Context, pedido_id: str, opcao: Opcao = "segura") -> dict[str, Any]:
        """Pede à Raíz que busque o interesse dos donos da opção escolhida, em ondas (WhatsApp, carta ou parceiro
        local, com o termo de LGPD). Quem recusa sai e a reserva entra. O cliente nunca contata o dono."""
        return await api.chamar("POST", f"/pedidos/{pedido_id}/solicitar-interesse", "solicitar_interesse", ctx,
                                {"opcao": opcao})  # fmt: skip

    @mcp.tool()
    async def andamento_do_pedido(ctx: Context, pedido_id: str) -> dict[str, Any]:
        """Quanto da meta já tem dono interessado, com aceite e com contrato; as ondas, as recusas e os motivos."""
        return await api.chamar("GET", f"/pedidos/{pedido_id}/andamento", "andamento_do_pedido", ctx)

    @mcp.tool()
    async def explicar_fazenda(ctx: Context, cod_imovel: str) -> dict[str, Any]:
        """O que a Raíz sabe de uma fazenda (código do CAR), sem dado pessoal: tamanho, área para restaurar, método,
        caminho da terra e risco, créditos P10/P50/P90, custo, TIR, reserva, rebanho e uma explicação curta."""
        return await api.chamar("GET", f"/fazendas/{cod_imovel}", "explicar_fazenda", ctx)

    @mcp.tool()
    async def pedir_reserva(ctx: Context, pedido_id: str) -> dict[str, Any]:
        """Pede a reserva do grupo pronto. Fica "aguardando confirmação": uma pessoa da empresa confirma pelo link
        enviado ao e-mail cadastrado e só então sai o Pix. Você (o agente) não confirma nem paga."""
        return await api.chamar("POST", f"/pedidos/{pedido_id}/reservar", "pedir_reserva", ctx)

    return mcp


class ChaveNaUrl:
    """Conectores que não mandam cabeçalho (ChatGPT, conector do Claude.ai): a chave pode vir em /mcp/?chave=raiz_...
    e vira o cabeçalho X-Chave-API. Use uma chave só para o conector, com limite baixo, e revogue quando quiser."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and b"chave=" in (scope.get("query_string") or b""):
            from urllib.parse import parse_qs

            q = parse_qs(scope["query_string"].decode())
            chave = (q.get("chave") or [""])[0]
            if chave.startswith("raiz_"):
                hs = [(k, v) for k, v in scope.get("headers", []) if k.lower() != b"x-chave-api"]
                scope = {**scope, "headers": [*hs, (b"x-chave-api", chave.encode())]}
        await self.app(scope, receive, send)


def app_http(api: ApiRaiz, hosts: str | None = None) -> Any:
    """O servidor MCP por HTTP (streamable HTTP, sem estado), para montar em /mcp na API. `hosts` (RAIZ_MCP_HOSTS):
    os hosts aceitos; sem eles, qualquer um (toda chamada exige a chave da empresa)."""
    from mcp.server.transport_security import TransportSecuritySettings

    lista = [h.strip() for h in (hosts or "").split(",") if h.strip()]
    seg = TransportSecuritySettings(enable_dns_rebinding_protection=bool(lista), allowed_hosts=lista,
                                    allowed_origins=[f"https://{h}" for h in lista])  # fmt: skip
    mcp = criar_servidor(api)
    return mcp, ChaveNaUrl(mcp.streamable_http_app(streamable_http_path="/", stateless_http=True, json_response=True,
                                                   transport_security=seg))  # fmt: skip
