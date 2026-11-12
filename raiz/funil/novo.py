"""Caminho novo do funil, ao lado do motor e comparado com ele (E2):

- interseção imóvel x camada: mesmos pares que o motor (índice espacial, predicado intersects) e área pelo iOverlay
  (extensão Rust nativo/raiz_iov, em paralelo nos núcleos), testado pelo fundador em motor/iovbench: 2,1x mais rápido
  que o GEOS num núcleo, mesma área. Sem a extensão compilada, cai no GEOS (mesmo resultado, mais lento).
- soma de raster por imóvel: zonal_janela do motor (motor/raiz_extras.py), no lugar de rusterize + bincount.

O motor continua sendo a referência: a bancada (comparar, `raiz funil bancada`) mede tempo e diferença de área.
"""

from __future__ import annotations

import logging
import sys
import time

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from raiz import MOTOR_DIR

log = logging.getLogger(__name__)

try:
    import raiz_iov

    TEM_IOV = True
except ImportError:  # pragma: no cover - depende de a extensão estar compilada
    raiz_iov = None
    TEM_IOV = False


def _multi(geoms) -> np.ndarray:
    """Tudo como MultiPolygon (o formato em vetores do shapely exige um só tipo); o que não é polígono vira vazio."""
    out = []
    for g in geoms:
        if g is None or g.is_empty:
            out.append(shapely.MultiPolygon())
        elif g.geom_type == "Polygon":
            out.append(shapely.MultiPolygon([g]))
        elif g.geom_type == "MultiPolygon":
            out.append(g)
        else:
            ps = [p for p in shapely.get_parts(g) if p.geom_type == "Polygon"]
            ps += [q for p in shapely.get_parts(g) if p.geom_type == "MultiPolygon" for q in p.geoms]
            out.append(shapely.MultiPolygon(ps))
    return np.array(out, dtype=object)


def _vetores(geoms):
    tipo, coords, (aneis, poligonos, multis) = shapely.to_ragged_array(_multi(geoms))
    return (
        np.ascontiguousarray(coords[:, :2], dtype=np.float64),
        aneis.astype(np.int64),
        poligonos.astype(np.int64),
        multis.astype(np.int64),
    )


def areas_iov(a, b, ia: np.ndarray, ib: np.ndarray) -> np.ndarray:
    """Área da interseção de cada par (a[ia[k]], b[ib[k]]), na unidade das coordenadas ao quadrado."""
    if len(ia) == 0:
        return np.zeros(0)
    if not TEM_IOV:
        log.warning("extensão raiz_iov não compilada: usando GEOS")
        return shapely.area(shapely.intersection(np.asarray(a)[ia], np.asarray(b)[ib]))
    # só as geometrias que aparecem nos pares vão para a extensão (camada grande com poucos pares)
    ua, ja = np.unique(np.asarray(ia), return_inverse=True)
    ub, jb = np.unique(np.asarray(ib), return_inverse=True)
    a, b = np.asarray(a, dtype=object)[ua], np.asarray(b, dtype=object)[ub]
    return raiz_iov.area_pares(*_vetores(a), *_vetores(b), ja.astype(np.int64), jb.astype(np.int64))


def pares(base: gpd.GeoDataFrame, layer: gpd.GeoDataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Os mesmos pares do motor (raiz_estado.ov): índice espacial da camada consultado com os imóveis."""
    ib, il = gpd.GeoSeries(layer.geometry.values, crs=layer.crs).sindex.query(
        base.geometry.values, predicate="intersects"
    )
    return ib, il


def ov_iov(base: gpd.GeoDataFrame, layer: gpd.GeoDataFrame) -> pd.Series:
    """Hectares de `layer` dentro de cada imóvel (mesma assinatura e resultado do ov do motor, área pelo iOverlay)."""
    if len(layer) == 0 or len(base) == 0:
        return pd.Series(dtype=float)
    ib, il = pares(base, layer)
    if len(ib) == 0:
        return pd.Series(dtype=float)
    a = areas_iov(base.geometry.values, layer.geometry.values, ib, il) / 1e4
    return pd.Series(a).groupby(base.cod_imovel.values[ib]).sum()


def comparar(base: gpd.GeoDataFrame, layer: gpd.GeoDataFrame) -> dict:
    """Bancada: mesmos pares, GEOS (como o motor) contra iOverlay. Tempo de cada um e diferença de área."""
    ib, il = pares(base, layer)
    bg, lg = base.geometry.values, layer.geometry.values
    t = time.perf_counter()
    a_geos = shapely.area(shapely.intersection(bg[ib], lg[il]))
    t_geos = time.perf_counter() - t
    t = time.perf_counter()
    a_iov = areas_iov(bg, lg, ib, il)
    t_iov = time.perf_counter() - t
    d = np.abs(a_iov - a_geos)
    return {
        "pares": int(len(ib)),
        "geos_s": round(t_geos, 3),
        "iov_s": round(t_iov, 3),
        "vezes": round(t_geos / t_iov, 2) if t_iov else None,
        "area_geos_ha": round(float(a_geos.sum()) / 1e4, 2),
        "area_iov_ha": round(float(a_iov.sum()) / 1e4, 2),
        "maior_dif_m2": round(float(d.max()), 3) if len(d) else 0,
        "pares_dif_1m2": int((d > 1).sum()),
        "extensao": TEM_IOV,
    }


def zonal(fonte, g: gpd.GeoDataFrame, ops=("count", "sum", "max"), include_cols=None):
    """Soma por imóvel do motor (zonal_janela): lê uma janela por grupo de imóveis; aceita endereço ou raster aberto
    (inclusive com o cache de blocos em disco)."""
    if str(MOTOR_DIR) not in sys.path:
        sys.path.insert(0, str(MOTOR_DIR))
    from raiz_extras import zonal_janela

    return zonal_janela(fonte, g, ops, include_cols)
