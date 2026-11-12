"""O site só recebe notas de grupos observados; nenhum identificador de imóvel."""

import datetime as dt
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raiz.aprendizado import painel as P

AGORA = dt.datetime(2026, 11, 12, tzinfo=dt.UTC)


def linhas(n=5, **alteracoes):
    return [
        {
            "modelo": "motor",
            "tipo": "ao_vivo",
            "modelo_versao": "v1",
            "alvo": "area_ha",
            "horizonte_dias": 365,
            "cod_imovel": f"IMOVEL-INTERNO-{i}",
            "data_corte": "2025-01-01",
            "horizonte_em": "2026-01-01",
            "observado_em": "2026-01-02",
            "gabarito_id": i + 1,
            "gabarito_fonte": "Fonte interna",
            "valor_num": 10,
            "real_num": 10 + i,
            "nome": "NAO PUBLICAR",
            **alteracoes,
        }
        for i in range(n)
    ]


def test_notas_reais_fonte_data_e_allowlist():
    r = P.resumir(linhas(), AGORA)
    v = r["versoes"][0]
    assert v["metricas"] == {"ae": 2.0, "eq": 6.0}
    assert v["comparacoes"] == v["imoveis_observados"] == 5
    assert v["ultima_observacao"] == "2026-01-02"
    assert r["gerado_em"] == AGORA.isoformat()
    publicado = json.dumps(r)
    for privado in ["cod_imovel", "IMOVEL-INTERNO", "NAO PUBLICAR", "Fonte interna", "real_num", "gabarito_id"]:
        assert privado not in publicado


def test_zero_medido_permanece_zero_e_ausencia_nao_gera_nota():
    assert P.resumir(linhas(real_num=10), AGORA)["versoes"][0]["metricas"]["ae"] == 0
    assert P.resumir(linhas(real_num=None), AGORA)["versoes"] == []
    assert P.resumir([], AGORA)["versoes"] == []


def test_minimo_exige_imoveis_distintos_nao_previsoes_repetidas():
    assert P.resumir(linhas(4), AGORA)["versoes"] == []
    assert P.resumir(linhas(8, cod_imovel="MESMO-IMOVEL"), AGORA)["versoes"] == []
    assert P.resumir(linhas() * 2, AGORA)["versoes"][0]["comparacoes"] == 10


@pytest.mark.parametrize(
    "mudanca",
    [
        {"horizonte_em": "2027-01-01"},
        {"observado_em": "2027-01-01"},
        {"observado_em": "2025-01-01"},
        {"gabarito_fonte": None},
        {"gabarito_id": None},
        {"modelo": "texto livre"},
        {"real_num": float("nan")},
        {"p10": 20, "p50": 10, "p90": 30},
    ],
)
def test_nao_divulga_resultado_prematuro_ou_sem_proveniencia(mudanca):
    assert P.resumir(linhas(**mudanca), AGORA)["versoes"] == []


def test_separa_versoes_horizontes_e_tipos():
    pares = linhas() + linhas(modelo_versao="v2") + linhas(horizonte_dias=30)
    assert len(P.resumir(pares, AGORA)["versoes"]) == 3
    # Cinco casos somados entre horizontes distintos não liberam um grupo pequeno.
    assert P.resumir(linhas(3) + linhas(2, horizonte_dias=30), AGORA)["versoes"] == []


def test_rota_publica_recebe_somente_projecao(monkeypatch):
    monkeypatch.setattr(P, "ler", lambda _: P.resumir(linhas(), AGORA))
    app = FastAPI()
    app.include_router(P.roteador(lambda _: None))
    resposta = TestClient(app).get("/acerto/resumo")
    assert resposta.status_code == 200
    assert resposta.json()["versoes"][0]["comparacoes"] == 5
    assert "IMOVEL-INTERNO" not in resposta.text


def test_reexecucao_retrospectiva_nunca_mistura_com_previsao_ao_vivo():
    r = P.resumir(linhas() + linhas(tipo="backtest"), AGORA)
    assert {v["avaliacao"] for v in r["versoes"]} == {"ao_vivo", "backtest"}
    assert all(v["comparacoes"] == 5 for v in r["versoes"])
    assert P.resumir(linhas(tipo=None), AGORA)["versoes"] == []


@pytest.mark.banco
def test_consulta_real_separa_backtest_e_preserva_minimo(banco_url):
    from sqlalchemy import create_engine

    from raiz.aprendizado.registro import Previsao, Versoes, registrar_gabarito, registrar_lote

    engine = create_engine(banco_url)
    try:
        with engine.begin() as con:
            for tipo in ("ao_vivo", "backtest"):
                registrar_lote(
                    con,
                    [Previsao(f"PA-1504950-PAINEL{i}", "area_ha", 365, valor_num=10) for i in range(5)],
                    Versoes("painel_acerto_teste", "v1", "fixture", dt.date(2024, 1, 1), tipo=tipo),
                )
            for i in range(5):
                registrar_gabarito(con, f"PA-1504950-PAINEL{i}", "area_ha", dt.date(2025, 1, 1), "campo", 10 + i)
        r = P.ler(engine)
        grupos = [v for v in r["versoes"] if v["modelo"] == "painel_acerto_teste"]
        assert len(grupos) == 2
        assert {v["avaliacao"] for v in grupos} == {"ao_vivo", "backtest"}
        assert all(v["metricas"] == {"ae": 2, "eq": 6} for v in grupos)
        assert all(v["comparacoes"] == v["imoveis_observados"] == 5 for v in grupos)
    finally:
        engine.dispose()
