"""API pública e servidor MCP para os agentes de IA das empresas clientes, com o banco: chave por empresa (além do
login por e-mail), limite de chamadas por chave, cada chamada gravada (empresa, ferramenta, pedido, versão do modelo),
reserva pedida pelo agente que espera a confirmação de uma pessoa, e o teste de ponta a ponta: um agente de teste faz
o pedido de 1 milhão de créditos pelo MCP e recebe as 3 opções. Nada pessoal do dono sai."""

import datetime as dt
import re

import anyio
import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from raiz.carga import carregar_pasta
from raiz.pedidos import servico as S
from raiz.pessoal import gerar_chave
from raiz.publica import chaves as K
from raiz.publica.servidor_mcp import ApiRaiz, criar_servidor
from testes.conftest import AMOSTRA

pytestmark = pytest.mark.banco
TODA_TERRA = ["matricula_conferida", "matricula_a_conferir", "concessao", "assentamento", "posse_em_titulacao"]
PEDIDO = {"meta": {"tipo": "creditos", "valor": 1_000_000}, "cronograma": "profloresta",
          "onde": {"ufs": ["PA"], "biomas": ["Amazônia"]}, "terra": TODA_TERRA}  # fmt: skip
PESSOAL = re.compile(r"'(nome[a-z_]*|cpf[a-z_]*|cnpj[a-z_]*|telefone|email|contato)'", re.I)


@pytest.fixture(scope="module")
def eng(banco_url):
    e = create_engine(banco_url)
    with e.begin() as c:
        c.execute(text("truncate funil.rodada, funil.imovel, negocio.oferta, negocio.cliente cascade"))
        c.execute(text("truncate negocio.interesse_dono, negocio.interesse_evento"))
    carregar_pasta(e, AMOSTRA, dt.date(2026, 11, 12))
    yield e
    e.dispose()


@pytest.fixture(scope="module")
def cofre():
    import raiz.pessoal as P

    mp = pytest.MonkeyPatch()
    mp.setattr(P, "config", lambda: type("C", (), {"chave_pessoal": SecretStr(gerar_chave())})())
    yield
    mp.undo()


@pytest.fixture(scope="module")
def app(eng):
    from raiz.api import criar_app

    return criar_app(engine=eng, grafo=object(), deps=object(), whatsapp=False)


@pytest.fixture(scope="module")
def cl(app):
    with TestClient(app) as c:  # o ciclo de vida (e o gerenciador de sessões do MCP) roda uma vez por aplicação
        yield c


@pytest.fixture(scope="module")
def empresa(eng, cofre):
    """Uma pessoa da empresa entra pelo e-mail e cria a chave do agente de IA."""
    cid, sessao = S.criar_cliente(eng, "Desenvolvedora de restauração", "compras@empresa.example")
    return {"cliente_id": cid, "sessao": sessao}


def _sem_pessoal(obj) -> None:
    assert not PESSOAL.search(str(obj)), PESSOAL.search(str(obj))


def test_chave_por_empresa_limite_e_registro(eng, cl, empresa):
    h_sessao = {"Authorization": f"Bearer {empresa['sessao']}"}
    assert cl.post("/v1/base", json=PEDIDO).status_code == 401  # sem chave nem sessão
    assert cl.post("/v1/base", json=PEDIDO, headers={"X-Chave-API": "raiz_falsa"}).status_code == 401
    # só uma pessoa (sessão) cria a chave; a chave aparece uma vez
    r = cl.post("/v1/chaves", json={"rotulo": "agente de compras", "limite_minuto": 4}, headers=h_sessao)
    assert r.status_code == 200 and r.json()["chave"].startswith("raiz_")
    chave = r.json()["chave"]
    assert cl.post("/v1/chaves", json={}, headers={"X-Chave-API": chave}).status_code == 403
    lista = cl.get("/v1/chaves", headers=h_sessao).json()
    assert lista[0]["prefixo"] == r.json()["prefixo"] and "chave" not in lista[0]
    with eng.connect() as c:  # só o hash fica guardado
        assert c.execute(text("select count(*) from negocio.chave_api where hash = :h"),
                         {"h": chave}).scalar() == 0  # fmt: skip
    # quanto existe na base, pela chave (com o modelo do agente no cabeçalho)
    h = {"X-Chave-API": chave, "X-Agente-Modelo": "agente-de-teste-1"}
    b = cl.post("/v1/base", json=PEDIDO, headers=h)
    assert b.status_code == 200 and b.json()["creditos"]["p10"] < b.json()["creditos"]["p50"]
    _sem_pessoal(b.json())
    # Bearer raiz_... também vale
    assert cl.get("/v1/pedidos", headers={"Authorization": f"Bearer {chave}"}).status_code == 200
    # limite por chave: 4 por minuto
    cl.get("/v1/pedidos", headers=h)
    cl.get("/v1/pedidos", headers=h)
    r = cl.get("/v1/pedidos", headers=h)
    assert r.status_code == 429 and r.headers["retry-after"] == "60"
    # cada chamada gravada com a empresa, a ferramenta, a versão do modelo e o modelo do agente
    ch = K.chamadas(eng, empresa["cliente_id"])
    base = next(x for x in ch if x["ferramenta"] == "base")
    assert base["via"] == "api" and base["agente_modelo"] == "agente-de-teste-1"
    assert base["versao_modelo"].startswith("pedidos-") and base["status"] == 200
    # revogada, a chave para de valer
    assert cl.delete(f"/v1/chaves/{r.request.headers['x-chave-api'][:13]}", headers=h_sessao).status_code == 200
    assert cl.get("/v1/pedidos", headers=h).status_code == 401


def test_pedido_pela_api_reserva_espera_uma_pessoa(eng, cl, empresa):
    k = K.criar(eng, empresa["cliente_id"], "agente", limite_minuto=100)
    h = {"X-Chave-API": k["chave"]}
    p = cl.post("/v1/pedidos", json={**PEDIDO, "meta": {"tipo": "creditos", "valor": 400_000}}, headers=h)
    assert p.status_code == 200
    pid = p.json()["id"]
    ops = cl.get(f"/v1/pedidos/{pid}/opcoes", headers=h).json()
    assert [o["id"] for o in ops] == ["barata", "segura", "compacta"]
    _sem_pessoal(ops)
    cod = ops[0]["itens"][0]["cod_imovel"]
    fz = cl.get(f"/v1/fazendas/{cod}", headers=h).json()
    assert fz["cod_imovel"] == cod and "explicacao" in fz and fz["creditos_ate_ano_25"]["p50"] is not None
    _sem_pessoal(fz)
    assert cl.get("/v1/fazendas/PA-0000000-NAOEXISTE", headers=h).status_code == 404
    r = cl.post(f"/v1/pedidos/{pid}/solicitar-interesse", json={"opcao": "barata"}, headers=h)
    assert r.status_code == 200
    an = cl.get(f"/v1/pedidos/{pid}/andamento", headers=h).json()
    _sem_pessoal(an)
    # os donos aceitam (a Raíz registra) até o grupo fechar
    estado = "buscando_interesse"
    for _ in range(8):
        for cod_ in S.contatados_do_pedido(eng, pid):
            S.registrar_resposta(eng, cod_, "interessado", "whatsapp", None, "termo-lgpd-2026a", pid,
                                 avancar_pedidos=False)  # fmt: skip
        estado = S.avancar(eng, pid)
        if estado == "grupo_pronto":
            break
    assert estado == "grupo_pronto"
    # o agente pede a reserva: nasce aguardando confirmação, sem Pix e sem o link na resposta
    tokens = []
    S.ENVIO_CONFIRMACAO = lambda cliente, token: tokens.append(token)
    try:
        res = cl.post(f"/v1/pedidos/{pid}/reservar", headers=h)
    finally:
        S.ENVIO_CONFIRMACAO = None
    assert res.status_code == 200
    j = res.json()
    assert j["aguardando_confirmacao"] and j["pix"] is None and not j["pago"] and tokens
    assert tokens[0] not in res.text  # o agente nunca recebe o link
    with eng.connect() as c:
        assert (
            c.execute(
                text("""select count(*) from negocio.cobranca b join negocio.reserva r
                                 on r.id = b.reserva_id where r.pedido_id = :p"""),
                {"p": pid},
            ).scalar()
            == 0
        )
        assert (
            c.execute(
                text("""select count(*) from negocio.notificacao where pedido_id = :p
                                 and tipo = 'confirmar_reserva' and canal = 'email'"""),
                {"p": pid},
            ).scalar()
            == 1
        )
    # uma pessoa da empresa abre o link e confirma: aí sai o Pix (uma vez só)
    pg = cl.get(f"/v1/reservas/confirmar/{tokens[0]}")
    assert pg.status_code == 200 and "Confirmar" in pg.text
    ok = cl.post(f"/v1/reservas/confirmar/{tokens[0]}")
    assert ok.status_code == 200 and "Pix copia e cola" in ok.text
    assert cl.post(f"/v1/reservas/confirmar/{tokens[0]}").status_code == 410
    r2 = cl.get(f"/v1/pedidos/{pid}/reserva", headers=h).json()
    assert r2["estado"] == "aguardando_pagamento" and r2["pix"]["copia_e_cola"]
    ch = K.chamadas(eng, empresa["cliente_id"], pid)
    assert {"montar", "opcoes", "solicitar", "andamento", "reservar"} <= {x["ferramenta"] for x in ch}


def test_agente_pede_um_milhao_pelo_mcp_e_recebe_as_3_opcoes(eng, app, empresa):
    """Ponta a ponta: um agente de teste (cliente MCP) liga no servidor MCP da Raíz, que chama a API pública com a
    chave da empresa, e faz o pedido de 1 milhão de créditos no Pará."""
    from mcp.client.client import Client

    k = K.criar(eng, empresa["cliente_id"], "agente MCP", limite_minuto=100)
    api = ApiRaiz(url="http://raiz.teste", chave=k["chave"], transporte=httpx.ASGITransport(app=app),
                  agente_modelo="agente-mcp-de-teste")  # fmt: skip
    servidor = criar_servidor(api)

    async def agente():
        async with Client(servidor) as cli:
            nomes = {t.name for t in (await cli.list_tools()).tools}
            assert {"buscar_base", "montar_lote", "ver_opcoes", "solicitar_interesse", "andamento_do_pedido",
                    "explicar_fazenda", "pedir_reserva"} <= nomes  # fmt: skip
            base = await cli.call_tool("buscar_base", {"meta_valor": 1_000_000, "ufs": ["PA"], "terra": TODA_TERRA})
            assert not base.is_error and base.structured_content["creditos"]["p50"] > 0
            lote = await cli.call_tool("montar_lote", {"meta_valor": 1_000_000, "ufs": ["PA"], "terra": TODA_TERRA})
            assert not lote.is_error, lote.content
            lt = lote.structured_content
            assert [o["id"] for o in lt["opcoes"]] == ["barata", "segura", "compacta"]
            for o in lt["opcoes"]:
                assert o["creditos"]["p10"] <= o["creditos"]["p50"] <= o["creditos"]["p90"]
                assert o["fazendas_no_lote"] and "itens" not in o
            ops = await cli.call_tool("ver_opcoes", {"pedido_id": lt["pedido_id"], "com_fazendas": True})
            cod = ops.structured_content["opcoes"][0]["itens"][0]["cod_imovel"]
            fz = await cli.call_tool("explicar_fazenda", {"cod_imovel": cod})
            assert fz.structured_content["cod_imovel"] == cod
            _sem_pessoal(fz.structured_content)
            _sem_pessoal(ops.structured_content)
            return lt["pedido_id"]

    pid = anyio.run(agente)
    ch = K.chamadas(eng, empresa["cliente_id"])
    mcp = [x for x in ch if x["via"] == "mcp"]
    assert {"buscar_base", "montar_lote", "ver_opcoes", "explicar_fazenda"} <= {x["ferramenta"] for x in mcp}
    assert all(x["agente_modelo"] == "agente-mcp-de-teste" for x in mcp)
    assert any(str(x["pedido_id"]) == pid for x in mcp)


def test_mcp_por_http_na_propria_api(eng, cl, empresa):
    """O servidor MCP remoto em /mcp (streamable HTTP, sem estado): a chave vai no cabeçalho de cada chamada."""
    k = K.criar(eng, empresa["cliente_id"], "agente remoto", limite_minuto=100)
    h = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
         "X-Chave-API": k["chave"], "MCP-Protocol-Version": "2025-06-18"}  # fmt: skip
    ini = cl.post(
        "/mcp/",
        headers=h,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "teste", "version": "1"},
            },
        },
    )
    assert ini.status_code == 200, ini.text
    lista = cl.post("/mcp/", headers=h, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert lista.status_code == 200 and "montar_lote" in lista.text
    r = cl.post(
        "/mcp/",
        headers=h,
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "buscar_base",
                "arguments": {"meta_valor": 1000000, "ufs": ["PA"], "terra": TODA_TERRA},
            },
        },
    )
    assert r.status_code == 200 and '"isError":false' in r.text.replace(" ", ""), r.text[:500]
    sem = {k_: v for k_, v in h.items() if k_ != "X-Chave-API"}
    r = cl.post(
        "/mcp/",
        headers=sem,
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "buscar_base", "arguments": {"meta_valor": 1000000}},
        },
    )
    assert "chave" in r.text  # sem a chave, o erro diz o que falta
    # conector que não manda cabeçalho (ChatGPT, Claude.ai): a chave na URL
    corpo = {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
             "params": {"name": "buscar_base", "arguments": {"meta_valor": 1000000, "ufs": ["PA"]}}}  # fmt: skip
    r = cl.post(f"/mcp/?chave={k['chave']}", headers=sem, json=corpo)
    assert '"isError":false' in r.text.replace(" ", ""), r.text[:300]
