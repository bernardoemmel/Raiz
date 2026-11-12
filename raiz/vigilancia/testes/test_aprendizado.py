"""Aprendizado: marcação humana vale sobre a automática, a confiança aprende com as marcações, a marcação automática
usa imagem nova e fonte oficial, e o acerto sai por versão da regra."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from raiz.vigilancia import aprendizado, cruzamento
from raiz.vigilancia.testes.conftest import (
    COD_A,
    CPF,
    CPF_MASCARADO,
    HOJE,
    fmt_cpf,
    ocorrencia,
    ocorrencias,
    quadrado_m,
)


def _alertas(oc, poligonos, regras, hoje=HOJE):
    return cruzamento.montar_alertas(oc, cruzamento.cruzar_imoveis(oc, poligonos), regras, hoje)


def test_marcacao_valida_fonte_e_mascara():
    with pytest.raises(ValueError):
        aprendizado.marcacao("a1", True, "palpite", "fundador")
    m = aprendizado.marcacao("a1", False, "campo", "Fundador", f"visita; CPF {fmt_cpf(CPF)} no portão")
    assert m["quem"] == "fundador" and fmt_cpf(CPF) not in m["evidencia"] and CPF_MASCARADO in m["evidencia"]


def test_humana_vale_sobre_automatica_mesmo_mais_velha():
    t0 = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
    humana = aprendizado.marcacao("a1", False, "campo", "fundador", agora=t0)
    auto = aprendizado.marcacao("a1", True, "imagem_nova", "automatico", agora=t0 + dt.timedelta(days=5))
    v = aprendizado.vigentes(pd.DataFrame([humana, auto]))
    assert len(v) == 1 and not v.iloc[0]["verdadeiro"] and v.iloc[0]["fonte"] == "campo"


def test_confianca_aprende_com_as_marcacoes(regras):
    a = pd.DataFrame({"alerta_id": [f"a{i}" for i in range(10)], "estrato": ["firms_nominal"] * 10})
    marcas = [aprendizado.marcacao(f"a{i}", i < 2, "campo", "fundador") for i in range(10)]
    cont = aprendizado.contagem(a, pd.DataFrame(marcas))
    assert cont == {"firms_nominal": (2, 8)}
    # prior 6/10 (60%); com 2 verdadeiros e 8 falsos: (6+2)/(10+10) = 40%
    assert aprendizado.confianca(regras, "firms_nominal", cont) == 0.4
    assert aprendizado.confianca(regras, "firms_nominal") == 0.6


def test_acerto_por_versao_com_brier():
    a = pd.DataFrame(
        {
            "alerta_id": ["a1", "a2", "a3"],
            "fonte": ["deter"] * 3,
            "estrato": ["deter_desmatamento"] * 3,
            "regra_versao": ["v1", "v1", "v2"],
            "confianca": [0.8, 0.8, 0.9],
        }
    )
    m = pd.DataFrame(
        [
            aprendizado.marcacao("a1", True, "campo", "fundador"),
            aprendizado.marcacao("a2", False, "cliente", "cliente"),
            aprendizado.marcacao("a3", True, "imagem_nova", "automatico"),
        ]
    )
    ac = {x["regra_versao"]: x for x in aprendizado.acerto(a, m)}
    assert ac["v1"]["marcados"] == 2 and ac["v1"]["precisao"] == 0.5
    assert ac["v1"]["brier"] == round(((0.8 - 1) ** 2 + (0.8 - 0) ** 2) / 2, 4)
    assert ac["v1"]["por_fonte_marcacao"] == {"campo": 1, "cliente": 1}
    assert ac["v2"]["precisao"] == 1.0


def test_deter_confirmado_pelo_prodes(poligonos, regras):
    oc = ocorrencias(
        ocorrencia("deter", "d1", "desmatamento_cr", quadrado_m(100, 100, 300), dt.date(2026, 6, 1)),
        ocorrencia("prodes", "p1", "desmatamento", quadrado_m(150, 150, 300), dt.date(2026, 7, 20)),
    )
    a = _alertas(oc, poligonos, regras)
    novas = aprendizado.marcar_automatico(a, None, regras, HOJE)
    assert len(novas) == 1
    m = novas[0]
    d1 = a[(a.chave == "d1")].iloc[0]
    assert m["alerta_id"] == d1["alerta_id"] and m["verdadeiro"] and m["fonte"] == "imagem_nova"
    assert m["quem"] == "automatico" and m["regra_versao"] == regras.versao
    # rodar de novo não marca de novo
    assert aprendizado.marcar_automatico(a, pd.DataFrame(novas), regras, HOJE) == []


def test_deter_grande_sem_prodes_do_ano_lido_vira_falso(poligonos, regras):
    # 300 m x 300 m = 9 ha (acima da área mínima do PRODES), imagem de 2026-03 -> PRODES 2026
    oc = ocorrencias(ocorrencia("deter", "d1", "desmatamento_cr", quadrado_m(100, 100, 300), dt.date(2026, 3, 1)))
    a = _alertas(oc, poligonos, regras)
    assert aprendizado.marcar_automatico(a, None, regras, HOJE, prodes_lidos={"x": {"PA": [2025]}}) == []
    novas = aprendizado.marcar_automatico(a, None, regras, HOJE, prodes_lidos={"x": {"PA": [2026]}})
    assert len(novas) == 1 and not novas[0]["verdadeiro"] and "PRODES 2026" in novas[0]["evidencia"]


def test_deter_pequeno_nao_vira_falso_sem_prodes(poligonos, regras):
    oc = ocorrencias(ocorrencia("deter", "d1", "desmatamento_cr", quadrado_m(100, 100, 100), dt.date(2026, 3, 1)))
    a = _alertas(oc, poligonos, regras)  # 1 ha: o PRODES pode não mapear
    assert aprendizado.marcar_automatico(a, None, regras, HOJE, prodes_lidos={"x": {"PA": [2026]}}) == []


def test_fogo_confirmado_por_cicatriz(poligonos, regras):
    oc = ocorrencias(
        ocorrencia("firms", "N20|2026-09-01|1700|0|0", "foco_alta", quadrado_m(400, 400, 375), dt.date(2026, 9, 1)),
        ocorrencia("deter", "c1", "cicatriz_de_queimada", quadrado_m(350, 350, 500), dt.date(2026, 9, 20)),
    )
    a = _alertas(oc, poligonos, regras)
    novas = aprendizado.marcar_automatico(a, None, regras, HOJE)
    f = a[a.fonte == "firms"].iloc[0]
    assert [n["alerta_id"] for n in novas] == [f["alerta_id"]] and novas[0]["verdadeiro"]


def test_embargo_cancelado_e_mapbiomas_rejeitado(poligonos, regras):
    oc = ocorrencias(
        ocorrencia("ibama_embargo", "555", "embargo", quadrado_m(100, 100, 100), dt.date(2026, 1, 1)),
        ocorrencia("mapbiomas_alerta", "888", "agriculture", quadrado_m(500, 500, 100), dt.date(2026, 9, 1)),
    )
    a = _alertas(oc, poligonos, regras)
    novas = aprendizado.marcar_automatico(
        a, None, regras, HOJE, ibama_cancelados={"555"}, mapbiomas_status={"888": "Rejeitado"}
    )
    assert len(novas) == 2 and all(not n["verdadeiro"] and n["fonte"] == "fonte_oficial" for n in novas)


def test_exportar_para_o_aprendizado_do_back_end(poligonos, regras):
    oc = ocorrencias(ocorrencia("deter", "d1", "desmatamento_cr", quadrado_m(100, 100, 300), HOJE))
    a = _alertas(oc, poligonos, regras)
    m = pd.DataFrame([aprendizado.marcacao(a.iloc[0]["alerta_id"], True, "campo", "fundador")])
    prev, gab = aprendizado.exportar(a, m)
    assert prev[0]["cod_imovel"] == COD_A and prev[0]["modelo_versao"] == regras.versao
    assert prev[0]["alvo"] == "vigilancia_desmatamento" and 0 < prev[0]["valor_num"] < 1
    assert gab[0]["valor_num"] == 1.0 and gab[0]["fonte"] == "campo"
