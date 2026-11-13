import numpy as np
import pandas as pd
import pytest

from raiz import restauracao_linha_base as B


def pixels():
    return pd.DataFrame(
        [
            {
                "pixel_id": f"{bloco}-{pixel}",
                "x_m": bloco * 1000 + pixel * 30,
                "y_m": 50,
                "periodo": periodo,
                "tratado": bloco == 0,
                "elegivel_controle": bloco != 0,
                "valor": periodo * (1 + bloco) + (10 if bloco == 0 and periodo >= 5 else 0),
                "area_m2": 900,
            }
            for bloco in (0, 1, 2)
            for pixel in (0, 1)
            for periodo in range(1, 9)
        ]
    )


def test_agrega_pixels_em_blocos_com_unidade_metrica():
    p = pixels()
    t = B.agregar_pixels(p, crs="EPSG:31982")
    assert len(t) == 24
    assert t.n_pixels.eq(2).all()
    assert t.area_m2.eq(1800).all()
    with pytest.raises(ValueError, match="metros"):
        B.agregar_pixels(p, crs="EPSG:4326")


def test_valor_pos_plantio_nao_altera_pesos_nem_hash_treino():
    a = B.agregar_pixels(pixels(), crs="EPSG:31982")
    b = a.copy()
    b.loc[b.periodo >= 5, "valor"] *= 100
    r1 = B.ajustar(a, bloco_tratado="0:0", periodo_plantio=5, unidade="Mg/ha")
    r2 = B.ajustar(b, bloco_tratado="0:0", periodo_plantio=5, unidade="Mg/ha")
    assert r1["pesos_controles"] == r2["pesos_controles"]
    assert r1["treino_sha256"] == r2["treino_sha256"]
    assert r1["periodos_treino"] == [1, 2, 3, 4]
    assert sum(r1["pesos_controles"].values()) == pytest.approx(1)
    assert r1["serie"][-1]["linha_base"] != r2["serie"][-1]["linha_base"]
    assert not r1["habilita_comercializacao"]


def test_mascara_variavel_e_controle_contaminado_nao_entram():
    p = pixels()
    with pytest.raises(ValueError, match="área observada"):
        B.agregar_pixels(p.iloc[1:], crs="EPSG:31982")
    p.loc[p.tratado, "x_m"] += 1000
    with pytest.raises(ValueError, match="mistura"):
        B.agregar_pixels(p, crs="EPSG:31982")


def test_painel_desbalanceado_e_observacao_invalida_nao_viram_zero():
    a = B.agregar_pixels(pixels(), crs="EPSG:31982")
    for b in [a.iloc[1:], a.assign(valor=np.nan)]:
        with pytest.raises(ValueError):
            B.ajustar(b, bloco_tratado="0:0", periodo_plantio=5, unidade="Mg/ha")
