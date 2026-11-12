"""Manifesto de blocos: só os blocos tocados por uma mudança ficam sujos; campo volátil não suja."""

import datetime as dt

import geopandas as gpd
import pytest
from shapely.geometry import box
from sqlalchemy import create_engine, text

from raiz.coleta.espelho import Espelho
from raiz.funil import manifesto_blocos as mb

pytestmark = pytest.mark.banco
T0 = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)


@pytest.fixture
def engine(banco_url):
    eng = create_engine(banco_url)
    with eng.begin() as c:
        c.execute(text("truncate funil.bloco_manifesto, funil.bloco_recorte, funil.bloco_calculo"))
    yield eng
    eng.dispose()


def _car(geoms, ids=None):
    n = len(geoms)
    return gpd.GeoDataFrame(
        {"cod_imovel": [f"PA-1-{i}" for i in range(n)], "area": [1.0] * n, "id": ids or list(range(n))},
        geometry=geoms,
        crs=4674,
    )


def test_so_blocos_tocados_ficam_sujos(engine, tmp_path):
    esp = Espelho(tmp_path)
    f = esp.caminho("car", "PA", 1)
    f.parent.mkdir(parents=True)
    # imóvel 0 no bloco -47.5_-3.0; imóvel 1 atravessa dois blocos (-47.0_-3.0 e -46.5_-3.0)
    g = _car([box(-47.3, -2.9, -47.2, -2.8), box(-46.6, -2.9, -46.4, -2.8)])
    g.to_parquet(f)
    m = mb.atualizar_do_espelho(engine, esp, "PA", [1], T0)
    assert m["car"] == {"-47.5_-3.0", "-47.0_-3.0", "-46.5_-3.0"}
    with engine.begin() as con:
        assert mb.sujos(con) == sorted(m["car"])
        mb.marcar_calculados(con, mb.sujos(con), T0 + dt.timedelta(hours=1))
        assert mb.sujos(con) == []

    # arquivo igual: nem lê de novo
    assert mb.atualizar_do_espelho(engine, esp, "PA", [1], T0 + dt.timedelta(days=1)) == {}

    # só o id do GeoServer mudou (volátil): arquivo novo, nenhum bloco sujo
    _car(list(g.geometry), ids=[10, 11]).to_parquet(f)
    m = mb.atualizar_do_espelho(engine, esp, "PA", [1], T0 + dt.timedelta(days=2))
    assert not m.get("car")

    # imóvel 0 muda de forma e o imóvel 1 sai: sujam o bloco do 0 e os dois do 1
    _car([box(-47.3, -2.9, -47.1, -2.8)]).to_parquet(f)
    m = mb.atualizar_do_espelho(engine, esp, "PA", [1], T0 + dt.timedelta(days=3))
    assert m["car"] == {"-47.5_-3.0", "-47.0_-3.0", "-46.5_-3.0"}
    with engine.begin() as con:
        assert set(mb.sujos(con)) == m["car"]
        n = con.execute(text("select count(*) from funil.bloco_manifesto where hash = ''")).scalar()
        assert n == 2  # os dois blocos do imóvel 1 ficaram vazios para o CAR desse município


def test_dois_municipios_no_mesmo_bloco(engine, tmp_path):
    esp = Espelho(tmp_path)
    for cod, x in ((1, -47.4), (2, -47.2)):
        f = esp.caminho("car", "PA", cod)
        f.parent.mkdir(parents=True, exist_ok=True)
        _car([box(x, -2.9, x + 0.05, -2.8)]).to_parquet(f)
    mb.atualizar_do_espelho(engine, esp, "PA", [1, 2], T0)
    with engine.begin() as con:
        mb.marcar_calculados(con, mb.sujos(con), T0 + dt.timedelta(hours=1))
    # muda só o município 2: o bloco fica sujo, e a parte do município 1 continua lá
    _car([box(-47.2, -2.9, -47.1, -2.8)]).to_parquet(esp.caminho("car", "PA", 2))
    m = mb.atualizar_do_espelho(engine, esp, "PA", [1, 2], T0 + dt.timedelta(days=1))
    assert m["car"] == {"-47.5_-3.0"}
    with engine.begin() as con:
        assert mb.sujos(con) == ["-47.5_-3.0"]
        partes = con.execute(text("select count(*) from funil.bloco_manifesto where hash <> ''")).scalar()
        assert partes == 2
