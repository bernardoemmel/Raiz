"""MCP v2 real, escopos por ferramenta e HTTP OAuth: nenhuma chave ou texto externo autoriza ações."""

import asyncio
import contextlib
import json
import time

import anyio
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from mcp.client.client import Client
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from sqlalchemy import text

from raiz.publica.oauth import acesso_interno, rotas_metadados
from raiz.publica.servidor_mcp import ApiRaiz, app_http, criar_servidor
from testes.test_publica_oauth import assinador, verificador  # noqa: F401
from testes.test_publica_trabalhos import empresa, eng  # noqa: F401

FERRAMENTAS = {
    "consultar_disponibilidade",
    "pedir_lote",
    "comparar_lotes",
    "acompanhar_contato",
    "preparar_reserva",
    "cancelar",
}
PID = "00000000-0000-4000-8000-000000000001"


def backend():
    app = FastAPI()
    chamadas = []

    @app.api_route("/v1/{rota:path}", methods=["GET", "POST"])
    async def responder(rota: str, request: Request):
        acesso = acesso_interno(request)
        chamadas.append((rota, acesso, request.headers.get("idempotency-key")))
        assert acesso is not None and acesso.via == "mcp"
        return {"pedido_id": PID, "estado": "submitted", "nome_proprietario": "Não pode sair"}

    return app, chamadas


def test_seis_ferramentas_sdk_estrutura_e_sem_oauth_falha():
    async def executar():
        async with Client(criar_servidor()) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
            assert set(tools) == FERRAMENTAS
            assert "P10/P50/P90" in tools["consultar_disponibilidade"].description
            assert "nunca aprova nem paga" in tools["preparar_reserva"].description
            assert {"campos", "idempotency_key"} <= set(tools["pedir_lote"].input_schema["required"])
            assert all("idempotency_key" in ferramenta.input_schema["required"] for ferramenta in tools.values())
            r = await c.call_tool("consultar_disponibilidade", {"campos": {}, "idempotency_key": "consulta-sem-oauth"})
            assert r.is_error and '"status":401' in r.content[0].text

    anyio.run(executar)


def test_escopos_impedem_reserva_e_ponte_preserva_empresa_idempotencia():
    app, chamadas = backend()
    token = AccessToken(token="interno", client_id="agente", scopes=["consultar", "pedir"], claims={"empresa_id": 42})

    async def executar():
        marcador = auth_context_var.set(AuthenticatedUser(token))
        try:
            async with Client(criar_servidor(ApiRaiz(app=app))) as c:
                r = await c.call_tool(
                    "pedir_lote", {"campos": {"onde": {"ufs": ["PA"]}}, "idempotency_key": "pedido-um-milhao"}
                )
                assert not r.is_error and r.structured_content["estado"] == "submitted"
                assert "nome_proprietario" not in r.structured_content
                r = await c.call_tool("preparar_reserva", {"pedido_id": PID, "idempotency_key": "reserva-um-milhao"})
                assert r.is_error and "reservar" in r.content[0].text
        finally:
            auth_context_var.reset(marcador)

    anyio.run(executar)
    assert len(chamadas) == 1 and chamadas[0][1].cliente_id == 42 and chamadas[0][2] == "pedido-um-milhao"


def test_http_oauth_real_descoberta_e_chave_na_url_rejeitada(assinador, monkeypatch):  # noqa: F811
    assinar, _ = assinador
    v = verificador(assinador, monkeypatch)
    app, chamadas = backend()
    mcp, http = app_http(ApiRaiz(app=app), hosts="api.raiz.example", verificador=v)

    @contextlib.asynccontextmanager
    async def vida(app):
        async with mcp.session_manager.run():
            yield

    principal = FastAPI(lifespan=vida)
    principal.router.routes.extend(rotas_metadados(v))
    principal.mount("/mcp", http)
    h = {
        "MCP-Protocol-Version": "2026-07-28",
        "MCP-Method": "server/discover",
        "Accept": "application/json, text/event-stream",
    }
    envelope = {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    corpo = {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": envelope}}
    with TestClient(principal, base_url="https://api.raiz.example") as c:
        meta = c.get("/.well-known/oauth-protected-resource/mcp").json()
        assert meta["scopes_supported"] == ["consultar", "pedir", "reservar"]
        for url, headers in (
            ("/mcp/", h),
            ("/mcp/?chave=raiz_teste", h),
            ("/mcp/", {**h, "Authorization": "Bearer raiz_teste"}),
        ):
            r = c.post(url, json=corpo, headers=headers)
            assert r.status_code == 401 and r.headers["content-type"].startswith("application/problem+json")
            assert "/.well-known/oauth-protected-resource/mcp" in r.headers["www-authenticate"]
        r = c.post("/mcp/", json=corpo, headers={**h, "Authorization": f"Bearer {assinar()}"})
        assert r.status_code == 200, r.text
        assert "2026-07-28" in r.json()["result"]["supportedVersions"]
        chamada = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "_meta": envelope,
                "name": "consultar_disponibilidade",
                "arguments": {"campos": {}, "idempotency_key": "consulta-http-oauth"},
            },
        }
        r = c.post(
            "/mcp/",
            json=chamada,
            headers={
                **h,
                "MCP-Method": "tools/call",
                "MCP-Name": chamada["params"]["name"],
                "Authorization": f"Bearer {assinar()}",
            },
        )
        assert r.status_code == 200, r.text
        assert not r.json()["result"].get("isError"), r.text
        chamada["params"] = {
            "_meta": envelope,
            "name": "preparar_reserva",
            "arguments": {"pedido_id": PID, "idempotency_key": "reserva-proibida"},
        }
        r = c.post(
            "/mcp/",
            json=chamada,
            headers={
                **h,
                "MCP-Method": "tools/call",
                "MCP-Name": chamada["params"]["name"],
                "Authorization": f"Bearer {assinar()}",
            },
        )
        assert r.json()["result"]["isError"]
        assert len(chamadas) == 1


def test_timeout_de_ferramenta_menor_que_cinco_segundos(monkeypatch):
    app = FastAPI()

    @app.post("/v1/agentes/consultar_disponibilidade")
    async def lento():
        await anyio.sleep(30)

    token = AccessToken(token="interno", client_id="agente", scopes=["consultar"], claims={"empresa_id": 42})

    async def executar():
        marcador = auth_context_var.set(AuthenticatedUser(token))
        try:
            t = time.monotonic()
            async with Client(criar_servidor(ApiRaiz(app=app))) as c:
                r = await c.call_tool(
                    "consultar_disponibilidade", {"campos": {}, "idempotency_key": "consulta-timeout"}
                )
                assert r.is_error and "prazo_excedido" in r.content[0].text
            assert time.monotonic() - t < 5
        finally:
            auth_context_var.reset(marcador)

    anyio.run(executar)


@pytest.mark.banco
@pytest.mark.parametrize("nome", ["consultar_disponibilidade", "comparar_lotes", "acompanhar_contato"])
def test_retry_apos_timeout_preserva_operacao_e_debito_no_banco(eng, empresa, nome):  # noqa: F811
    """A primeira submissão confirma no PostgreSQL, mas a resposta chega depois do prazo MCP."""
    from raiz.publica import conta as CT
    from raiz.publica import trabalhos as T
    from raiz.publica.problemas import problema

    app = FastAPI()
    recebidas = []
    with eng.begin() as con:
        con.execute(text("update negocio.conta_api set testes_restantes=0 where cliente_id=:c"), {"c": empresa})

    @app.get("/v1/operacoes/{pedido_id}")
    async def nao_e_operacao(pedido_id: str):
        # Um pedido de negócio vai ao POST de acompanhamento; só o recibo de operação fica no GET.
        return problema(404, "operacao_nao_encontrada", "operação não encontrada", "confira o identificador")

    @app.post("/v1/agentes/{ferramenta}")
    async def submeter(ferramenta: str, request: Request):
        acesso = acesso_interno(request)
        assert acesso is not None and acesso.cliente_id == empresa
        chave = request.headers["idempotency-key"]
        recebidas.append(chave)
        resultado = T.submeter(eng, empresa, ferramenta, await request.json(), chave)
        if len(recebidas) == 1:
            await anyio.sleep(3.2)
        return resultado

    api = ApiRaiz(app=app)
    token = AccessToken(token="interno", client_id="agente", scopes=["consultar"], claims={"empresa_id": empresa})
    argumentos = {"campos": {}} if nome == "consultar_disponibilidade" else {"pedido_id": PID}
    argumentos["idempotency_key"] = "mesma-intencao-apos-timeout"

    async def executar():
        marcador = auth_context_var.set(AuthenticatedUser(token))
        try:
            async with Client(criar_servidor(api)) as c:
                primeiro = await c.call_tool(nome, argumentos)
                assert primeiro.is_error and "prazo_excedido" in primeiro.content[0].text
                repetido = await c.call_tool(nome, argumentos)
                assert not repetido.is_error and repetido.structured_content["estado"] == "submitted"
                # A execução original continua e também precisa concluir sem criar outra operação.
                with anyio.fail_after(2):
                    await asyncio.gather(*api._pendentes)
                assert not api._pendentes
        finally:
            auth_context_var.reset(marcador)

    anyio.run(executar)
    assert recebidas == [argumentos["idempotency_key"]] * 2
    with eng.connect() as con:
        assert (
            con.execute(
                text("select count(*) from negocio.trabalho_api where cliente_id=:c"), {"c": empresa}
            ).scalar_one()
            == 1
        )
        assert (
            con.execute(
                text("select count(*) from negocio.lancamento_api where cliente_id=:c and tipo='debito'"),
                {"c": empresa},
            ).scalar_one()
            == 1
        )
        saldo = con.execute(
            text("select saldo_rs from negocio.conta_api where cliente_id=:c"), {"c": empresa}
        ).scalar_one()
        assert float(saldo) == 2000 - CT.premissas()["precos"][nome]


def test_acompanhar_operacao_preserva_get_sem_nova_submissao():
    app, chamadas = backend()
    token = AccessToken(token="interno", client_id="agente", scopes=["consultar"], claims={"empresa_id": 42})

    async def executar():
        marcador = auth_context_var.set(AuthenticatedUser(token))
        try:
            async with Client(criar_servidor(ApiRaiz(app=app))) as c:
                r = await c.call_tool(
                    "acompanhar_contato", {"pedido_id": PID, "idempotency_key": "acompanhar-operacao"}
                )
                assert not r.is_error
        finally:
            auth_context_var.reset(marcador)

    anyio.run(executar)
    assert len(chamadas) == 1 and chamadas[0][0] == f"operacoes/{PID}" and chamadas[0][2] is None


def test_deadline_nao_espera_rota_sincrona_e_preserva_execucao_unica_com_chave_original():
    app = FastAPI()
    chamadas, concluidas = [], []

    @app.post("/v1/agentes/pedir_lote")
    def lento(request: Request):
        chamadas.append(request.headers["idempotency-key"])
        time.sleep(5.2)
        concluidas.append(True)
        return {"pedido_id": PID, "estado": "submitted"}

    api = ApiRaiz(app=app)
    token = AccessToken(token="interno", client_id="agente", scopes=["pedir"], claims={"empresa_id": 42})

    async def executar():
        marcador = auth_context_var.set(AuthenticatedUser(token))
        try:
            async with Client(criar_servidor(api)) as c:
                inicio = time.monotonic()
                r = await c.call_tool("pedir_lote", {"campos": {}, "idempotency_key": "pedido-original-teste"})
                assert time.monotonic() - inicio < 4
                assert r.is_error
                texto = r.content[0].text
                p = json.loads(texto[texto.index("{") :])
                assert p["status"] == 504 and p["type"].endswith("#erro-prazo_excedido")
                assert "mesma Idempotency-Key" in p["corrigir"]
                assert chamadas == ["pedido-original-teste"] and concluidas == []
                assert len(api._pendentes) == 1
                await anyio.sleep(2.5)
                assert concluidas == [True] and chamadas == ["pedido-original-teste"]
                assert not api._pendentes
        finally:
            auth_context_var.reset(marcador)

    anyio.run(executar)
