"""Um visitante não pode escolher o domínio que recebe o token de login enviado por e-mail."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raiz.pedidos import api


@pytest.mark.parametrize(
    "origem", ["https://atacante.example", "null", "https://painel.example.atacante.example", None]
)
def test_link_usa_destino_configurado_nunca_origin_ou_host(origem, monkeypatch):
    enviados = []
    monkeypatch.setattr(api.S, "pedir_link", lambda engine, email, destino: enviados.append((email, destino)))
    app = FastAPI()
    app.include_router(api.roteador_cliente(lambda request: object(), base_url="https://painel.example/Raiz/"))
    headers = {"Host": "atacante.example", "X-Forwarded-Host": "atacante.example"}
    if origem is not None:
        headers["Origin"] = origem
    r = TestClient(app).post("/entrar", json={"email": "teste@example.invalid"}, headers=headers)
    assert r.status_code == 200 and r.json() == {"enviado": True}
    assert enviados == [("teste@example.invalid", "https://painel.example/Raiz/")]


@pytest.mark.parametrize(
    "destino",
    [
        "",
        "//painel.example",
        "http://painel.example",
        "https://usuario@painel.example",
        "https://painel.example?url=x",
        "https://painel.example#fragmento",
        "https://*.example",
        "https://painel.example:invalida",
        "https://painel. example",
    ],
)
def test_destino_inseguro_nao_cria_token_nem_acessa_banco(destino):
    def nao_acessar(request):
        raise AssertionError("não deveria acessar o banco")

    app = FastAPI()
    app.include_router(api.roteador_cliente(nao_acessar, base_url=destino))
    r = TestClient(app).post("/entrar", json={"email": "teste@example.invalid"})
    assert r.status_code == 503


def test_configuracao_api_usa_canonica_ou_primeira_origem(monkeypatch):
    from raiz import api as principal
    from raiz.config import Config

    enviados = []
    monkeypatch.setattr(api.S, "pedir_link", lambda engine, email, destino: enviados.append(destino))
    for canonica, esperado in [
        (None, "http://127.0.0.1:4173/"),
        ("https://painel.example/Raiz", "https://painel.example/Raiz/"),
    ]:
        cfg = Config(_env_file=None, api_origens="http://127.0.0.1:4173,https://outro.example", login_base_url=canonica)
        monkeypatch.setattr(principal, "config", lambda cfg=cfg: cfg)
        cliente = TestClient(principal.criar_app(engine=object(), grafo=object(), whatsapp=False))
        r = cliente.post(
            "/entrar", json={"email": "teste@example.invalid"}, headers={"Origin": "https://atacante.example"}
        )
        assert r.status_code == 200
        assert enviados[-1] == esperado
