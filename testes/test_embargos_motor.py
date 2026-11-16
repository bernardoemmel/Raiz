"""Embargo sem polígono retém só os imóveis identificáveis, sem derrubar o município."""

import importlib.util
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
import shapely

MOTOR = Path(__file__).resolve().parents[1] / "motor"


@pytest.fixture
def motor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(MOTOR))
    spec = importlib.util.spec_from_file_location("motor_embargos_teste", MOTOR / "raiz_estado.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _embargos(geometrias, **colunas):
    return pd.DataFrame({"COD_MUNICIPIO": ["1504950"] * len(geometrias),
                         "SIT_CANCELADO": ["N"] * len(geometrias),
                         "SIT_DESEMBARGO": ["N"] * len(geometrias),
                         "GEOM_AREA_EMBARGADA": geometrias, **colunas})  # fmt: skip


@pytest.mark.parametrize("geometria", [None, "", "POLYGON EMPTY", "POINT (-47 -2)",
                                    "LINESTRING (-47 -2, -46 -2)",
                                    "POLYGON ((-47 -2, -46 -2, -45 -2, -47 -2))",
                                    "WKT_PRIVADO_INVALIDO"])  # fmt: skip
def test_municipio_continua_e_retem_so_a_fazenda_afetada(motor, monkeypatch, tmp_path, geometria, capsys):
    car = gpd.GeoDataFrame({"cod_imovel": ["afetada", "livre"], "municipio": ["Exemplo"] * 2,
                           "status_imovel": ["AT"] * 2, "tipo_imovel": ["IRU"] * 2, "m_fiscal": [1, 1]},
                          geometry=[shapely.box(-47, -2, -46.99, -1.99),
                                    shapely.box(-46.9, -1.8, -46.89999, -1.79999)], crs=4674)  # fmt: skip
    vazio = gpd.GeoDataFrame(geometry=[], crs=4674)
    monkeypatch.setattr(motor, "PROJ", vazio)
    monkeypatch.setattr(motor, "car_mun", lambda *a: car)
    monkeypatch.setattr(
        motor, "camadas", lambda *a: ({k: vazio for k in ("yd", "acc", "nf", "hy", "ti", "uc")}, ["Amazônia"])
    )
    monkeypatch.setattr(motor, "sigef", lambda *a: vazio)
    monkeypatch.setattr(motor, "alertas", lambda *a: vazio)
    monkeypatch.setattr(
        motor,
        "biomas",
        lambda: gpd.GeoDataFrame({"bioma": ["Amazônia"]}, geometry=[shapely.box(-48, -3, -45, 0)], crs=4674),
    )
    monkeypatch.setattr(motor, "regeneracao", lambda c, uf: c)
    embargo = _embargos([geometria], COD_IMOVEL=["afetada"])
    c, nome = motor.municipio("PA", 1504950, embargo, out=str(tmp_path))
    assert nome == "Exemplo" and set(c.index) == {"afetada", "livre"}
    assert c.loc["afetada", "embargo_a_conferir"] and c.loc["afetada", "problema"]
    assert c.loc["afetada", "embargo_situacao"] == "embargo a conferir"
    assert pd.isna(c.loc["afetada", "embargo_ha"])
    assert c.loc["afetada", "frente"] == "desbloqueio"
    assert not c.loc["livre", "embargo_a_conferir"] and not c.loc["livre", "problema"]
    assert c.loc["livre", "embargo_ha"] == 0 and c.loc["livre", "ha"] > 0
    from raiz.restauracao import elegivel

    for cod, esperado in (("afetada", False), ("livre", True)):
        assert elegivel({**c.loc[cod].to_dict(), "alem_RL_ha": 10, "pasto_ha": 10}) is esperado
    capturado = capsys.readouterr()
    assert "WKT_PRIVADO_INVALIDO" not in capturado.out + capturado.err


@pytest.mark.parametrize("geometria", [None, "POINT (-47 -2)", "POLYGON EMPTY"])
def test_espelho_sem_poligono_conserva_pendencia(motor, geometria):
    df = _embargos([geometria])
    g = gpd.GeoDataFrame(df, geometry=shapely.from_wkt(df.GEOM_AREA_EMBARGADA), crs=4674)
    out = motor.embargos_municipio(g, 1504950)
    assert out.empty and len(out.attrs["embargos_a_conferir"]) == 1


def test_ponto_do_ibama_marca_todos_os_cars_atingidos_mas_nao_o_municipio(motor):
    car = gpd.GeoDataFrame({"cod_imovel": ["a", "sobreposto", "livre"]},
                          geometry=[shapely.box(-47, -2, -46.99, -1.99)] * 2 +
                                   [shapely.box(-46.9, -1.8, -46.89999, -1.79999)], crs=4674)  # fmt: skip
    df = _embargos([None, "WKT_PRIVADO_INVALIDO", None],
                    NUM_LONGITUDE_TAD=["-46,995", None, None], NUM_LATITUDE_TAD=["-1,995", None, None],
                    SIT_CANCELADO=["N", "N", "S"])  # fmt: skip
    out = motor.marcar_embargos_a_conferir(car, motor.embargos_municipio(df, 1504950))
    assert out.embargo_a_conferir.to_dict() == {"a": True, "sobreposto": True, "livre": False}
    assert out.embargos_sem_vinculo_municipio.eq(1).all()
    assert set(out.columns) == {"embargo_a_conferir", "embargo_situacao", "embargos_sem_vinculo_municipio"}


def test_coluna_geometria_ausente_usa_vinculo_car_sem_area_inventada(motor):
    car = gpd.GeoDataFrame({"cod_imovel": ["a", "b"]}, geometry=[shapely.box(0, 0, 1, 1)] * 2, crs=4674)
    df = _embargos([None], COD_IMOVEL=["a"]).drop(columns="GEOM_AREA_EMBARGADA")
    out = motor.marcar_embargos_a_conferir(car, motor.embargos_municipio(df, 1504950))
    assert out.embargo_a_conferir.to_dict() == {"a": True, "b": False}


def test_inativos_ou_outro_municipio_nao_bloqueiam_e_area_valida_nao_muda(motor):
    poligono = shapely.box(-47, -2, -46.99999, -1.99999)  # também preserva polígonos pequenos
    df = _embargos([poligono.wkt, None, "WKT_INVALIDO", "POINT (-47 -2)"],
                   COD_MUNICIPIO=[1504950, 1504950, 1504950, 1500107],
                   SIT_CANCELADO=["N", "S", "N", "N"], SIT_DESEMBARGO=["N", "N", "S", "N"])  # fmt: skip
    atual = motor.embargos_municipio(df, "1504950")
    esperado = gpd.GeoDataFrame(geometry=[poligono], crs=4674)
    assert len(atual) == 1 and atual.geometry.iloc[0].equals_exact(poligono, 0)
    assert motor.fix(atual).area.iloc[0] == motor.fix(esperado).area.iloc[0] > 0
    assert motor.embargos_municipio(df, 9999999).empty


def test_poligono_reparavel_mantem_a_regra_legada(motor):
    poligono = shapely.Polygon([(-47, -2), (-46.99, -1.99), (-47, -1.99), (-46.99, -2), (-47, -2)])
    assert not poligono.is_valid
    atual = motor.embargos_municipio(_embargos([poligono.wkt]), 1504950)
    esperado = gpd.GeoDataFrame(geometry=[poligono], crs=4674)
    assert atual.geometry.iloc[0].equals_exact(poligono, 0)
    assert motor.fix(atual).area.iloc[0] == motor.fix(esperado).area.iloc[0] > 0


def test_coluna_obrigatoria_ausente_bloqueia(motor):
    with pytest.raises(ValueError, match="colunas obrigatórias"):
        motor.embargos_municipio(_embargos([]).drop(columns="SIT_CANCELADO"), 1504950)
