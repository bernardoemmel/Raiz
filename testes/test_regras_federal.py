"""Regras federais do caminho novo contra o laudo do motor nos imóveis de teste (snapshot, E2 passo 3) e testes de
propriedade nas faixas de módulo fiscal e de largura de rio (Hypothesis)."""

from pathlib import Path

import pandas as pd
import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from raiz.regras import parametros
from raiz.regras.federal import calcular, explicar

CASOS = {
    f.stem: yaml.safe_load(f.read_text()) for f in Path(__file__).parent.joinpath("dados/imoveis_teste").glob("*.yaml")
}
P = parametros()


@pytest.mark.parametrize("uf", sorted(CASOS))
def test_laudo_igual_ao_do_motor(uf):
    doc = CASOS[uf]
    assert 60 <= len(doc["casos"]) <= 100
    ent = pd.DataFrame([c["entrada"] for c in doc["casos"]], index=[c["cod_imovel"] for c in doc["casos"]])
    esp = pd.DataFrame([c["esperado"] for c in doc["casos"]], index=ent.index)
    r = calcular(ent, P)
    for col in [
        "pct_RL",
        "pct_RL_alem",
        "deficit_RL80_ha",
        "deficit_RL50_ha",
        "deficit_RL_ha",
        "deficit_RL_alem_ha",
        "alem_RL_ha",
        "app_recompor_ha",
    ]:
        dif = (r[col] - esp[col]).abs()
        assert dif.max() < 1e-4, (col, dif.idxmax(), r.loc[dif.idxmax(), col], esp.loc[dif.idxmax(), col])


def test_explicacao_em_portugues():
    c = CASOS["PA"]["casos"][0]
    passos = explicar(pd.Series(c["entrada"]), P)
    assert any("art. 12" in p for p in passos) and all(isinstance(p, str) for p in passos)


@settings(max_examples=300, deadline=None)
@given(st.floats(0.01, 200), st.floats(0.01, 200))
def test_escadinha_nao_diminui_com_o_tamanho(mf1, mf2):
    a, b = sorted([mf1, mf2])
    assert P.escadinha_m(a) <= P.escadinha_m(b)


@settings(max_examples=300, deadline=None)
@given(st.floats(10.01, 200), st.floats(0, 2000))
def test_faixa_acima_de_10_mf_respeita_minimo_e_maximo(mf, largura):
    assert 30 <= P.escadinha_m(mf, largura_rio_m=largura) <= 100


@settings(max_examples=300, deadline=None)
@given(
    st.floats(0.1, 5000),
    st.floats(0.01, 50),
    st.floats(0, 1),
    st.floats(0, 1),
    st.floats(0, 1),
    st.sampled_from(["Amazônia", "Cerrado", "Caatinga", "Mata Atlântica"]),
    st.sampled_from(["PA", "MT", "SP", "PI"]),
)
def test_propriedades_da_reserva(ha, mf, f_nf, f_flor, f_app, bioma, uf):
    nf = ha * f_nf * 0.3
    flor = (ha - nf) * f_flor
    im = pd.DataFrame(
        [
            {
                "uf": uf,
                "bioma": bioma,
                "ha": ha,
                "m_fiscal": mf,
                "nao_floresta_ha": nf,
                "floresta_rem_ha": flor,
                "desm_total_ha": ha - nf - flor,
                "app_escadinha_ha": ha * f_app * 0.2,
            }
        ]
    )
    r = calcular(im, P).iloc[0]
    assert r.deficit_RL_ha >= 0 and r.deficit_RL80_ha >= r.deficit_RL50_ha
    assert 0 <= r.alem_RL_ha <= im.desm_total_ha[0] + 1e-9
    if mf <= 4:
        assert r.alem_RL_ha == pytest.approx(im.desm_total_ha[0])  # art. 67
    teto = P.teto_61b(mf)
    if teto is not None:
        assert r.app_recompor_ha <= teto * ha + 1e-9  # art. 61-B
