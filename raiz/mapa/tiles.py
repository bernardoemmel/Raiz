"""PMTiles vetorial por município (camadas dentro do imóvel e contorno dos imóveis), para o mapa do front.

Ladrilhos MVT em Web Mercator, zoom 8 a 13 (o MapLibre amplia o 13 nos zooms de cima), comprimidos com gzip, um
arquivo por município (camadas_<mun>.pmtiles), servido com Range. Sem tippecanoe: shapely corta cada feição no
ladrilho e mapbox-vector-tile (MIT) codifica; o pmtiles (BSD-3) escreve o arquivo.
"""

from __future__ import annotations

import gzip
import math
from collections import defaultdict
from pathlib import Path

import shapely

EXTENT = 4096
MEIO = 20037508.342789244  # metade do mundo em EPSG:3857


def _ladrilhos(z: int, caixa_merc) -> list[tuple[int, int]]:
    n = 2**z
    lado = 2 * MEIO / n
    x0, y0, x1, y1 = caixa_merc
    tx0, tx1 = int((x0 + MEIO) // lado), int((x1 + MEIO) // lado)
    ty0, ty1 = int((MEIO - y1) // lado), int((MEIO - y0) // lado)
    return [(x, y) for x in range(max(tx0, 0), min(tx1, n - 1) + 1) for y in range(max(ty0, 0), min(ty1, n - 1) + 1)]


def _caixa_ladrilho(z: int, x: int, y: int):
    lado = 2 * MEIO / 2**z
    return (-MEIO + x * lado, MEIO - (y + 1) * lado, -MEIO + (x + 1) * lado, MEIO - y * lado)


def gerar(caminho: str | Path, camadas: dict, zmin: int = 8, zmax: int = 13) -> dict:
    """camadas: {nome: GeoDataFrame (qualquer CRS) com as propriedades a levar}. Devolve um resumo."""
    import mapbox_vector_tile
    from pmtiles.tile import Compression, TileType, zxy_to_tileid
    from pmtiles.writer import Writer

    merc = {nome: g.to_crs(3857) for nome, g in camadas.items() if g is not None and len(g)}
    if not merc:
        raise ValueError("nada para desenhar")
    por_ladrilho: dict[tuple[int, int, int], dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for nome, g in merc.items():
        props = [c for c in g.columns if c != "geometry"]
        registros = g[props].to_dict("records")
        for geom, p in zip(g.geometry.values, registros, strict=True):
            if geom is None or geom.is_empty:
                continue
            p = {k: (v if isinstance(v, str | int | float | bool) else str(v)) for k, v in p.items() if v is not None}
            for z in range(zmin, zmax + 1):
                lado = 2 * MEIO / 2**z
                tol = lado / EXTENT  # menos que um ponto do ladrilho não aparece
                gz = geom.simplify(tol, preserve_topology=True) if z < zmax else geom
                for x, y in _ladrilhos(z, geom.bounds):
                    cx = _caixa_ladrilho(z, x, y)
                    m = lado * 64 / EXTENT  # margem para não aparecer emenda
                    corte = shapely.clip_by_rect(gz, cx[0] - m, cx[1] - m, cx[2] + m, cx[3] + m)
                    if corte.is_empty:
                        continue
                    por_ladrilho[(z, x, y)][nome].append({"geometry": corte, "properties": p, "_caixa": cx})
    resumo = {"ladrilhos": 0, "bytes": 0}
    ids = sorted((zxy_to_tileid(z, x, y), (z, x, y)) for (z, x, y) in por_ladrilho)
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(caminho).with_suffix(".tmp")
    todos = shapely.union_all([shapely.box(*g.to_crs(4326).total_bounds) for g in camadas.values() if g is not None])
    lon0, lat0, lon1, lat1 = todos.bounds
    with open(tmp, "wb") as f:
        w = Writer(f)
        for tid, (z, x, y) in ids:
            camadas_lt = []
            for nome, feats in por_ladrilho[(z, x, y)].items():
                cx = feats[0]["_caixa"]
                camadas_lt.append(
                    {
                        "name": nome,
                        "features": [{"geometry": ft["geometry"], "properties": ft["properties"]} for ft in feats],
                    }  # fmt: skip
                )
            dado = mapbox_vector_tile.encode(
                camadas_lt, default_options={"quantize_bounds": cx, "extents": EXTENT, "y_coord_down": False}
            )
            dado = gzip.compress(dado)
            w.write_tile(tid, dado)
            resumo["ladrilhos"] += 1
            resumo["bytes"] += len(dado)
        w.finalize(
            {
                "tile_type": TileType.MVT,
                "tile_compression": Compression.GZIP,
                "min_zoom": zmin,
                "max_zoom": zmax,
                "min_lon_e7": int(lon0 * 1e7),
                "min_lat_e7": int(lat0 * 1e7),
                "max_lon_e7": int(lon1 * 1e7),
                "max_lat_e7": int(lat1 * 1e7),
                "center_zoom": max(zmin, min(zmax, 10)),
                "center_lon_e7": int((lon0 + lon1) / 2 * 1e7),
                "center_lat_e7": int((lat0 + lat1) / 2 * 1e7),
            },
            {
                "name": "Raíz: camadas dentro do imóvel",
                "attribution": "MapBiomas, SICAR/SFB, INPE",
                "vector_layers": [{"id": n, "fields": {}} for n in merc],
            },
        )
    tmp.replace(caminho)
    return resumo


def zoom_de_lat(lat: float, metros_por_px: float) -> int:  # pragma: no cover - utilidade
    return int(math.log2(156543.03 * math.cos(math.radians(lat)) / metros_por_px))
