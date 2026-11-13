"""O caminho legado também bloqueia ausência de geometria em embargo ativo, sem importar E1."""

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
def test_municipio_bloqueia_embargo_antes_de_calcular_areas(motor, monkeypatch, tmp_path, geometria, capsys):
    car = gpd.GeoDataFrame({"cod_imovel": ["exemplo"], "municipio": ["Exemplo"],
                           "status_imovel": ["AT"], "tipo_imovel": ["IRU"]},
                          geometry=[shapely.box(-47, -2, -46.99, -1.99)], crs=4674)  # fmt: skip
    monkeypatch.setattr(motor, "PROJ", gpd.GeoDataFrame(geometry=[], crs=4674))
    monkeypatch.setattr(motor, "car_mun", lambda *a: car)
    monkeypatch.setattr(motor, "camadas", lambda *a: pytest.fail("não calcula com geometria de embargo ausente"))
    with pytest.raises(ValueError, match="embargo ativo sem geometria poligonal válida") as erro:
        motor.municipio("PA", 1504950, _embargos([geometria]), out=str(tmp_path))
    capturado = capsys.readouterr()
    assert "WKT_PRIVADO_INVALIDO" not in str(erro.value) + capturado.out + capturado.err
    assert not list(tmp_path.glob("*.csv"))


@pytest.mark.parametrize("geometria", [None, "POINT (-47 -2)", "POLYGON EMPTY"])
def test_espelho_sem_poligono_tambem_falha(motor, geometria):
    df = _embargos([geometria])
    g = gpd.GeoDataFrame(df, geometry=shapely.from_wkt(df.GEOM_AREA_EMBARGADA), crs=4674)
    with pytest.raises(ValueError, match="embargo ativo sem geometria poligonal válida"):
        motor.embargos_municipio(g, 1504950)


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
