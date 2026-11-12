"""A representação Markdown preserva os portões da ficha e a projeção pública."""

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from raiz import api, prospeccao_acesso, prospeccao_api, publico

CAR = "PA-1504950-" + "A" * 32


@pytest.fixture
def cliente(monkeypatch):
    cfg = type("C", (), {"api_token": SecretStr("operacao-markdown"), "api_origens": ""})()
    monkeypatch.setattr(api, "config", lambda: cfg)
    monkeypatch.setattr(
        prospeccao_api.pedidos, "cliente_da_sessao", lambda _engine, token: 7 if token == "sessao-markdown" else None
    )
    monkeypatch.setattr(prospeccao_acesso, "limitar", lambda *args: None)

    def bloquear(*args):
        raise prospeccao_acesso.ErroAcesso(402, "A ficha exige crédito pago.")

    monkeypatch.setattr(prospeccao_acesso, "exigir_desbloqueio", bloquear)
    app = api.criar_app(engine=object(), grafo=object(), deps=object(), whatsapp=False)
    with TestClient(app) as cl:
        yield cl


def test_accept_markdown_nao_troca_autorizacao_operacional_ou_pagamento(cliente):
    for rota in (f"/imoveis/{CAR}", f"/imoveis/{CAR}/ficha", f"/imoveis/{CAR}/certidoes"):
        for autorizacao in ({}, {"Authorization": "Bearer sessao-markdown"}):
            r = cliente.get(rota, headers={"Accept": "text/markdown", **autorizacao})
            assert r.status_code == 401
            assert CAR not in r.text
    for autorizacao, status in (
        ({}, 401),
        ({"Authorization": "Bearer operacao-markdown"}, 401),
        ({"Authorization": "Bearer sessao-markdown"}, 402),
    ):
        r = cliente.get(f"/prospeccao/fichas/{CAR}", headers={"Accept": "text/markdown", **autorizacao})
        assert r.status_code == status
        assert CAR not in r.text


@pytest.mark.parametrize("aceito", [False, True])
def test_codigo_curto_markdown_nao_exporta_ficha_completa_ou_campos_do_dono(cliente, monkeypatch, aceito):
    privado = "conteudo_privado_nao_publicar"
    dados = {
        "codigo": "AB23CDE",
        "municipio": "Parauapebas",
        "uf": "PA",
        "hectares": "25",
        "frase": "podem voltar a ser mata",
        "selo": "ouro" if aceito else "bronze",
        "aceito": aceito,
        "_cod_imovel": CAR,
        "_cod_busca": "localizacao-interna",
        "nome_dono": privado,
        "contato": {"nome": privado, "telefone": privado},
        "credito": {"p10": privado, "p50": privado, "p90": privado},
        "tir": privado,
        "pendencias": [privado],
        "imovel": {"nome": privado, "dados": {"contato": privado}},
    }
    monkeypatch.setattr(publico, "dados", lambda *args: dados)
    monkeypatch.setattr(publico, "_imagens_do_aceite", lambda _dados: {})
    for endereco, accept in (
        ("/p/AB23CDE.md", "*/*"),
        ("/p/AB23CDE", "text/markdown"),
        ("/p/AB23CDE", "text/html"),
    ):
        r = cliente.get(endereco, headers={"Accept": accept})
        assert r.status_code == 200 and "Parauapebas" in r.text
        assert privado not in r.text and "localizacao-interna" not in r.text
        assert (CAR in r.text) is aceito
