"""Ponte entre a coleta e o motor, sem editar motor/.

O motor baixa CAR (car_mun) e SIGEF (sigef) a cada município. Durante a chamada ao motor, a ponte troca essas duas
funções do módulo raiz_estado pela leitura do espelho local da coleta (Parquet por município, escrito pela E1):

    <espelho>/car/<UF>/<cod_municipio>.parquet     camada sicar_imoveis_<uf> do município, colunas do WFS
    <espelho>/sigef/<UF>/<cod_municipio>.parquet   parcelas geonode:sigef_geo que tocam o município

Se o arquivo do município não existir, cai no download original do motor e anota de onde veio. No fim, as funções
originais voltam (a ponte vale só dentro do `with`).
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path

import geopandas as gpd

from raiz import RAIZ_REPO
from raiz.config import config

log = logging.getLogger(__name__)


def espelho_padrao() -> Path:
    return Path(config().espelho_dir) if config().espelho_dir else RAIZ_REPO / "dados" / "espelho"


def arquivo(espelho: Path, camada: str, uf: str, cod: int) -> Path:
    return Path(espelho) / camada / uf.upper() / f"{int(cod)}.parquet"


def ler_local(espelho: Path, camada: str, uf: str, cod: int) -> gpd.GeoDataFrame | None:
    f = arquivo(espelho, camada, uf, cod)
    if not f.exists():
        return None
    g = gpd.read_parquet(f)
    return g.to_crs(4674) if g.crs is not None else g.set_crs(4674)


@contextlib.contextmanager
def ponte(R, uf: str, cod: int, espelho: Path | None = None):
    """R = módulo raiz_estado já importado. Devolve um dicionário com a origem usada para cada camada."""
    espelho = Path(espelho) if espelho else espelho_padrao()
    car_original, sigef_original = R.car_mun, R.sigef
    origem: dict[str, str] = {}

    def car_mun(uf_, cod_):
        g = ler_local(espelho, "car", uf_, cod_)
        if g is None:
            origem["car"] = "download"
            return car_original(uf_, cod_)
        origem["car"] = "espelho"
        return g.drop_duplicates("cod_imovel")

    def sigef(bbox):
        g = ler_local(espelho, "sigef", uf, cod)
        if g is None:
            origem["sigef"] = "download"
            return sigef_original(bbox)
        origem["sigef"] = "espelho"
        x0, y0, x1, y1 = bbox
        g = g.cx[x0:x1, y0:y1]
        return g.drop_duplicates("parcela_codigo") if len(g) else g

    R.car_mun, R.sigef = car_mun, sigef
    try:
        yield origem
    finally:
        R.car_mun, R.sigef = car_original, sigef_original


@contextlib.contextmanager
def ponte_raster(modulo, atributo: str = "U", cache=None):
    """Troca, durante a chamada, os endereços /vsicurl/ de um dicionário do motor (ex.: raiz_direto.U) por rasters
    abertos com o cache de blocos em disco (raiz.coleta.blocos). O zonal_janela do motor aceita o raster aberto.
    Sem editar o motor; no fim, os endereços originais voltam e os rasters são fechados."""
    from raiz.coleta.blocos import CacheDisco, abrir_com_cache

    cache = cache or CacheDisco(cache_raster_padrao(), config().raster_cache_gb)
    original = getattr(modulo, atributo)
    trocado, abertos = dict(original), []
    for k, v in original.items():
        if isinstance(v, str) and v.startswith("/vsicurl/"):
            ds = abrir_com_cache(v.removeprefix("/vsicurl/"), cache)
            abertos.append(ds)
            trocado[k] = ds
    setattr(modulo, atributo, trocado)
    try:
        yield trocado
    finally:
        setattr(modulo, atributo, original)
        for ds in abertos:
            ds.close()


def cache_raster_padrao() -> Path:
    return Path(config().raster_cache_dir) if config().raster_cache_dir else RAIZ_REPO / "dados" / "cache_raster"
