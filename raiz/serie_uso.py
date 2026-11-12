"""Série de uso por imóvel, 1985 até hoje: % de mata, pasto, lavoura e água em cada ano (design v1 do front, item 3).

A cobertura de cada ano vem da API da Plataforma MapBiomas por estado, pelo mesmo exportador do motor
(motor/raiz_mapbiomas.exporta_uf, que pede um ano por vez; a API aceita no máximo 20 anos por pedido), sem editar o
motor: a lista de temas é trocada só durante a chamada. Os anos vão em lotes; cada GeoTIFF do estado é somado por
imóvel (zonal_janela do motor, centro do pixel dentro do imóvel) e apagado em seguida, para não guardar 3 GB por
estado. A saída é serie_uso_<mun>.csv (cod_imovel, ano, mata_pct, pasto_pct, lavoura_pct, agua_pct, colecao), que a
carga leva a funil.serie_uso.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from raiz import MOTOR_DIR

MATA = (3, 4, 5, 6, 49)
PASTO = (15,)
LAVOURA = (9, 18, 19, 20, 35, 36, 39, 40, 41, 46, 47, 48, 62)
AGUA = (26, 31, 33)
COLECAO = "mapbiomas-col11"
CHAVE_COBERTURA = "coverage_coverage-30m-droufo"
PRIMEIRO_ANO = 1985


def anos_padrao() -> list[int]:
    ultimo = int(os.environ.get("RAIZ_MB_ANO", dt.date.today().year - 1))
    return list(range(PRIMEIRO_ANO, ultimo + 1))


@contextlib.contextmanager
def _temas_de_cobertura(rm, anos: list[int]):
    original = rm.TEMAS
    rm.TEMAS = {f"cobertura_{a}": (CHAVE_COBERTURA, a) for a in anos}
    try:
        yield
    finally:
        rm.TEMAS = original


def exportar(uf: str, anos: list[int], dir_trabalho: Path) -> dict[int, Path]:
    """GeoTIFF de cobertura do estado para cada ano (baixa o que falta). Roda na pasta de trabalho do motor."""
    if str(MOTOR_DIR) not in sys.path:
        sys.path.insert(0, str(MOTOR_DIR))
    import raiz_mapbiomas as rm

    antes = Path.cwd()
    os.chdir(dir_trabalho)
    try:
        with _temas_de_cobertura(rm, anos):
            arq = rm.exporta_uf(uf.upper())
    finally:
        os.chdir(antes)
    return {int(k.split("_")[1]): (dir_trabalho / v).resolve() for k, v in arq.items()}


def percentuais(contagem: dict[int, float]) -> dict[str, float | None]:
    """Contagem de pixels por classe -> % de mata, pasto, lavoura e água sobre o que foi classificado (sem o 0)."""
    total = sum(n for c, n in contagem.items() if c != 0)
    if total <= 0:
        return {"mata_pct": None, "pasto_pct": None, "lavoura_pct": None, "agua_pct": None}

    def pct(grupo):
        return round(100 * sum(contagem.get(c, 0) for c in grupo) / total, 1)

    return {"mata_pct": pct(MATA), "pasto_pct": pct(PASTO), "lavoura_pct": pct(LAVOURA), "agua_pct": pct(AGUA)}


def serie_do_ano(geo, tif: Path, ano: int) -> pd.DataFrame:
    """Uma linha por imóvel no ano (zonal_janela 'classes' do motor sobre o GeoTIFF do estado)."""
    import rasterio

    from raiz.funil.novo import zonal

    g = geo.to_crs(4326).reset_index(drop=True)
    with rasterio.open(tif) as ras:
        d = zonal(ras, g, ("classes",), include_cols=["cod_imovel"]).reset_index(drop=True)
    linhas = []
    for _, row in d.iterrows():
        cont = {}
        for c, v in row.items():
            for prefixo in ("band_1_c", "c"):
                if isinstance(c, str) and c.startswith(prefixo) and c[len(prefixo) :].isdigit():
                    cont[int(c[len(prefixo) :])] = float(v or 0)
                    break
        linhas.append({"cod_imovel": row["cod_imovel"], "ano": ano, **percentuais(cont), "colecao": COLECAO})
    return pd.DataFrame(linhas)


def gerar(
    pasta: Path, cods: list[int], anos: list[int], dir_trabalho: Path, lote: int = 5, apagar: bool = True
) -> dict[int, int]:
    """serie_uso_<mun>.csv dos municípios da pasta saida/<UF>/ (junta com os anos que já existirem)."""
    import geopandas as gpd

    uf = pasta.name.upper()
    geos = {c: gpd.read_parquet(pasta / f"geo_{c}.parquet") for c in cods if (pasta / f"geo_{c}.parquet").exists()}
    feitos: dict[int, int] = {c: 0 for c in geos}
    for i in range(0, len(anos), lote):
        bloco = anos[i : i + lote]
        tifs = exportar(uf, bloco, dir_trabalho)
        for cod, geo in geos.items():
            arq = pasta / f"serie_uso_{cod}.csv"
            velho = pd.read_csv(arq) if arq.exists() else pd.DataFrame()
            novos = pd.concat([serie_do_ano(geo, tifs[a], a) for a in bloco], ignore_index=True)
            if len(velho):
                velho = velho[~velho.ano.isin(bloco)]
            tudo = pd.concat([velho, novos], ignore_index=True).sort_values(["cod_imovel", "ano"])
            tmp = arq.with_suffix(".tmp")
            tudo.to_csv(tmp, index=False)
            tmp.replace(arq)
            feitos[cod] = int(tudo.ano.nunique())
        if apagar:
            for t in tifs.values():
                if t.exists() and t.stat().st_size and np.isfinite(t.stat().st_size):
                    t.unlink()
    return feitos
