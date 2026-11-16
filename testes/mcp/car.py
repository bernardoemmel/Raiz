"""Fonte CAR sintética exclusiva da amostra e do banco descartável do ensaio MCP."""

import contextlib
import shutil
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import pandas as pd
from shapely.geometry import box
from sqlalchemy.engine import make_url

from raiz import RAIZ_REPO


def validar_banco(url: str) -> str:
    if not url:
        raise RuntimeError("Defina RAIZ_BANCO_URL_MCP_TESTE para PostGIS local descartável")
    destino = make_url(url)
    if (
        destino.drivername not in {"postgresql", "postgresql+psycopg"}
        or destino.host not in {"localhost", "127.0.0.1"}
        or destino.database != "raiz_mcp_teste"
        or destino.query
    ):
        raise RuntimeError("O ensaio MCP exige banco local chamado raiz_mcp_teste")
    return url


@contextlib.contextmanager
def fonte_sintetica(url: str, espelho: Path):
    """Troca só WFS e diretório de insumos; conferência, carga e seleção continuam reais."""
    validar_banco(url)
    pasta = espelho / "saida" / "PA"
    pasta.mkdir(parents=True, exist_ok=True)
    for arquivo in (RAIZ_REPO / "dados" / "amostra").glob("*.csv"):
        destino = pasta / arquivo.name
        if not destino.exists():
            shutil.copyfile(arquivo, destino)
    quadros = []
    for arquivo in pasta.glob("imoveis_*.csv"):
        tabela = pd.read_csv(arquivo, low_memory=False)
        quadro = gpd.GeoDataFrame(tabela, geometry=[box(-47, -1, -46.99, -0.99)] * len(tabela), crs=4674)
        geo = pasta / arquivo.name.replace("imoveis_", "geo_").replace(".csv", ".parquet")
        if not geo.exists():
            quadro[["cod_imovel", "geometry"]].to_parquet(geo)
        quadros.append(quadro)
    atual = gpd.GeoDataFrame(pd.concat(quadros, ignore_index=True), crs=4674)

    def consultar(uf, codigos):
        if uf != "PA" or not codigos <= set(atual.cod_imovel):
            raise ValueError("A fonte CAR do MCP só aceita os imóveis da amostra")
        return atual[atual.cod_imovel.isin(codigos)].copy()

    with (
        patch("raiz.executor.sincronizar.espelho_local", return_value=espelho),
        patch("raiz.coleta.car_conferencia.consultar", consultar),
    ):
        yield pasta
