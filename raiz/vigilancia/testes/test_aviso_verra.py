"""O aviso inicial é um rascunho rastreável; gerar não registra o envio."""

import datetime as dt
from email import policy
from email.parser import Parser

import pytest

from raiz.vigilancia import aviso_verra
from raiz.vigilancia.projetos import Projeto

HOJE = dt.date(2026, 11, 12)
PRAZO = dt.date(2026, 11, 15)


def test_urtx_rascunho_para_cliente_nao_inventa_descoberta_ou_area(regras):
    projeto = Projeto("URTX", {"nome_projeto": "URTX"})
    d = aviso_verra.preparar(projeto, "URTX_LE1", regras, HOJE, prazo_informado=PRAZO)
    assert d["prazo"] == "2026-11-15" and d["dias_restantes"] == 3
    assert d["origem_prazo"] == "informado_pelo_operador"
    assert d["enviado"] is False and len(d["pendencias"]) == 3
    assert d["responsavel_pelo_envio"] == "proponente"
    assert d["destino_rascunho"] == "desenvolvedor_cliente"
    assert "a preencher pelo proponente" in d["corpo"]
    assert "2026-10-16" not in d["corpo"]  # a descoberta não é deduzida do prazo
    mensagem = Parser(policy=policy.default).parsestr(aviso_verra.eml(d))
    assert mensagem["To"] == "registry@verra.org" and mensagem["X-Unsent"] == "1"
    assert mensagem["From"] is None and "URTX_LE1" in mensagem.get_content()
    with pytest.raises(ValueError, match="evento indisponível"):
        aviso_verra.preparar(projeto, "URTX_LE1", regras, HOJE)
    with pytest.raises(ValueError, match="não é deste projeto"):
        aviso_verra.preparar(projeto, "OUTRO_LE1", regras, HOJE, prazo_informado=PRAZO)


def test_urtx_prazo_registrado_gera_rota_e_alerta_sem_estado_privado(cfg, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from raiz.operacao import alertas
    from raiz.vigilancia.api import roteador
    from raiz.vigilancia.servico import Vigilancia

    monkeypatch.delenv("RAIZ_PROJETOS_PRIVADO", raising=False)
    v = Vigilancia(cfg)
    monkeypatch.setattr(v, "areas", lambda _pid: (_ for _ in ()).throw(RuntimeError("sem geometria")))
    app = FastAPI()
    app.include_router(roteador(lambda: v))
    cliente = TestClient(app)
    base = "/vigilancia/projeto/URTX/perdas/URTX_LE1"
    d = cliente.get(base + "/aviso-verra").json()
    assert d["prazo"] == "2026-11-15" and d["enviado"] is False
    assert "privado" not in " ".join(d["pendencias"])
    assert cliente.get(base + "/aviso-verra.eml").status_code == 200
    projeto = cliente.get("/vigilancia/projeto/URTX").json()
    assert projeto["perdas"] == []  # o prazo não fabrica uma perda, área ou descoberta
    assert projeto["avisos_verra_informados"][0]["prazo"] == "2026-11-15"
    novos = alertas._vigilancia(v, alertas.politica()["regras"], HOJE)
    aviso = next(a for a in novos if a.chave == "verra_aviso:URTX_LE1")
    assert aviso.gravidade == "critico" and "proponente" in aviso.texto
    assert not len(v.eventos())
    # Confirmação do proponente também encerra o aviso que nasceu só do prazo informado.
    cliente.post(base + "/eventos", json={"tipo": "verra_avisada", "quem": "proponente", "data": "2026-11-13"})
    assert cliente.get(base + "/aviso-verra.eml").status_code == 409
    assert not any(
        a.chave == "verra_aviso:URTX_LE1" for a in alertas._vigilancia(v, alertas.politica()["regras"], HOJE)
    )
