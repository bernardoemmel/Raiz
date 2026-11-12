"""Validação cruzada: classes de diferença, imóveis sem par e explicação das maiores diferenças."""

from pathlib import Path

import pandas as pd
import pytest
import yaml

from raiz.regras import validacao

CASOS = yaml.safe_load(Path(__file__).parent.joinpath("dados/imoveis_teste/PA.yaml").read_text())["casos"]


def _im():
    return pd.DataFrame([{"cod_imovel": c["cod_imovel"], **c["entrada"]} for c in CASOS])


def test_classificar():
    a = pd.Series([10.0, 10.0, 100.0, 100.0, None, 5.0, None])
    b = pd.Series([10.005, 10.5, 101.5, 130.0, 3.0, None, None])
    assert list(validacao.classificar(a, b)) == [
        "igual",
        "perto",
        "perto",
        "diferente",
        "só na fonte",
        "só na Raíz",
        "sem valor",
    ]


def test_comparar_com_sicar_simulado():
    im = _im()
    nossa = validacao.laudo_raiz(im)
    ext = pd.DataFrame(
        {
            "cod_imovel": nossa.cod_imovel,
            "num_area_imovel": nossa.ha,
            "num_area_reserva_legal_minima_lei": nossa.rl_minima_ha,
        }
    )
    ext.loc[0, "num_area_reserva_legal_minima_lei"] += 50  # uma diferença de regra
    ext = pd.concat([ext.iloc[1:], pd.DataFrame({"cod_imovel": ["PA-FORA"], "num_area_imovel": [1.0]})])
    rel = validacao.comparar(im, ext, "sicar")
    assert rel.sem_par["só na Raíz"] == [nossa.cod_imovel[0]] and rel.sem_par["só na fonte"] == ["PA-FORA"]
    assert rel.resumo.loc["ha", "igual"] == len(im) - 1
    assert rel.resumo.loc["rl_minima_ha", "igual"] == len(im) - 1

    ext2 = ext.copy()
    ext2.loc[ext2.cod_imovel == nossa.cod_imovel[1], "num_area_reserva_legal_minima_lei"] += 5000
    rel2 = validacao.comparar(im, ext2, "sicar")
    pior = rel2.piores(1).iloc[0]
    assert pior.cod_imovel == nossa.cod_imovel[1] and pior.diferenca == pytest.approx(-5000)
    texto = validacao.explicar_diferencas(rel2, im, n=1)
    assert "diferença -5000.00" in texto[0] and any("art. 12" in t for t in texto)


def test_fonte_sem_codigo():
    with pytest.raises(ValueError, match="código do imóvel"):
        validacao.comparar(_im(), pd.DataFrame({"x": [1]}), "geocar")
