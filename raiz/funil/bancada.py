"""Bancada (E2 passos 1 e 5): interseção imóvel x camada do PRODES pelo GEOS (como o motor) e pelo iOverlay, nos
mesmos pares, com os blocos do TerraBrasilis que o motor já guardou em cache/tb/. Desenho do motor/iovbench/bench.py.
Também mede os pares pelo índice espacial (motor) e pela junção espacial do DuckDB, e confere que são iguais."""

from __future__ import annotations

import glob
import os
import time

import geopandas as gpd
import pandas as pd

from raiz.funil import duck, novo
from raiz.funil.rodar import dir_trabalho, preparar_motor


def bancada(
    uf: str, cod: int, camada: str = "accumulated_deforestation_2007", espaco: str = "prodes-legal-amz"
) -> dict:
    R = preparar_motor(carregar_embargos=False)
    g = gpd.read_parquet(f"saida/{uf.upper()}/geo_{cod}.parquet")
    x0, y0, x1, y1 = g.to_crs(4326).total_bounds
    fs = []
    for f in glob.glob(f"cache/tb/{espaco}__{camada}__*.parquet"):
        lx, ly = map(float, f.split("__")[-1][:-8].split("_"))
        if lx + 0.5 >= x0 and lx <= x1 and ly + 0.5 >= y0 and ly <= y1:
            fs.append(f)
    if not fs:
        raise FileNotFoundError(
            f"sem blocos de {camada} em {os.path.join(dir_trabalho(), 'cache/tb')}: rode o funil antes"
        )
    L = pd.concat([gpd.read_parquet(f) for f in fs])
    L = gpd.GeoDataFrame(L[~L.geometry.isna()], geometry="geometry", crs=L.crs)
    base, lay = R.fix(g, sub=False), R.fix(L)
    r = novo.comparar(base, lay)
    t = time.perf_counter()
    ib, il = novo.pares(base, lay)
    r["pares_indice_s"] = round(time.perf_counter() - t, 3)
    con = duck.conectar()
    t = time.perf_counter()
    jb, jl = duck.pares(base, lay, con)
    r["pares_duckdb_s"] = round(time.perf_counter() - t, 3)
    r["pares_iguais"] = sorted(zip(ib.tolist(), il.tolist(), strict=True)) == list(
        zip(jb.tolist(), jl.tolist(), strict=True)
    )
    r.update(imoveis=len(g), blocos=len(fs), poligonos=len(lay), camada=camada)
    return r
