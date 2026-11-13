"""Contagem pública tem fonte municipal, escopo e validade; nunca é estimada por jobs."""

import copy
import datetime as dt
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raiz.executor import processamento_publico as P
from raiz.executor.armazem import ArmazemLocal, por_json
from raiz.executor.painel import _expirar_observacoes, roteador_publico

AGORA = dt.datetime(2026, 11, 13, 1, tzinfo=dt.UTC)


@pytest.fixture
def observacao():
    return {
        "versao": 1,
        "escopo": "unidade",
        "unidade": "PA-1",
        "municipios_total": 12,
        "municipios": {"prontos": 5, "em_execucao": 2, "com_erro": 1, "pendentes": 3, "desconhecidos": 1},
        "observado_em": AGORA.isoformat(),
        "ultima_mudanca_em": (AGORA - dt.timedelta(seconds=10)).isoformat(),
        "valido_ate": (AGORA + dt.timedelta(seconds=120)).isoformat(),
    }


def test_remove_identificadores_e_erros_sem_perder_zero_real(observacao):
    observacao.update(eventos=[{"cod_imovel": "PRIVADO", "erro": "SEGREDO"}], caminho="/privado")
    observacao["municipios"].update(com_erro=0, pendentes=4, identificadores=["PRIVADO"])
    limpo = P.sanitizar_processamento("PA", observacao)
    assert limpo["municipios"]["com_erro"] == 0
    assert limpo["escopo"] == "unidade" and limpo["unidade"] == "PA-1"
    assert set(limpo["municipios"]) == set(P.CONTAGENS)
    assert not any(t in json.dumps(limpo) for t in ("SEGREDO", "PRIVADO", "caminho", "eventos"))


@pytest.mark.parametrize("valor", [-1, 0.5, True, "2", None, float("nan"), 6001])
def test_recusa_contagem_ambigua(observacao, valor):
    observacao["municipios"]["em_execucao"] = valor
    assert P.sanitizar_processamento("PA", observacao) is None


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("escopo", "brasil"),
        ("unidade", "RN-1"),
        ("unidade", "PA/segredo"),
        ("unidade", "PA-0"),
        ("versao", True),
        ("municipios_total", 13),
        ("observado_em", "2026-11-13T01:00:00"),
        ("ultima_mudanca_em", "2026-11-13T01:00:01Z"),
        ("valido_ate", "2026-11-13T01:00:00Z"),
        ("valido_ate", "2026-11-13T02:00:01Z"),
    ],
)
def test_recusa_escopo_ou_tempo_incomprovado(observacao, campo, valor):
    observacao[campo] = valor
    assert P.sanitizar_processamento("PA", observacao) is None


def test_fatia_nao_vira_estado_inteiro(observacao):
    observacao["escopo"] = "uf"
    assert P.sanitizar_processamento("PA", observacao) is None
    observacao["unidade"] = "PA"
    assert P.sanitizar_processamento("PA", observacao)["escopo"] == "uf"


def test_27_estados_sem_inferir_conclusao_de_arquivos_ou_actions():
    dado = P.painel_publico(
        {"PA": {"municipios": 144, "feitos": 144, "total": 144, "situacao": "pronto", "jobs": 5}}, agora=AGORA
    )
    assert len(dado["estados"]) == 27
    for estado in dado["estados"]:
        assert estado["situacao"] == "sem_telemetria"
        assert set(estado["municipios"].values()) == {None}


def test_expiracao_nao_renova_lease_nem_afirma_running(observacao):
    antes = copy.deepcopy(observacao)
    atual = P.estado_publico("PA", observacao, agora=AGORA)
    velho = P.estado_publico("PA", observacao, agora=AGORA + dt.timedelta(seconds=120))
    assert atual["municipios"]["em_execucao"] == 2
    assert velho["municipios"]["em_execucao"] is None
    assert velho["municipios"]["prontos"] == 5
    assert velho["situacao"] == "desatualizado"
    assert velho["ultima_mudanca_em"] == observacao["ultima_mudanca_em"]
    assert observacao == antes


def test_relogio_futuro_nao_atesta_execucao(observacao):
    estado = P.estado_publico("PA", observacao, agora=AGORA - dt.timedelta(minutes=10))
    assert estado["situacao"] == "sem_telemetria"


def test_preserva_tempo_exato_do_lease_sem_truncar_micros(observacao):
    observado = AGORA + dt.timedelta(microseconds=900_000)
    validade = observado + dt.timedelta(seconds=120)
    observacao.update(observado_em=observado.isoformat(), valido_ate=validade.isoformat())
    limpo = P.sanitizar_processamento("PA", observacao)
    assert limpo["observado_em"] == observado.isoformat()
    assert limpo["valido_ate"] == validade.isoformat()
    antes = P.estado_publico("PA", limpo, agora=validade - dt.timedelta(microseconds=1))
    assert antes["situacao"] == "atual" and antes["municipios"]["em_execucao"] == 2


def test_release_consulta_so_manifesto_fresco_sem_baixar_pacotes(observacao):
    class Release:
        def manifesto(self, fresco=False):
            assert fresco is True
            return {"estados": {"PA": {"processamento": observacao}}}

        def ler(self, chave):
            pytest.fail("a API pública não deve baixar controles e pacotes privados")

    assert len(P.ler_painel(Release())["estados"]) == 27


def test_estado_local_sanitizado(tmp_path, observacao, monkeypatch):
    projetar = P.painel_publico
    monkeypatch.setattr(P, "painel_publico", lambda entradas: projetar(entradas, agora=AGORA))
    a = ArmazemLocal(tmp_path)
    por_json(a, "estado/PA.json", {"processamento": observacao, "erros": [{"car": "PRIVADO"}]})
    resultado = P.ler_painel(a)
    assert "PRIVADO" not in json.dumps(resultado)
    assert next(e for e in resultado["estados"] if e["uf"] == "PA")["municipios"]["prontos"] == 5


def test_endpoint_publico_sem_token_cacheia_apenas_resposta_segura(monkeypatch, observacao):
    chamadas = []

    def ler(a):
        chamadas.append(a)
        return P.painel_publico({"PA": {"processamento": observacao}}, agora=AGORA)

    monkeypatch.setattr(P, "ler_painel", ler)
    app = FastAPI()
    app.include_router(roteador_publico(lambda request: "armazem"))
    cliente = TestClient(app)
    for _ in range(2):
        resposta = cliente.get("/processamento/publico")
        assert resposta.status_code == 200
        assert resposta.headers["cache-control"] == "no-store"
        assert len(resposta.json()["estados"]) == 27
    assert chamadas == ["armazem"]


def test_erro_nao_expoe_caminho_token_ou_car(monkeypatch):
    def falhar(a):
        raise RuntimeError("token SEGREDO /caminho/PRIVADO")

    monkeypatch.setattr(P, "ler_painel", falhar)
    app = FastAPI()
    app.include_router(roteador_publico(lambda request: object()))
    resposta = TestClient(app).get("/processamento/publico")
    assert resposta.status_code == 503
    assert resposta.json() == {"erro": "observacao_indisponivel"}


def test_cache_tambem_perde_validade(observacao):
    dado = P.painel_publico({"PA": {"processamento": observacao}}, agora=AGORA)
    pa = next(e for e in dado["estados"] if e["uf"] == "PA")
    pa["valido_ate"] = "2020-01-01T00:00:00Z"
    out = _expirar_observacoes(dado)
    atual = next(e for e in out["estados"] if e["uf"] == "PA")
    assert atual["situacao"] == "desatualizado" and atual["municipios"]["em_execucao"] is None
    assert pa["municipios"]["em_execucao"] == 2  # cache original não é modificado
