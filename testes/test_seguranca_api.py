"""Proteções também valem para recusas, validação inválida e exceção antes da resposta."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from raiz.seguranca_api import SegurancaAPI


def app_teste(**opcoes):
    app = FastAPI()

    @app.get("/ok")
    @app.post("/entrar")
    @app.post("/entrar/confirmar")
    def ok():
        return {"ok": True}

    @app.get("/privado")
    def privado():
        raise HTTPException(401, "sem sessão")

    @app.get("/erro")
    def erro():
        raise ValueError("não publicar o conteúdo desta exceção")

    app.add_middleware(SegurancaAPI, **opcoes)
    return app


@pytest.mark.parametrize("caminho,status", [("/ok", 200), ("/privado", 401), ("/ausente", 404), ("/erro", 500)])
def test_cabecalhos_inclusive_erros(caminho, status):
    cliente = TestClient(app_teste(), base_url="https://testserver", raise_server_exceptions=False)
    r = cliente.get(caminho, headers={"Authorization": "Bearer teste"})
    assert r.status_code == status
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "max-age=" in r.headers["strict-transport-security"]
    assert r.headers["cache-control"] == "no-store"
    assert "conteúdo desta exceção" not in r.text


def test_limite_ignora_cabecalho_falso_e_retorna_retry_after(monkeypatch):
    agora = 100.0
    monkeypatch.setattr("raiz.seguranca_api.time.monotonic", lambda: agora)
    cliente = TestClient(app_teste(limite=2))
    assert cliente.get("/ok").status_code == 200
    assert cliente.get("/ok", headers={"X-Forwarded-For": "192.0.2.1"}).status_code == 200
    r = cliente.get("/ok", headers={"X-Forwarded-For": "192.0.2.2"})
    assert r.status_code == 429
    assert r.headers["retry-after"] == "60"
    assert r.headers["x-content-type-options"] == "nosniff"
    agora += 60
    assert cliente.get("/ok").status_code == 200


def test_login_compartilha_limite_entre_pedir_e_confirmar():
    cliente = TestClient(app_teste(limite=10, login_limite=2))
    assert cliente.post("/entrar").status_code == 200
    assert cliente.post("/entrar/confirmar").status_code == 200
    assert cliente.post("/entrar/").status_code == 429
    assert cliente.get("/ok").status_code == 200


def test_cors_inclui_limite_erro_e_preflight_com_cabecalhos_seguros():
    origem = "https://painel.example.org"
    cliente = TestClient(app_teste(limite=2, origens=[origem]), raise_server_exceptions=False)
    r = cliente.options("/ok", headers={"Origin": origem, "Access-Control-Request-Method": "POST"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == origem
    assert r.headers["x-frame-options"] == "DENY"
    assert cliente.get("/ok", headers={"Origin": origem}).status_code == 200
    erro = cliente.get("/erro", headers={"Origin": origem})
    assert erro.status_code == 500
    limite = cliente.get("/ok", headers={"Origin": origem})
    assert limite.status_code == 429
    for r in (erro, limite):
        assert r.headers["access-control-allow-origin"] == origem
        assert "Retry-After" in r.headers["access-control-expose-headers"]
        assert r.headers["x-content-type-options"] == "nosniff"
    assert int(limite.headers["retry-after"]) > 0


def test_memoria_limitada_nao_expulsa_cliente_ativo_para_liberar_abuso(monkeypatch):
    agora = 100.0
    monkeypatch.setattr("raiz.seguranca_api.time.monotonic", lambda: agora)
    middleware = SegurancaAPI(None, limite=1, max_clientes=2)
    assert middleware._espera("192.0.2.1", False) == 0
    assert middleware._espera("192.0.2.2", False) == 0
    assert middleware._espera("192.0.2.3", False) == 60
    assert middleware._espera("192.0.2.1", False) == 60
    assert len(middleware.clientes) == 2
    agora += 60
    assert middleware._espera("192.0.2.3", False) == 0
    assert len(middleware.clientes) == 1


@pytest.mark.parametrize("metodo,rota", [("PATCH", "/pedidos/um"), ("DELETE", "/prospeccao/buscas-salvas/uma")])
def test_api_aplica_protecao_e_permite_patch_e_exclusao_de_busca(monkeypatch, metodo, rota):
    from raiz.api import criar_app
    from raiz.config import config

    monkeypatch.setenv("RAIZ_API_ORIGENS", "https://painel.example.org")
    config.cache_clear()
    try:
        cliente = TestClient(criar_app(grafo=object(), whatsapp=False))
        r = cliente.get("/rota-inexistente")
        assert r.headers["x-frame-options"] == "DENY"
        r = cliente.options(
            rota,
            headers={
                "Origin": "https://painel.example.org",
                "Access-Control-Request-Method": metodo,
                "Access-Control-Request-Headers": "Authorization,Content-Type",
            },
        )
        assert r.status_code == 200
        assert metodo in r.headers["access-control-allow-methods"]
    finally:
        config.cache_clear()


def test_api_independente_da_vigilancia_tambem_protegida(monkeypatch):
    from raiz.vigilancia.servidor import criar_app

    monkeypatch.setenv("RAIZ_API_LIMITE_MINUTO", "1")
    cliente = TestClient(criar_app(baixar=False))
    r = cliente.get("/vigilancia/projetos")
    assert r.headers["x-frame-options"] == "DENY"
    assert cliente.get("/vigilancia/projetos").status_code == 429


def test_preflight_aceita_revisao_otimista_do_lote():
    origem = "https://painel.example.org"
    cliente = TestClient(app_teste(origens=[origem]))
    r = cliente.options(
        "/pedidos/exemplo/sensibilidade",
        headers={
            "Origin": origem,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,if-match",
        },
    )
    assert r.status_code == 200
    assert "if-match" in r.headers["access-control-allow-headers"].lower()
