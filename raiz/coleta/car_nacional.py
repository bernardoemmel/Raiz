"""CAR de julho/2026: uma leitura remota por UF, recortes locais pelo limite geobr.

O retrato do SICAR hospedado pela Source Cooperative é a base, não uma conferência
do cadastro atual. O desenho inteiro é conservado (o limite seleciona, não corta
a fazenda). Nenhum filtro por tamanho é aplicado.
"""

from __future__ import annotations

import contextlib
import fcntl
import logging
import os
import re
import time
from pathlib import Path

import duckdb
import geopandas as gpd
import httpx
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import shapely

from raiz.funil.duck import _baixar_extensao, conectar

log = logging.getLogger(__name__)
VERSAO = "2026-07"
URL = "https://data.source.coop/tristangruppwri/cadastral/brazil-car-area-imovel/brazil_car_area_imovel.parquet"
GEOBR_ARQUIVO = "municipalities_2025.parquet"
GEOBR_URL = "https://www.ipea.gov.br/geobr/data_v2.0.0/" + GEOBR_ARQUIVO
_falhas: dict[tuple[str, str], float] = {}


@contextlib.contextmanager
def trava(arquivo: Path):
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    with arquivo.with_suffix(arquivo.suffix + ".lock").open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def arquivo_estado(uf: str, cache: str | Path = "cache") -> Path:
    from raiz.executor.tarefas import UFS

    if uf not in UFS:
        raise ValueError("UF inválida para o CAR nacional")
    return Path(cache) / "car_nacional" / VERSAO / f"{uf}.parquet"


def limites(cache: str | Path = "cache") -> Path:
    arquivo = Path(cache) / "car_nacional" / GEOBR_ARQUIVO
    # Reaproveita também o cache geobr anterior, sem outra cópia nacional.
    anterior = Path(cache) / GEOBR_ARQUIVO
    if anterior.exists():
        return anterior
    with trava(arquivo):
        if arquivo.exists():
            pq.read_metadata(arquivo)
            return arquivo
        tmp = arquivo.with_suffix(f".{os.getpid()}.tmp")
        try:
            with httpx.stream("GET", GEOBR_URL, timeout=300, follow_redirects=True) as r, tmp.open("wb") as f:
                r.raise_for_status()
                for bloco in r.iter_bytes(1024 * 1024):
                    f.write(bloco)
            pq.read_metadata(tmp)
            os.replace(tmp, arquivo)
        finally:
            tmp.unlink(missing_ok=True)
    return arquivo


def estado(uf: str, cache: str | Path = "cache", *, fonte: str = URL) -> Path:
    """Publica o cache só depois da consulta e da validação completas; seguro entre processos."""
    arquivo = arquivo_estado(uf, cache)
    with trava(arquivo):
        if arquivo.exists():
            pq.read_metadata(arquivo)
            return arquivo
        tmp = arquivo.with_suffix(f".{os.getpid()}.tmp")
        try:
            with conectar() as con:
                con.execute("SET threads=4")
                if fonte.startswith("https://"):
                    try:
                        con.execute("LOAD httpfs")
                    except duckdb.Error:
                        _baixar_extensao(con, "httpfs")
                        con.execute("LOAD httpfs")
                # Projeção positiva: nenhuma coluna pessoal nova entra no cache.
                t = con.execute(
                    """SELECT cod_imovel, mod_fiscal AS m_fiscal, num_area AS area,
                        ind_status AS status_imovel, ind_tipo AS tipo_imovel,
                        des_condic AS condicao, municipio, cod_estado AS uf,
                        dat_criaca AS dat_criacao, dat_atuali AS data_atualizacao,
                        ST_AsWKB(geometry) AS wkb
                    FROM read_parquet(?) WHERE cod_estado = ?
                    QUALIFY row_number() OVER (PARTITION BY cod_imovel ORDER BY
                        coalesce(try_cast(dat_atuali AS TIMESTAMP),
                            try_strptime(dat_atuali, ['%d/%m/%Y', '%d/%m/%Y %H:%M:%S'])) DESC NULLS LAST,
                        coalesce(try_cast(dat_criaca AS TIMESTAMP),
                            try_strptime(dat_criaca, ['%d/%m/%Y', '%d/%m/%Y %H:%M:%S'])) DESC NULLS LAST,
                        md5(ST_AsWKB(geometry))) = 1
                    ORDER BY cod_imovel""",
                    [fonte, uf],
                ).fetchdf()
            if t.empty or t.cod_imovel.isna().any() or t.cod_imovel.eq("").any():
                raise ValueError("CAR nacional sem identificadores válidos para a UF")
            g = gpd.GeoDataFrame(
                t.drop(columns="wkb"),
                geometry=shapely.from_wkb(t.wkb.map(lambda b: bytes(b) if b is not None else None)),
                crs=4326,
            )
            # Não inventa o id interno do GeoServer, ausente no retrato nacional.
            g["id"] = None
            g["car_base"] = VERSAO
            g["car_fonte"] = "source_cooperative_sicar"
            g.to_parquet(tmp, compression="zstd", write_covering_bbox=True, schema_version="1.1.0")
            pq.read_metadata(tmp)
            os.replace(tmp, arquivo)
        finally:
            tmp.unlink(missing_ok=True)
    return arquivo


def preparar(uf: str, cache: str | Path = "cache") -> bool:
    """A falha da base libera a reserva WFS; não repete o download a cada município."""
    chave = (str(Path(cache).resolve()), uf)
    if time.monotonic() - _falhas.get(chave, -float("inf")) < 900:
        return False
    try:
        estado(uf, cache)
        limites(cache)
    except (duckdb.Error, OSError, ValueError, httpx.HTTPError) as ex:
        _falhas[chave] = time.monotonic()
        log.warning("CAR nacional %s indisponível (%s); usando WFS de reserva", uf, type(ex).__name__)
        return False
    _falhas.pop(chave, None)
    return True


def municipio(uf: str, cod: int, cache: str | Path = "cache") -> gpd.GeoDataFrame:
    """Interseção exata com o limite de 2025; bbox elimina grupos antes de ler a geometria."""
    if not re.fullmatch(r"\d{7}", str(cod)):
        raise ValueError("Código IBGE inválido")
    limites_uf = gpd.read_parquet(limites(cache), filters=[("abbrev_state", "=", uf)]).to_crs(4326)
    lim = limites_uf[limites_uf.code_muni.astype(int) == int(cod)]
    if len(lim) != 1:
        raise ValueError("Limite municipal geobr ausente ou duplicado")
    geom = lim.geometry.iloc[0]
    g = gpd.read_parquet(estado(uf, cache), bbox=geom.bounds)
    g = g[g.geometry.intersects(geom)].drop_duplicates("cod_imovel").copy()
    # Um CAR que cruza a divisa não pode virar duas fazendas na soma estadual.
    # Prefere o município declarado no identificador se ele de fato intersecta;
    # sem esse vínculo, usa a maior interseção, com desempate pelo código IBGE.
    if len(g):
        g = g.reset_index(drop=True)
        imovel, limite = limites_uf.sindex.query(g.geometry, predicate="intersects")
        pares = pd.DataFrame({"i": imovel, "m": limites_uf.code_muni.iloc[limite].to_numpy(int)})
        declarado = pd.to_numeric(g.cod_imovel.str.extract(r"^[A-Z]{2}-(\d{7})", expand=False), errors="coerce")
        pares["declarado"] = pares.m.to_numpy() == declarado.iloc[imovel].to_numpy()
        pares["area"] = 0.0
        ambiguo = pares.i.duplicated(keep=False) & ~pares.i.isin(pares.loc[pares.declarado, "i"])
        if ambiguo.any():
            pos = np.flatnonzero(ambiguo.to_numpy())
            inter = shapely.intersection(
                shapely.make_valid(g.geometry.iloc[imovel[pos]].to_numpy()),
                shapely.make_valid(limites_uf.geometry.iloc[limite[pos]].to_numpy()),
            )
            pares.loc[ambiguo, "area"] = gpd.GeoSeries(inter, crs=4326).to_crs(5880).area.to_numpy()
        donos = pares.sort_values(["declarado", "area", "m"], ascending=[False, False, True]).drop_duplicates("i")
        g = g.loc[donos.loc[donos.m == int(cod), "i"]].copy()
    g["cod_municipio_ibge"] = int(cod)
    g["municipio"] = lim.name_muni.iloc[0]
    return g.reset_index(drop=True)


def ler(uf: str, cod: int, reserva, cache: str | Path = "cache") -> gpd.GeoDataFrame:
    if preparar(uf, cache):
        try:
            return municipio(uf, cod, cache)
        except (duckdb.Error, OSError, ValueError) as ex:
            log.warning("Recorte CAR nacional indisponível (%s); usando WFS", type(ex).__name__)
    g = reserva(uf, cod)
    g["car_fonte"] = "sicar_wfs_reserva"
    g["car_base"] = VERSAO
    return g
