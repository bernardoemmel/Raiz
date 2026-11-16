"""Quantis, deduplicação e exclusão explícita de fatias e marcas sem medição."""

import copy
import json

import pytest

from raiz.executor.tempos import estatistica, medir


def controle():
    return {
        "estado": {
            "uf": "DF",
            "versoes": {"funil": "v1"},
            "situacao": "pronto",
            "total": 1,
            "feitos": 1,
            "rodados": 1,
            "erros": [],
            "inicio": "2026-11-01T00:00:00+00:00",
            "fim": "2026-11-01T00:00:10+00:00",
        },
        "marcas": {
            "5300108": {"tarefas": {"funil": {"versao": "v1", "segundos": 8.5, "data": "2026-11-01T00:00:09+00:00"}}}
        },
    }


def test_quantis_lineares_e_amostra_unica():
    assert estatistica([]) == {"amostras": 0, "mediana_s": None, "p95_s": None}
    assert estatistica([10]) == {"amostras": 1, "mediana_s": 10, "p95_s": 10}
    assert estatistica([40, 10, 30, 20]) == {"amostras": 4, "mediana_s": 25, "p95_s": 38.5}


def test_mesmo_snapshot_nao_duplica_e_so_divulga_agregados():
    r = medir([controle(), controle()])
    g = r["grupos"][0]
    assert g["municipio_soma_tarefas"] == {"amostras": 1, "mediana_s": 8.5, "p95_s": 8.5}
    assert g["estado_inteiro"] == {"amostras": 1, "mediana_s": 10, "p95_s": 10}
    assert "5300108" not in json.dumps(r)
    novo = controle()
    novo["estado"]["versoes"]["funil"] = "v2"
    assert len(medir([controle(), novo])["grupos"]) == 2


@pytest.mark.parametrize(
    "mudanca",
    [
        {"segundos": None},
        {"segundos": -1},
        {"segundos": float("nan")},
        {"segundos": True},
        {"erro": "falhou"},
        {"adotado": True},
        {"versao": "v0"},
    ],
)
def test_marcas_sem_medicao_propria_completa_nao_sao_zero(mudanca):
    c = controle()
    c["marcas"]["5300108"]["tarefas"]["funil"].update(mudanca)
    g = medir([c])["grupos"][0]
    assert g["municipio_soma_tarefas"]["amostras"] == 0
    assert g["municipios_excluidos"] == 1
    assert g["estado_inteiro"]["amostras"] == 0
    assert g["estado_rodada_sem_medicao_integral"]["amostras"] == 1


@pytest.mark.parametrize(
    "mudanca", [{"uf": "RR"}, {"rodados": 0}, {"situacao": "com_erro"}, {"erros": [{"cod": 5300108}]}, {"fim": None}]
)
def test_fatia_retomada_sem_calculo_e_falhas_nao_sao_tempo_de_estado_inteiro(mudanca):
    c = controle()
    c["estado"].update(mudanca)
    assert medir([c])["grupos"][0]["estado_inteiro"]["amostras"] == 0


def test_registro_recente_substitui_medicao_municipal_sem_somar_repeticoes():
    antigo = controle()
    novo = copy.deepcopy(antigo)
    novo["marcas"]["5300108"]["tarefas"]["funil"].update(segundos=2.5, data="2026-11-02T00:00:00+00:00")
    for entradas in ([antigo, novo], [novo, antigo]):
        g = medir(entradas)["grupos"][0]
        assert g["municipio_soma_tarefas"] == {"amostras": 1, "mediana_s": 2.5, "p95_s": 2.5}
