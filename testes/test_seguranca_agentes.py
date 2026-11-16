"""Segurança global compatível com a API paga, OAuth MCP e aprovação humana."""

import anyio
import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.testclient import TestClient

from raiz.seguranca_api import SegurancaAPI

ORIGEM = "https://painel.example.org"


def aplicacao(**opcoes):
    app = FastAPI()

    @app.get("/v1/operacoes/pedido")
    def operacao():
        return {"estado": "submitted"}

    @app.post("/mcp/")
    def mcp():
        return JSONResponse(
            {"detail": "OAuth necessário"},
            status_code=401,
            headers={
                "WWW-Authenticate": 'Bearer resource_metadata="https://api.example/.well-known/oauth-protected-resource/mcp"'
            },
        )

    @app.get("/aprovacao")
    def aprovacao():
        return HTMLResponse(
            '<script nonce="teste-nao-secreto">0</script>',
            headers={
                "Content-Security-Policy": (
                    "default-src 'none'; script-src 'nonce-teste-nao-secreto'; frame-ancestors 'none'"
                )
            },
        )

    @app.get("/erro")
    def erro():
        raise ValueError("mensagem interna não publicável")

    app.add_middleware(SegurancaAPI, origens=[ORIGEM], **opcoes)
    return app


@pytest.mark.parametrize("metodo", ["POST", "PUT", "DELETE"])
def test_preflight_permite_mcp_chaves_idempotencia_e_administracao(metodo):
    cliente = TestClient(aplicacao())
    cabecalhos = (
        "Authorization,Content-Type,X-Chave-API,Idempotency-Key,MCP-Protocol-Version,"
        "MCP-Method,MCP-Name,MCP-Session-Id,Last-Event-ID"
    )
    r = cliente.options(
        "/mcp/" if metodo == "POST" else "/v1/conta/permissoes/reservar",
        headers={
            "Origin": ORIGEM,
            "Access-Control-Request-Method": metodo,
            "Access-Control-Request-Headers": cabecalhos,
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == ORIGEM
    assert metodo in r.headers["access-control-allow-methods"]
    permitidos = r.headers["access-control-allow-headers"].lower()
    assert all(nome.lower() in permitidos for nome in cabecalhos.split(","))
    negado = cliente.options(
        "/mcp/",
        headers={"Origin": "https://outra.example.org", "Access-Control-Request-Method": metodo},
    )
    assert negado.status_code == 400 and "access-control-allow-origin" not in negado.headers


def test_desafio_oauth_fica_legivel_no_navegador_e_api_nao_e_cacheada():
    cliente = TestClient(aplicacao())
    r = cliente.post("/mcp/", headers={"Origin": ORIGEM})
    assert r.status_code == 401 and "resource_metadata=" in r.headers["www-authenticate"]
    expostos = r.headers["access-control-expose-headers"].lower()
    assert all(h in expostos for h in ("www-authenticate", "retry-after", "location", "mcp-session-id"))
    assert r.headers["cache-control"] == "no-store"
    r = cliente.get("/v1/operacoes/pedido", headers={"X-Chave-API": "chave-de-teste"})
    assert r.headers["cache-control"] == "no-store"


def test_politica_nonce_da_pagina_e_preservada():
    r = TestClient(aplicacao()).get("/aprovacao")
    assert (
        r.headers["content-security-policy"]
        == "default-src 'none'; script-src 'nonce-teste-nao-secreto'; frame-ancestors 'none'"
    )
    assert r.headers["x-frame-options"] == "DENY"


def test_recusa_global_e_falha_interna_sao_rfc9457_sem_url_ou_excecao():
    cliente = TestClient(aplicacao(limite=1), raise_server_exceptions=False)
    erro = cliente.get("/erro", headers={"Origin": ORIGEM})
    limite = cliente.get("/v1/reservas/confirmar/token-que-nao-pode-sair", headers={"Origin": ORIGEM})
    for r, status in ((erro, 500), (limite, 429)):
        assert r.status_code == status and r.json()["status"] == status
        assert r.headers["content-type"].startswith("application/problem+json")
        assert {"type", "title", "detail", "status"} <= r.json().keys()
        assert "não publicável" not in r.text and "token-que-nao-pode-sair" not in r.text
        assert r.headers["access-control-allow-origin"] == ORIGEM
    assert int(limite.headers["retry-after"]) > 0


def test_so_sentinela_interna_evitar_contagem_duplicada_nao_cabecalhos():
    marcador = object()

    async def app(scope, receive, send):
        await JSONResponse({"ok": True})(scope, receive, send)

    middleware = SegurancaAPI(
        app,
        limite=1,
        autenticada_interna=lambda scope: scope.get("state", {}).get("marcador") is marcador,
    )
    respostas = []

    async def enviar(mensagem):
        if mensagem["type"] == "http.response.start":
            respostas.append(mensagem["status"])

    async def executar():
        base = {"type": "http", "method": "POST", "path": "/v1/agentes/pedir_lote", "client": ("127.0.0.1", 1)}
        # A segunda passagem por ASGI conserva a autenticação da empresa e não é outra requisição de rede.
        await middleware({**base, "state": {"marcador": marcador}}, None, enviar)
        assert not middleware.clientes
        await middleware({**base, "headers": [(b"x-raiz-interno", b"true")]}, None, enviar)
        await middleware({**base, "state": {"marcador": "true"}}, None, enviar)

    anyio.run(executar)
    assert respostas == [200, 200, 429]
