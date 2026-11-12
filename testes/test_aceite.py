"""Fluxo completo do aceite: WhatsApp -> grafo (LangGraph com checkpointer cifrado no Postgres) -> mensagens que
esperam aprovação. Modelos falsos com roteiro; nenhuma chamada de API de verdade."""

import datetime as dt
import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from raiz.agentes import aceite
from raiz.agentes.memoria import checkpointer, preparar
from raiz.carga import carregar_pasta
from raiz.modelos.base import Resposta
from raiz.modelos.cascata import Cascata
from raiz.pessoal import Cofre, gerar_chave
from raiz.whatsapp import aprovar, enviar_aprovadas, receber
from testes.conftest import AMOSTRA

pytestmark = pytest.mark.banco
CHAVE = gerar_chave()
COFRE = Cofre(CHAVE)
PROPOSTA = {"area_ha": 12.5, "prazo_anos": 30, "pagamento": "R$ 300 por hectare por ano, todo mês de março"}


class Roteiro:
    """Modelo falso: responde pela tarefa e por palavras da mensagem do dono."""

    provedor = "teste"

    def __init__(self, nome):
        self.nome = nome

    def responder_json(self, pedido):
        m = pedido.mensagem.lower()
        if pedido.tarefa == "aceite.intencao":
            intencao = "duvida" if "?" in m else ("recusa" if "não" in m or "nao" in m else "aceita")
            dados = {"intencao": intencao}
        else:
            dados = {
                "entendeu_area": "hectare" in m,
                "entendeu_prazo": "30 anos" in m,
                "entendeu_pagamento": "300" in m,
                "desistiu": "desisto" in m,
            }
        return Resposta(dados, self.nome, self.provedor, custo_fonte="teste")


@pytest.fixture
def ambiente(banco_url):
    eng = create_engine(banco_url)
    with eng.begin() as c:
        c.execute(
            text(
                "truncate funil.rodada, funil.imovel, pessoal.contato, negocio.aceite, "
                "operacao.fila_revisao, operacao.decisao_cascata, operacao.chamada_modelo cascade"
            )
        )
    carregar_pasta(eng, AMOSTRA, dt.date(2026, 11, 12), congelar=False)
    preparar(banco_url, CHAVE)
    with checkpointer(banco_url, CHAVE) as cp:
        grafo = aceite.construir(cp)
        deps = aceite.Dependencias(eng, Cascata(Roteiro("A"), Roteiro("B"), Roteiro("C")))
        yield eng, grafo, deps
    eng.dispose()


def _imoveis(eng, n=2):
    with eng.connect() as c:
        return (
            c.execute(
                text(
                    "select cod_imovel from funil.resultado_vigente where frente = 'carbono' "
                    "order by cod_imovel limit :n"
                ),
                {"n": n},
            )
            .scalars()
            .all()
        )


def _contato(eng, bsuid, wa_id=None):
    from raiz.pessoal import registrar_contato_whatsapp

    with eng.begin() as c:
        return registrar_contato_whatsapp(c, bsuid, wa_id, cofre=COFRE)


def _ultima(eng, cod, tipo):
    with eng.connect() as c:
        return c.execute(
            text(
                "select texto from pessoal.mensagem_saida where cod_imovel = :c and tipo = :t order by id desc limit 1"
            ),
            {"c": cod, "t": tipo},
        ).scalar()


def _aceite(eng, cod):
    with eng.connect() as c:
        return c.execute(text("select estado, etapa from negocio.aceite where cod_imovel = :c"), {"c": cod}).one()


def test_aceite_completo_pelo_whatsapp(ambiente):
    eng, grafo, deps = ambiente
    cod = _imoveis(eng)[0]
    ct = _contato(eng, "BR.dono1")
    aceite.iniciar(grafo, deps, cod, ct)
    assert aceite.pausa(grafo, cod, deps)["etapa"] == "convite"
    assert "hectares" in _ultima(eng, cod, "convite")

    # dono responde pelo WhatsApp (agora com telefone): o contato ganha o telefone e a conversa anda
    r = receber(eng, grafo, deps, "BR.dono1", "5591988887777", "Sim, quero saber mais", cofre=COFRE)
    assert r["acao"] == "retomada"
    assert aceite.pausa(grafo, cod, deps)["etapa"] == "aguardando_proposta"
    # enquanto espera a proposta, mensagem do dono vai para revisão (não retoma)
    assert receber(eng, grafo, deps, "BR.dono1", None, "e aí?", cofre=COFRE)["acao"] == "revisao"

    aceite.enviar_proposta(grafo, deps, cod, PROPOSTA)
    assert "30 anos" in _ultima(eng, cod, "proposta")
    receber(eng, grafo, deps, "BR.dono1", None, "são 12 hectares e pagam 300 por ano", cofre=COFRE)
    assert "prazo é de 30 anos" in _ultima(eng, cod, "reexplicacao")  # faltou o prazo: reexplica só o prazo
    receber(eng, grafo, deps, "BR.dono1", None, "12 hectares, 30 anos, 300 por hectare", cofre=COFRE)
    assert aceite.pausa(grafo, cod, deps)["etapa"] == "codigo"
    codigo = re.search(r"\d{6}", _ultima(eng, cod, "codigo")).group(0)

    receber(eng, grafo, deps, "BR.dono1", None, "111111" if codigo != "111111" else "222222", cofre=COFRE)
    assert _ultima(eng, cod, "codigo_errado") and aceite.pausa(grafo, cod, deps)["etapa"] == "codigo"
    receber(eng, grafo, deps, "BR.dono1", None, f"meu código é {codigo}", cofre=COFRE)
    assert aceite.pausa(grafo, cod, deps) is None
    assert tuple(_aceite(eng, cod)) == ("aceito", "aceito")
    with eng.connect() as c:
        assert c.execute(
            text("select consentimento_em is not null from pessoal.contato where id = :i"), {"i": ct}
        ).scalar()
        assert (
            c.execute(
                text("select valor_texto from aprendizado.gabarito where cod_imovel = :c and alvo = 'aceite_dono'"),
                {"c": cod},
            ).scalar()
            == "sim"
        )
        # conversa cifrada no esquema pessoal: nada do que o dono escreveu aparece em claro
        assert c.execute(text("select count(*) from pessoal.checkpoint_writes")).scalar() > 0
        claro = c.execute(
            text("select count(*) from pessoal.checkpoint_writes where encode(blob, 'escape') like '%quero saber%'")
        ).scalar()
        assert claro == 0
        # nenhuma mensagem saiu sem aprovação
        assert (
            c.execute(
                text("select count(*) from pessoal.mensagem_saida where estado <> 'aguardando_aprovacao'")
            ).scalar()
            == 0
        )


def test_recusa_e_duvida(ambiente):
    eng, grafo, deps = ambiente
    cod = _imoveis(eng)[1]
    ct = _contato(eng, "BR.dono2", "5594977776666")
    aceite.iniciar(grafo, deps, cod, ct, PROPOSTA)
    receber(eng, grafo, deps, "BR.dono2", None, "quanto tempo dura?", cofre=COFRE)
    assert aceite.pausa(grafo, cod, deps)["etapa"] == "convite"  # dúvida: fila de revisão e segue esperando
    with eng.connect() as c:
        assert (
            c.execute(
                text(
                    "select count(*) from operacao.fila_revisao where chave = :c and motivo like "
                    "'dono fez uma pergunta%'"
                ),
                {"c": cod},
            ).scalar()
            == 1
        )
    receber(eng, grafo, deps, "BR.dono2", None, "não, obrigado", cofre=COFRE)
    assert tuple(_aceite(eng, cod)) == ("recusado", "recusado")
    # mensagem depois de encerrado: revisão, não quebra
    assert receber(eng, grafo, deps, "BR.dono2", None, "oi", cofre=COFRE)["acao"] == "revisao"


def test_envio_so_do_aprovado_para_o_bsuid(ambiente):
    eng, grafo, deps = ambiente
    cod = _imoveis(eng)[0]
    ct = _contato(eng, "BR.dono3", "5591911112222")
    aceite.iniciar(grafo, deps, cod, ct)
    with eng.connect() as c:
        mid = c.execute(text("select id from pessoal.mensagem_saida where cod_imovel = :c"), {"c": cod}).scalar()
    enviados = []
    assert enviar_aprovadas(eng, lambda d, t: enviados.append((d, t)) or "wamid.1", COFRE) == 0
    aprovar(eng, mid, "fundador")
    assert enviar_aprovadas(eng, lambda d, t: enviados.append((d, t)) or "wamid.1", COFRE) == 1
    assert enviados[0][0] == "BR.dono3"  # prioridade do PyWa: BSUID antes do telefone
    with pytest.raises(ValueError):
        aprovar(eng, mid, "fundador")


def test_api(ambiente, monkeypatch):
    from raiz import api

    eng, grafo, deps = ambiente
    monkeypatch.setattr(api, "config", lambda: SimpleNamespace(api_token=SecretStr("segredo")))
    cli = TestClient(api.criar_app(eng, grafo, deps, whatsapp=False))
    h = {"Authorization": "Bearer segredo"}
    assert cli.get("/saude").json() == {"ok": True}
    assert cli.get("/mensagens/pendentes").status_code == 401
    cod = _imoveis(eng)[0]
    ct = _contato(eng, "BR.dono4")
    r = cli.post(f"/aceites/{cod}/iniciar", json={"contato_id": ct}, headers=h)
    assert r.status_code == 200 and r.json()["esperando"]["etapa"] == "convite"
    assert cli.post(f"/aceites/{cod}/iniciar", json={"contato_id": ct}, headers=h).status_code == 409
    assert cli.post(f"/aceites/{cod}/proposta", json=PROPOSTA, headers=h).status_code == 409  # ainda no convite
    r = cli.post(f"/aceites/{cod}/responder", json={"texto": "sim"}, headers=h)
    assert r.json()["esperando"]["etapa"] == "aguardando_proposta"
    assert cli.post(f"/aceites/{cod}/proposta", json=PROPOSTA, headers=h).json()["esperando"]["etapa"] == "explicacao"
    pend = cli.get("/mensagens/pendentes", headers=h).json()
    assert {m["tipo"] for m in pend} >= {"convite", "proposta"}
    assert cli.post(f"/mensagens/{pend[0]['id']}/aprovar", json={"quem": "fundador"}, headers=h).json()["enviadas"] == 0
    rev = cli.get("/revisoes", headers=h).json()
    assert (
        rev
        and cli.post(
            f"/revisoes/{rev[0]['id']}/resolver", json={"quem": "fundador", "resposta": {"ok": 1}}, headers=h
        ).status_code
        == 200
    )


def test_webhook_pywa_entrega_bsuid(ambiente, monkeypatch):
    """Payload no formato da Cloud API, assinado com o app secret, passa pela rota que o PyWa registra."""
    import hashlib
    import hmac
    import json
    import time

    from raiz import api, whatsapp

    eng, grafo, deps = ambiente
    cfg = SimpleNamespace(
        whatsapp_phone_id="123456",
        whatsapp_token=SecretStr("tok"),
        whatsapp_verify_token=SecretStr("verifica"),
        whatsapp_app_secret=SecretStr("app-secret"),
        api_token=SecretStr("segredo"),
    )
    monkeypatch.setattr(whatsapp, "config", lambda: cfg)
    monkeypatch.setattr(api, "config", lambda: cfg)
    recebidos = []
    monkeypatch.setattr(whatsapp, "receber", lambda *a, **k: recebidos.append((a, k)))
    cli = TestClient(api.criar_app(eng, grafo, deps, whatsapp=True))

    # verificação do webhook pela Meta
    r = cli.get("/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "verifica", "hub.challenge": "42"})
    assert r.status_code == 200 and r.text == "42"

    corpo = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "999",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {"display_phone_number": "5511900000000", "phone_number_id": "123456"},
                                "contacts": [
                                    {"profile": {"name": "Dono"}, "wa_id": "5591988887777", "user_id": "BR.13579"}
                                ],
                                "messages": [
                                    {
                                        "from": "5591988887777",
                                        "from_user_id": "BR.13579",
                                        "id": "wamid.ABC",
                                        "timestamp": str(int(time.time())),
                                        "type": "text",
                                        "text": {"body": "Sim, quero"},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }
    )
    assin = "sha256=" + hmac.new(b"app-secret", corpo.encode(), hashlib.sha256).hexdigest()
    r = cli.post("/whatsapp", content=corpo, headers={"Content-Type": "application/json", "X-Hub-Signature-256": assin})
    assert r.status_code == 200
    assert len(recebidos) == 1
    args = recebidos[0][0]
    assert args[3:6] == ("BR.13579", "5591988887777", "Sim, quero")
    # assinatura errada é rejeitada
    r = cli.post(
        "/whatsapp", content=corpo, headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=00"}
    )
    assert r.status_code in (401, 403)
