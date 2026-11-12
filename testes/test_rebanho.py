"""Rebanho por fazenda (E4): a PPM do município espalhada pelo pasto e pela produtividade, com o total preservado em
cabeças inteiras, faixa P10 a P90, metano Tier 1 e o rebanho no vazamento. Pequena nunca sai."""

import numpy as np
import pandas as pd
import pytest

from raiz import rebanho as RB
from raiz import vazamento as V
from testes.conftest import AMOSTRA


def test_ppm_e_censo_por_municipio():
    ppm, ppm17 = RB.bovinos_municipio(1504950)
    assert ppm == 53314 and ppm17 == 28210  # Nova Esperança do Piriá, SIDRA 3939
    assert RB.censo_2017(1504950) == 23221  # Censo Agro 2017
    assert RB.bovinos_municipio(9999999) == (None, None)
    assert RB.versao().startswith("rebanho-2026a+")


def test_espalhar_preserva_o_total_e_da_faixa():
    linhas = [{"cod_imovel": f"F{i}", "mb_pasto_2025_ha": ha, "gpw_ugpp": g}
              for i, (ha, g) in enumerate([(10, 1.0), (100, 1.5), (500, 0.5), (3, None), (0, 1.0)])]  # fmt: skip
    out = RB.espalhar(linhas, 1504950)
    p50 = np.array([x["rebanho_cab_p50"] for x in out])
    # total do município em cabeças inteiras; aqui o pasto é pouco e a lotação para no teto de 4 cabeças por ha
    assert p50.sum() == round(min(53314 / 613, 4.0) * 613) and p50.dtype.kind == "i"
    grande = RB.espalhar([{**x, "mb_pasto_2025_ha": 100 * (x["mb_pasto_2025_ha"] or 0)} for x in linhas], 1504950)
    assert sum(x["rebanho_cab_p50"] for x in grande) == 53314  # lotação dentro dos limites: o total da PPM
    assert out[4]["rebanho_cab_p50"] == 0  # sem pasto, sem gado
    assert out[3]["rebanho_cab_p50"] > 0 and out[3]["rebanho_produtividade_fonte"] == "neutra"  # pequena entra
    assert out[1]["rebanho_lotacao_cab_ha"] > out[2]["rebanho_lotacao_cab_ha"]  # pasto mais produtivo, mais gado
    for x in out:
        assert x["rebanho_cab_p10"] <= x["rebanho_cab_p50"] <= x["rebanho_cab_p90"]
    m = RB.regra()["metano"]
    t = (m["enterico_kg_ch4_cab_ano"] + m["dejetos_kg_ch4_cab_ano"]) * m["gwp100"] / 1000
    assert out[1]["metano_tco2e_ano_p50"] == pytest.approx(out[1]["rebanho_cab_p50"] * t, abs=0.1)
    assert RB.espalhar([{"cod_imovel": "X", "pasto_ha": 10}], 9999999)[0]["rebanho_fonte"] == "sem_ppm"
    assert list(RB.inteiros(np.array([0.5, 0.5, 1.0]), 3)) == [1, 1, 1]


def test_rebanho_da_amostra_e_o_vazamento():
    df = RB.calcular_municipio(AMOSTRA, 1504950)
    im = pd.read_csv(AMOSTRA / "imoveis_1504950.csv")
    assert len(df) == len(im) and int(df.rebanho_cab_p50.sum()) == 53314
    assert set(df.rebanho_produtividade_fonte) <= {"gpw", "vigor", "neutra"}
    assert 0.5 < df.rebanho_municipio_lotacao_cab_ha.iloc[0] < 3
    gravado = pd.read_csv(AMOSTRA / "rebanho_1504950.csv")
    assert gravado.rebanho_versao.iloc[0] == RB.versao() and int(gravado.rebanho_cab_p50.sum()) == 53314
    # o vazamento usa o rebanho da E4: cabeças que saem = lotação da fazenda vezes a área restaurada
    li = {**gravado.iloc[0].to_dict(), "pasto_ha": 999.0}
    reb, fonte = V.rebanho(li)
    assert reb == li["rebanho_cab_p50"] and fonte.startswith("ppm_")
    if li["rebanho_pasto_ha"] > 0:
        assert V.cabecas_deslocadas(li, li["rebanho_pasto_ha"] / 2) == pytest.approx(reb / 2)
    dv = pd.read_csv(AMOSTRA / "desenvolvedor_1504950.csv", low_memory=False)
    com = dv[dv.restauracao_area_ha > 0]
    assert (com.rebanho_fonte == "ppm_2025_dasimetrico").all()


def test_ppm_zero_nao_inventa_rebanho_nem_metano(monkeypatch):
    monkeypatch.setattr(RB, "bovinos_municipio", lambda cod, r: (0, 100))
    monkeypatch.setattr(RB, "censo_2017", lambda cod, r: 200)
    out = RB.espalhar([{"cod_imovel": "PEQUENA", "pasto_ha": 3}, {"cod_imovel": "GRANDE", "pasto_ha": 1000}], 1504950)
    assert len(out) == 2
    for fazenda in out:
        assert fazenda["rebanho_municipio_ppm"] == 0
        assert fazenda["rebanho_municipio_lotacao_cab_ha"] == 0
        for faixa in ("p10", "p50", "p90"):
            assert fazenda[f"rebanho_cab_{faixa}"] == 0
            assert fazenda[f"metano_tco2e_ano_{faixa}"] == 0
