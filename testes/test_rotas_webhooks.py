"""Configuração operacional por pessoa: segredo único, isolamento e cancelamento da outbox."""

import os
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from raiz import pessoal
from raiz.pedidos import servico as S
from raiz.publica import api
from raiz.publica import chaves as K
from raiz.publica import webhooks as W

pytestmark = pytest.mark.banco


@pytest.fixture
def sistema(request, monkeypatch):
    url = os.environ.get("RAIZ_EVENTOS_URL_TESTE") or request.getfixturevalue("banco_url")
    eng = create_engine(url)
    chave = SecretStr(pessoal.gerar_chave())
    monkeypatch.setattr(pessoal, "config", lambda: SimpleNamespace(chave_pessoal=chave))
    monkeypatch.setenv("RAIZ_WEBHOOK_HOSTS", "eventos.example.com")
    empresas = []
    for _ in range(2):
        cid, sessao = S.criar_cliente(eng, "Teste webhooks")
        with eng.begin() as con:
            con.execute(
                text("""INSERT INTO negocio.conta_api
                (cliente_id,cnpj_hmac,cnpj_mascarado,termos_versao)
                VALUES (:c,:h,'**','teste')"""),
                {"c": cid, "h": uuid.uuid4().hex},
            )
        empresas.append(SimpleNamespace(id=cid, sessao=sessao, chave=K.criar(eng, cid)["chave"]))
    with TestClient(api.criar(lambda _: eng)) as cl:
        yield SimpleNamespace(eng=eng, cl=cl, empresas=empresas)
    with eng.begin() as con:
        for empresa in empresas:
            con.execute(text("DELETE FROM negocio.cliente WHERE id=:c"), {"c": empresa.id})
    eng.dispose()


def _headers(empresa, chave="webhook-unico-01"):
    return {"Authorization": f"Bearer {empresa.sessao}", "Idempotency-Key": chave}


def test_secret_aparece_uma_vez_e_replay_nao_duplica(sistema):
    empresa = sistema.empresas[0]
    corpo = {"url": "https://eventos.example.com/raiz"}
    resposta = sistema.cl.post("/webhooks", json=corpo, headers=_headers(empresa))
    assert resposta.status_code == 201, resposta.text
    primeiro = resposta.json()
    assert primeiro["segredo"].startswith("whsec_")
    assert resposta.headers["Cache-Control"] == "no-store"
    repetido = sistema.cl.post("/webhooks", json=corpo, headers=_headers(empresa))
    assert repetido.status_code == 200 and repetido.json()["id"] == primeiro["id"]
    assert repetido.json()["segredo"] is None
    lista = sistema.cl.get("/webhooks", headers=_headers(empresa))
    assert len(lista.json()["inscricoes"]) == 1
    assert primeiro["segredo"] not in lista.text and "eventos.example.com" not in lista.text
    with sistema.eng.connect() as con:
        linha = con.execute(
            text("SELECT segredo_cifrado,url_cifrada FROM negocio.webhook_inscricao WHERE id=:id"),
            {"id": primeiro["id"]},
        ).one()
    assert primeiro["segredo"].encode() not in bytes(linha.segredo_cifrado)
    assert b"example.com" not in bytes(linha.url_cifrada)
    conflito = sistema.cl.post(
        "/webhooks", json={"url": "https://eventos.example.com/outro"}, headers=_headers(empresa)
    )
    assert conflito.status_code == 409


def test_agente_nao_cadastra_nem_lista_webhook(sistema):
    empresa = sistema.empresas[0]
    h = {"X-Chave-API": empresa.chave, "Idempotency-Key": "agente-nao-administra"}
    assert sistema.cl.post("/webhooks", json={"url": "https://eventos.example.com/raiz"}, headers=h).status_code == 403
    assert sistema.cl.get("/webhooks", headers=h).status_code == 403
    assert sistema.cl.get("/webhooks").status_code == 401


def test_empresa_nao_le_nem_desativa_destino_alheio(sistema):
    a, b = sistema.empresas
    criado = sistema.cl.post("/webhooks", json={"url": "https://eventos.example.com/raiz"}, headers=_headers(a)).json()
    assert sistema.cl.get("/webhooks", headers=_headers(b)).json() == {"inscricoes": []}
    assert sistema.cl.delete(f"/webhooks/{criado['id']}", headers=_headers(b)).status_code == 404
    with sistema.eng.begin() as con:
        W.enfileirar(con, a.id, "pedido.atualizado", str(uuid.uuid4()), "pronto")
    for _ in range(2):
        resposta = sistema.cl.delete(f"/webhooks/{criado['id']}", headers=_headers(a))
        assert resposta.status_code == 200 and resposta.json()["ativa"] is False
    with sistema.eng.connect() as con:
        assert (
            con.execute(
                text("SELECT estado FROM negocio.webhook_entrega WHERE inscricao_id=:i"), {"i": criado["id"]}
            ).scalar_one()
            == "cancelada"
        )
    assert (
        W.entregar_proximo(
            sistema.eng, a.id, cofre=pessoal.Cofre(), enviar=lambda *a: pytest.fail("destino desativado")
        )
        is None
    )


def test_url_insegura_nao_vaza_segredo_e_cofre_ausente_fecha_cadastro(sistema, monkeypatch):
    empresa = sistema.empresas[0]
    resposta = sistema.cl.post(
        "/webhooks", json={"url": "https://eventos.example.com/raiz?token=segredo"}, headers=_headers(empresa)
    )
    assert resposta.status_code == 422 and "token=segredo" not in resposta.text
    monkeypatch.setattr(pessoal, "config", lambda: SimpleNamespace(chave_pessoal=None))
    resposta = sistema.cl.post("/webhooks", json={"url": "https://eventos.example.com/raiz"}, headers=_headers(empresa))
    assert resposta.status_code == 503
