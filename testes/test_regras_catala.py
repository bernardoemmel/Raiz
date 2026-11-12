"""Regras em Catala (referência legal) contra o laudo do motor e contra o caminho vetorizado (raiz/regras/federal.py).

Três conferências: o Python gerado está em dia com as fontes .catala_en; os 72 imóveis reais de teste dão o mesmo
laudo; e, em imóveis e faixas sorteados pelo Hypothesis, Catala e federal.py/Parametros nunca discordam.
"""

from pathlib import Path

import pandas as pd
import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from raiz.regras import catala_gerar, federal, parametros, referencia

P = parametros()
CASOS = yaml.safe_load(Path(__file__).parent.joinpath("dados/imoveis_teste/PA.yaml").read_text())["casos"]


def test_gerado_em_dia():
    ok, difs = catala_gerar.em_dia()
    assert ok, f"regras em Catala mudaram sem gerar o Python de novo (rode `raiz regras gerar`): {difs}"


@pytest.mark.parametrize("caso", CASOS, ids=[c["cod_imovel"][-8:] for c in CASOS])
def test_laudo_do_motor(caso):
    r = referencia.laudo(caso["entrada"])
    for k in referencia.SAIDAS_LAUDO:
        assert r[k] == pytest.approx(caso["esperado"][k], abs=1e-5), k


_area = st.floats(0.5, 50_000, allow_nan=False)


@st.composite
def _imovel(draw):
    ha = draw(_area)
    nao_floresta = draw(st.floats(0, 1)) * ha * draw(st.sampled_from([0, 0, 1]))
    floresta = draw(st.floats(0, 1)) * (ha - nao_floresta)
    return {
        "uf": draw(st.sampled_from(["PA", "MT", "TO", "MA", "SP", "PI", "GO", "BA"])),
        "bioma": draw(st.sampled_from(["Amazônia", "Cerrado", "Pantanal", "Mata Atlântica", "Caatinga"])),
        "ha": ha,
        "m_fiscal": draw(st.sampled_from([0.3, 1.0, 1.5, 2.0, 3.0, 4.0, 4.01, 9.0, 10.0, 12.0, 300.0])),
        "nao_floresta_ha": nao_floresta,
        "floresta_rem_ha": floresta,
        "desm_total_ha": (ha - nao_floresta - floresta) * draw(st.floats(0, 1)),
        "app_escadinha_ha": draw(st.floats(0, 1)) * ha * 0.3,
    }


@settings(max_examples=300, deadline=None)
@given(_imovel())
def test_catala_igual_ao_vetorizado(e):
    vet = federal.calcular(pd.DataFrame([e]), P).iloc[0]
    cat = referencia.laudo(e)
    for k in referencia.SAIDAS_LAUDO:
        assert cat[k] == pytest.approx(vet[k], rel=1e-9, abs=1e-6), (k, e)


@settings(max_examples=400, deadline=None)
@given(
    corpo=st.sampled_from(["rio", "nascente", "lago", "vereda"]),
    mf=st.sampled_from([0.5, 1.0, 1.01, 2.0, 2.5, 4.0, 4.01, 8.0, 10.0, 10.5, 50.0]),
    consolidada=st.booleans(),
    largura=st.one_of(st.none(), st.sampled_from([5.0, 10.0, 12.0, 50.0, 120.0, 200.0, 300.0, 600.0, 601.0, 900.0])),
    superficie=st.sampled_from([1.0, 20.0, 20.5, 300.0]),
    urbana=st.booleans(),
)
def test_faixas_de_app_iguais_a_tabela(corpo, mf, consolidada, largura, superficie, urbana):
    urbana = urbana and corpo == "lago" and not consolidada
    cat = referencia.faixa_app_m(corpo, mf, consolidada, largura, superficie, urbana)
    tab = P.faixa_app_m(corpo, mf, consolidada, largura, superficie, urbana)
    assert cat == tab, (corpo, mf, consolidada, largura, superficie, urbana)


def test_fatos_opcionais_mudam_o_devido():
    e = {"uf": "PA", "bioma": "Amazônia", "ha": 1000, "m_fiscal": 10, "floresta_rem_ha": 500, "desm_total_ha": 500}
    base = referencia.reserva_legal(e)
    assert base["deficit_devido_ha"] == pytest.approx(300) and base["percentual_recomposicao"] == pytest.approx(0.8)
    assert referencia.reserva_legal(e, reducao_art12_par4_ou_par5=True)["deficit_devido_ha"] == pytest.approx(0)
    assert referencia.reserva_legal(e, supressao_respeitou_lei_da_epoca=True)["deficit_devido_ha"] == 0
    com_app = referencia.reserva_legal(e, app_conservada_fora_da_floresta_ha=100)
    assert com_app["deficit_ha"] == pytest.approx(200)
