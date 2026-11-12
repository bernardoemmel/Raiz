"""Cruzamento vetorial no DuckDB (E2 passo 2): só o predicado espacial na junção, filtros depois, e o plano conferido
(o EXPLAIN tem de mostrar SPATIAL_JOIN; sem ele o DuckDB cai num produto cartesiano).

O DuckDB acha os pares (imóvel, polígono da camada) lendo GeoParquet direto do disco, sem carregar tudo no pandas;
a área de cada par continua no iOverlay (raiz/funil/novo.py). Os pares são os mesmos do índice espacial do motor.

A extensão spatial do DuckDB é MIT (usa GEOS, LGPL, como biblioteca). Em servidor atrás de proxy, o INSTALL do DuckDB
falha (baixa por http); aqui ela é baixada por https pelo httpx e instalada do arquivo local.
"""

from __future__ import annotations

import gzip
import logging
import tempfile
from pathlib import Path

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

log = logging.getLogger(__name__)

REPO_EXTENSOES = "https://extensions.duckdb.org"


def _baixar_extensao(con: duckdb.DuckDBPyConnection, nome: str) -> None:
    import httpx

    versao = duckdb.__version__
    plataforma = con.sql("PRAGMA platform").fetchone()[0]
    url = f"{REPO_EXTENSOES}/v{versao}/{plataforma}/{nome}.duckdb_extension.gz"
    r = httpx.get(url, timeout=300, follow_redirects=True)
    r.raise_for_status()
    with tempfile.TemporaryDirectory() as d:
        arq = Path(d) / f"{nome}.duckdb_extension"
        arq.write_bytes(gzip.decompress(r.content))
        con.execute(f"INSTALL '{arq}'")


def conectar(con: duckdb.DuckDBPyConnection | None = None) -> duckdb.DuckDBPyConnection:
    """Conexão com a extensão spatial carregada (instala se faltar)."""
    con = con or duckdb.connect()
    try:
        con.execute("LOAD spatial")
    except duckdb.Error:
        try:
            con.execute("INSTALL spatial")
        except duckdb.Error:
            log.info("INSTALL spatial falhou; baixando por https")
            _baixar_extensao(con, "spatial")
        con.execute("LOAD spatial")
    return con


def plano(con: duckdb.DuckDBPyConnection, sql: str) -> str:
    return "\n".join(str(x[1]) for x in con.sql("EXPLAIN " + sql).fetchall())


def tem_juncao_espacial(con: duckdb.DuckDBPyConnection, sql: str) -> bool:
    return "SPATIAL_JOIN" in plano(con, sql)


def _tabela(con, nome: str, geoms) -> None:
    wkb = shapely.to_wkb(np.asarray(geoms, dtype=object))
    t = pd.DataFrame({"i": np.arange(len(wkb), dtype=np.int64), "wkb": wkb})
    con.register(f"_{nome}", t)
    con.execute(f"CREATE OR REPLACE TEMP TABLE {nome} AS SELECT i, ST_GeomFromWKB(wkb) AS g FROM _{nome}")
    con.unregister(f"_{nome}")


SQL_PARES = "SELECT a.i AS ia, b.i AS ib FROM a JOIN b ON ST_Intersects(a.g, b.g)"


def pares(
    base: gpd.GeoDataFrame, layer: gpd.GeoDataFrame, con: duckdb.DuckDBPyConnection | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Mesmos pares que novo.pares (índice espacial), achados pela junção espacial do DuckDB. Ordem (imóvel, camada)."""
    con = conectar(con)
    _tabela(con, "a", base.geometry.values)
    _tabela(con, "b", layer.to_crs(base.crs).geometry.values if layer.crs != base.crs else layer.geometry.values)
    if not tem_juncao_espacial(con, SQL_PARES):  # pragma: no cover - guarda contra mudança do otimizador
        raise RuntimeError("o DuckDB não montou SPATIAL_JOIN para os pares; o cruzamento viraria produto cartesiano")
    r = con.sql(SQL_PARES + " ORDER BY ia, ib").fetchnumpy()
    return r["ia"].astype(np.int64), r["ib"].astype(np.int64)


def sql_arquivos(base: str, camada: str, onde: str | None = None) -> str:
    """Junção entre dois GeoParquet no disco: só o predicado espacial no ON; o filtro da camada (`onde`, por exemplo
    "b.restricao = 'ti'") vai no WHERE, depois da junção."""
    sql = (
        f"SELECT a.cod_imovel, b.* EXCLUDE (geometry) FROM read_parquet('{base}') a "
        f"JOIN read_parquet('{camada}') b ON ST_Intersects(a.geometry, b.geometry)"
    )
    return sql + (f" WHERE {onde}" if onde else "")
