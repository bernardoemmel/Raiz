"""E2 no caminho de produção: DuckDB + iOverlay e restrições sem apagar evidência legal."""

import sys

import geopandas as gpd
import pandas as pd
import pytest
import shapely

from raiz import MOTOR_DIR
from raiz.funil import duck, rodar
from raiz.funil.filtros import embargos_ativos
from raiz.funil.ponte import ponte_vetorial
from raiz.operacao.healthchecks import Healthchecks


@pytest.fixture
def motor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(MOTOR_DIR))
    # Todos os módulos devem compartilhar a mesma instância de raiz_estado.
    nomes = ("raiz_estado", "raiz_filtros", "raiz_extras")
    anteriores = {n: sys.modules.pop(n, None) for n in nomes}
    import raiz_estado
    import raiz_extras
    import raiz_filtros

    yield raiz_estado, raiz_extras, raiz_filtros
    for nome in nomes:
        sys.modules.pop(nome, None)
        if anteriores[nome] is not None:
            sys.modules[nome] = anteriores[nome]


def _g(geoms, **colunas):
    return gpd.GeoDataFrame(colunas, geometry=geoms, crs=5880)


def test_ponte_mantem_areas_legadas_e_fecha_na_falha(motor, monkeypatch):
    R, _, _ = motor
    base = _g([shapely.box(0, 0, 100, 100), shapely.box(0, 0, 10, 10)], cod_imovel=["a", "pequena"])
    camada = _g([shapely.box(0, 0, 100, 100), shapely.box(0, 0, 50, 100)])
    original = R.ov
    esperado = original(base, camada)
    conectar, conexoes = duck.conectar, []

    def abrir():
        con = conectar()
        conexoes.append(con)
        return con

    monkeypatch.setattr(duck, "conectar", abrir)
    with pytest.raises(RuntimeError, match="falha depois do cruzamento"):
        with ponte_vetorial(R):
            pd.testing.assert_series_equal(R.ov(base, camada), esperado, atol=1e-8)
            assert R.ov(base, camada).loc["pequena"] > 0
            assert len(conexoes) == 1
            assert duck.tem_juncao_espacial(conexoes[0], duck.SQL_PARES)
            raise RuntimeError("falha depois do cruzamento")
    assert R.ov is original
    with pytest.raises(Exception, match="closed"):
        conexoes[0].sql("SELECT 1")


def test_producao_preserva_embargo_sobre_ti_e_imovel_pequeno(motor, tmp_path, monkeypatch):
    R, extras, filtros = motor
    centro = gpd.GeoSeries([shapely.Point(-47, -2)], crs=4674).to_crs(5880).iloc[0]
    x, y = centro.x, centro.y
    car = _g(
        [
            shapely.box(x, y, x + 100, y + 100),
            shapely.box(x, y, x + 10, y + 10),
            shapely.box(x + 1000, y, x + 1100, y + 100),
        ],
        cod_imovel=["grande", "pequena", "livre"],
    )
    ti = _g([shapely.box(x, y, x + 50, y + 100)], fase_ti=["Regularizada"]).to_crs(4674)
    uc = _g(
        [shapely.box(x + 25, y, x + 100, y + 100)],
        grupo=["Proteção Integral"],
        categoria=["Parque Nacional"],
    ).to_crs(4674)
    embargo = ti.copy()  # mesmo trecho: permanece evidência de embargo, área exclusiva é atribuída à TI
    camadas = {"ti": ti, "uc": uc, "quilombo": _g([]).to_crs(4674)}
    monkeypatch.setattr(filtros, "camada", camadas.__getitem__)
    monkeypatch.setattr(extras, "geometria", lambda *a: car)
    monkeypatch.setattr(rodar, "_R", R)
    monkeypatch.setattr(
        rodar,
        "_EMB",
        pd.DataFrame(
            {
                "COD_MUNICIPIO": ["1504950"],
                "SIT_CANCELADO": ["N"],
                "SIT_DESEMBARGO": ["N"],
                "GEOM_AREA_EMBARGADA": [embargo.geometry.iloc[0].wkt],
            }
        ),
    )
    original, conectar, conexoes = R.ov, duck.conectar, []

    def abrir():
        con = conectar()
        conexoes.append(con)
        return con

    def municipio(*args):
        t = car.set_index("cod_imovel").drop(columns="geometry")
        t["embargo_ha"] = R.ov(car, R.fix(embargo))
        t["ti_ha"] = R.ov(car, R.fix(ti))
        return t.fillna(0), "Município de teste"

    monkeypatch.setattr(duck, "conectar", abrir)
    monkeypatch.setattr(R, "municipio", municipio)
    op = rodar.Opcoes("PA", tarefas=("funil", "filtros"), banco=False, espelho=str(tmp_path / "espelho"))
    assert rodar.rodar_municipio(1504950, op, Healthchecks("")) == {"funil": "sucesso", "filtros": "sucesso"}
    assert R.ov is original and len(conexoes) == 1
    saida = tmp_path / "saida" / "PA"
    bruto = pd.read_csv(saida / "imoveis_1504950.csv", index_col="cod_imovel")
    t = pd.read_csv(saida / "filtros_1504950.csv", index_col="cod_imovel")
    assert bruto.loc["grande", "embargo_ha"] == pytest.approx(0.5, abs=1e-6)
    assert bruto.loc["grande", "ti_ha"] == pytest.approx(0.5, abs=1e-6)
    assert t.loc["grande", "uc_protecao_integral_ha"] > t.loc["grande", "restricao_uc_protecao_integral_ha"]
    assert t.loc["grande", "restricao_embargo_ha"] == pytest.approx(0, abs=1e-6)
    assert t.loc["grande", "restricao_total_ha"] == pytest.approx(1, abs=1e-6)
    assert t.loc["pequena", "restricao_total_ha"] == pytest.approx(0.01, abs=1e-6)
    assert t.loc["livre", "restricao_total_ha"] == 0
    limite = pd.Series(car.area.values / 1e4, index=car.cod_imovel)
    assert (t.restricao_total_ha <= limite + 1e-6).all()
    assert set(t.index) == set(car.cod_imovel)


def test_embargos_ativos_excluem_cancelados_sem_ocultar_erro():
    df = pd.DataFrame(
        {
            "COD_MUNICIPIO": [1504950] * 3,
            "SIT_CANCELADO": ["N", "S", "N"],
            "SIT_DESEMBARGO": ["N", "N", "S"],
            "GEOM_AREA_EMBARGADA": [shapely.box(0, 0, 1, 1).wkt] * 3,
        }
    )
    assert len(embargos_ativos(df, 1504950)) == 1
    assert len(embargos_ativos(df, 1234567)) == 0
    with pytest.raises(ValueError, match="obrigatórias"):
        embargos_ativos(df.drop(columns="SIT_CANCELADO"), 1504950)
    df.loc[0, "GEOM_AREA_EMBARGADA"] = "geometria inválida"
    with pytest.raises(shapely.errors.GEOSException):
        embargos_ativos(df, 1504950)


def test_areas_exigem_crs_metrico():
    a = _g([shapely.box(0, 0, 1, 1)], cod_imovel=["a"]).set_crs(4674, allow_override=True)
    with pytest.raises(ValueError, match="metros"):
        duck.ov(a, a)


def test_producao_recusa_plano_sem_spatial_join(monkeypatch):
    base = _g([shapely.box(0, 0, 10, 10)], cod_imovel=["pequena"])
    monkeypatch.setattr(duck, "tem_juncao_espacial", lambda *a: False)
    with pytest.raises(RuntimeError, match="SPATIAL_JOIN"):
        duck.ov(base, base)
