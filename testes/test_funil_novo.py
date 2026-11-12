"""Caminho novo: área de interseção pelo iOverlay igual à do GEOS (polígonos com buraco, multipolígonos, vazios)."""

import geopandas as gpd
import numpy as np
import pytest
import shapely
from shapely.geometry import MultiPolygon, Polygon, box

from raiz.funil import novo


def _aleatorios(n, semente, x0=5_000_000, y0=9_000_000):
    rng = np.random.default_rng(semente)
    out = []
    for _ in range(n):
        cx, cy = x0 + rng.uniform(0, 20_000), y0 + rng.uniform(0, 20_000)
        r = rng.uniform(200, 3000)
        ang = np.sort(rng.uniform(0, 2 * np.pi, rng.integers(5, 40)))
        raio = r * rng.uniform(0.5, 1.0, len(ang))
        p = Polygon(np.c_[cx + raio * np.cos(ang), cy + raio * np.sin(ang)]).buffer(0)
        if rng.random() < 0.3:  # buraco
            p = p.difference(shapely.Point(cx, cy).buffer(r * 0.2))
        if rng.random() < 0.2:  # multipolígono
            p = p.union(box(cx + 4 * r, cy, cx + 5 * r, cy + r))
        out.append(p)
    return out


@pytest.mark.skipif(not novo.TEM_IOV, reason="extensão raiz_iov não compilada")
def test_area_igual_ao_geos():
    a, b = _aleatorios(150, 1), _aleatorios(300, 2)
    base = gpd.GeoDataFrame({"cod_imovel": [f"I{i}" for i in range(len(a))]}, geometry=a, crs=5880)
    layer = gpd.GeoDataFrame(geometry=b, crs=5880)
    r = novo.comparar(base, layer)
    assert r["extensao"] and r["pares"] > 100
    assert abs(r["area_iov_ha"] - r["area_geos_ha"]) <= 1e-3 * max(r["area_geos_ha"], 1)
    assert r["maior_dif_m2"] < 1.0, r


def test_ov_iov_tem_a_forma_do_ov_do_motor():
    base = gpd.GeoDataFrame(
        {"cod_imovel": ["A", "B", "C"]},
        geometry=[box(0, 0, 100, 100), box(100, 0, 200, 100), box(500, 500, 600, 600)],
        crs=5880,
    )
    layer = gpd.GeoDataFrame(
        geometry=[box(50, 0, 150, 100), MultiPolygon([box(0, 0, 10, 10), box(90, 90, 110, 100)])], crs=5880
    )
    s = novo.ov_iov(base, layer)
    assert set(s.index) == {"A", "B"}  # C não toca a camada: fica fora, como no motor (fillna(0) depois)
    assert s["A"] == pytest.approx((50 * 100 + 10 * 10 + 10 * 10) / 1e4, rel=1e-6)
    assert s["B"] == pytest.approx((50 * 100 + 10 * 10) / 1e4, rel=1e-6)
    assert novo.ov_iov(base, layer.iloc[:0]).empty


def test_geometria_vazia_e_colecao():
    a = np.array([shapely.Polygon(), shapely.GeometryCollection([box(0, 0, 1, 1), shapely.Point(5, 5)])], dtype=object)
    b = np.array([box(0, 0, 2, 2)], dtype=object)
    r = novo.areas_iov(a, b, np.array([0, 1]), np.array([0, 0]))
    assert r[0] == 0 and r[1] == pytest.approx(1.0)
