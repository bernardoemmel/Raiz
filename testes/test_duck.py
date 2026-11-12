"""Cruzamento no DuckDB: plano com SPATIAL_JOIN e os mesmos pares do índice espacial (motor)."""

import geopandas as gpd
import numpy as np
import pytest

from raiz.funil import duck, novo
from testes.test_funil_novo import _aleatorios

try:
    duck.conectar()
    TEM_SPATIAL = True
except Exception:  # noqa: BLE001 - sem rede e sem a extensão no disco
    TEM_SPATIAL = False

pytestmark = pytest.mark.skipif(not TEM_SPATIAL, reason="extensão spatial do DuckDB indisponível")


def test_mesmos_pares_do_indice():
    a, b = _aleatorios(200, 3), _aleatorios(400, 4)
    base = gpd.GeoDataFrame({"cod_imovel": [f"I{i}" for i in range(len(a))]}, geometry=a, crs=5880)
    layer = gpd.GeoDataFrame(geometry=b, crs=5880)
    ib, il = novo.pares(base, layer)
    jb, jl = duck.pares(base, layer)
    esperado = sorted(zip(ib.tolist(), il.tolist(), strict=True))
    assert list(zip(jb.tolist(), jl.tolist(), strict=True)) == esperado and len(esperado) > 100


def test_arquivos_filtro_depois_da_juncao(tmp_path):
    a, b = _aleatorios(50, 5), _aleatorios(80, 6)
    base = gpd.GeoDataFrame({"cod_imovel": [f"I{i}" for i in range(len(a))]}, geometry=a, crs=5880)
    rng = np.random.default_rng(0)
    layer = gpd.GeoDataFrame({"restricao": rng.choice(["ti", "embargo"], len(b))}, geometry=b, crs=5880)
    base.to_parquet(tmp_path / "base.parquet")
    layer.to_parquet(tmp_path / "camada.parquet")
    con = duck.conectar()
    sql = duck.sql_arquivos(str(tmp_path / "base.parquet"), str(tmp_path / "camada.parquet"), "b.restricao = 'ti'")
    assert duck.tem_juncao_espacial(con, sql)
    r = con.sql(sql).df()
    ib, il = novo.pares(base, layer)
    ti = layer.restricao.values[il] == "ti"
    assert len(r) == int(ti.sum()) and set(r.restricao) == {"ti"}
