"""Sem segredo e assinatura válidos, ou em teste, nenhum crédito pago é liberado."""

import base64
import datetime as dt
import hashlib
import hmac
import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from raiz import prospeccao_acesso as acesso
from raiz import prospeccao_webhook as webhook
from raiz.pedidos import pix
from raiz.pedidos.servico import criar_cliente

SEGREDO = "segredo-local-so-para-testes-de-assinatura"
CHAVE_PUBLICA = "chave-publica-local-de-teste"


def cabecalhos(corpo):
    assinatura = base64.b64encode(hmac.digest(CHAVE_PUBLICA.encode(), corpo, hashlib.sha256)).decode()
    return {"X-Webhook-Secret": SEGREDO, "X-Webhook-Signature": assinatura, "Content-Type": "application/json"}


@pytest.fixture
def configuracao(monkeypatch):
    monkeypatch.setenv("RAIZ_ABACATEPAY_WEBHOOK_SEGREDO", SEGREDO)
    monkeypatch.setenv("RAIZ_ABACATEPAY_WEBHOOK_CHAVE_PUBLICA", CHAVE_PUBLICA)


def test_assinatura_depende_dos_bytes_e_do_segredo(configuracao, monkeypatch):
    corpo = b'{"event": "billing.paid"}'
    assinatura = cabecalhos(corpo)["X-Webhook-Signature"]
    assert webhook.verificar_assinatura(corpo, SEGREDO, assinatura)
    assert not webhook.verificar_assinatura(corpo + b" ", SEGREDO, assinatura)
    assert not webhook.verificar_assinatura(corpo, "incorreto", assinatura)
    assert not webhook.verificar_assinatura(corpo, SEGREDO, "incorreta")
    monkeypatch.delenv("RAIZ_ABACATEPAY_WEBHOOK_CHAVE_PUBLICA")
    assert not webhook.verificar_assinatura(corpo, SEGREDO, assinatura)


def test_pix_em_teste_mesmo_com_chave_nao_consulta_provedor(monkeypatch):
    monkeypatch.delenv("RAIZ_PIX_MODO", raising=False)
    monkeypatch.setenv("RAIZ_ABACATEPAY_CHAVE", "chave-presente-sem-ativacao")

    class Proibido:
        def post(self, *args, **kwargs):
            pytest.fail("O modo teste não pode criar uma cobrança real.")

        def get(self, *args, **kwargs):
            pytest.fail("O modo teste não consulta pagamento de produção.")

    cobranca = pix.criar(1, "Teste", 3600, cliente=Proibido(), chave_idempotencia="teste-local-1")
    repetida = pix.criar(1, "Teste", 3600, cliente=Proibido(), chave_idempotencia="teste-local-1")
    assert cobranca.modo == "teste" and cobranca.externo_id.startswith("teste_")
    assert repetida.externo_id == cobranca.externo_id
    assert pix.conferir("identificador-de-producao", cliente=Proibido()) == "pendente"
    assert not pix.producao_habilitada()


@pytest.mark.parametrize("devmode", [None, True, "false"])
def test_resposta_sem_confirmacao_explicita_de_producao_continua_teste(monkeypatch, devmode):
    monkeypatch.setenv("RAIZ_PIX_MODO", "producao")
    monkeypatch.setenv("RAIZ_ABACATEPAY_CHAVE", "chave-local")

    class Resposta:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": {"id": "pix_exemplo", "brCode": "pix-unitario", "devMode": devmode}}

    class Provedor:
        def post(self, *args, **kwargs):
            return Resposta()

    assert pix.criar(1, "Teste", 3600, cliente=Provedor()).modo == "teste"


def test_webhook_invalido_ou_em_teste_nao_chega_ao_banco(configuracao, monkeypatch):
    def proibido(_request):
        pytest.fail("Um evento inválido ou de teste não pode chegar ao banco.")

    app = FastAPI()
    app.include_router(webhook.roteador(proibido))
    corpo = json.dumps({"event": "billing.paid", "data": {"id": "pix_teste"}}).encode()
    rota = "/pagamentos/prospeccao/abacatepay"
    with TestClient(app) as cliente:
        assert cliente.post(rota, content=corpo).status_code == 401
        assert cliente.post(rota, content=corpo + b" ", headers=cabecalhos(corpo)).status_code == 401
        invalido = b"nao-e-json"
        assert cliente.post(rota, content=invalido, headers=cabecalhos(invalido)).status_code == 400
        monkeypatch.setenv("RAIZ_PIX_MODO", "teste")
        assert cliente.post(rota, content=corpo, headers=cabecalhos(corpo)).json()["ignorado"]
        monkeypatch.setenv("RAIZ_PIX_MODO", "producao")
        monkeypatch.setenv("RAIZ_ABACATEPAY_CHAVE", "chave-de-teste")
        simulado = json.dumps({"event": "billing.paid", "devMode": True, "data": {"id": "pix_teste"}}).encode()
        assert cliente.post(rota, content=simulado, headers=cabecalhos(simulado)).json()["ignorado"]
        grande = b"x" * (webhook.MAX_CORPO + 1)
        assert cliente.post(rota, content=grande, headers=cabecalhos(grande)).status_code == 413


@pytest.mark.banco
def test_webhook_reconfere_provedor_e_credita_apenas_uma_vez(banco_url, configuracao, monkeypatch):
    monkeypatch.setenv("RAIZ_PIX_MODO", "producao")
    monkeypatch.setenv("RAIZ_ABACATEPAY_CHAVE", "chave-local")
    monkeypatch.setenv(
        "RAIZ_PROSPECCAO_PLANOS",
        json.dumps(
            {
                "versao": "teste",
                "status": "aprovado",
                "aprovado_em": "2026-11-12",
                "planos": [{"id": "avulsa", "nome": "Avulsa", "creditos": 1, "valor_rs": 1}],
            }
        ),
    )
    ident = f"pix_{uuid.uuid4()}"
    monkeypatch.setattr(
        pix,
        "criar",
        lambda *_: pix.Cobranca(ident, "producao", 1, "pix-unitario", dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)),
    )
    monkeypatch.setattr(pix, "conferir", lambda _ident: "pendente")
    engine = create_engine(banco_url)
    try:
        cid = criar_cliente(engine, "Comprador do teste")[0]
        acesso.iniciar_compra(engine, cid, "avulsa", str(uuid.uuid4()))
        app = FastAPI()
        app.include_router(webhook.roteador(lambda _: engine))
        corpo = json.dumps(
            {
                "event": "billing.paid",
                "devMode": False,
                "data": {"id": ident, "cliente_id": -1, "creditos": 999999, "estado": "paga"},
            }
        ).encode()
        rota = "/pagamentos/prospeccao/abacatepay"
        with TestClient(app) as cliente:
            primeira = cliente.post(rota, content=corpo, headers=cabecalhos(corpo))
            assert primeira.status_code == 200 and not primeira.json()["creditado"]
            assert acesso.saldo(engine, cid)["creditos"] == 0
            monkeypatch.setattr(pix, "conferir", lambda _ident: "paga")
            for _ in range(3):
                r = cliente.post(rota, content=corpo, headers=cabecalhos(corpo))
                assert r.status_code == 200 and r.json()["creditado"]
            assert acesso.saldo(engine, cid)["creditos"] == 1
    finally:
        engine.dispose()
