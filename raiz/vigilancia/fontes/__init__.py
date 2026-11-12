"""Fontes de alerta. Cada fonte devolve uma Leitura com as ocorrências no mesmo formato (GeoDataFrame em EPSG:4674):

    fonte           mapbiomas_alerta | firms | ibama_embargo | deter | prodes
    chave           identificador estável dentro da fonte (chave composta quando a fonte não tem um)
    classe          classe da fonte em minúsculas (desmatamento_cr, cicatriz_de_queimada, foco_alta, embargo...)
    data_evento     data da imagem ou do fato (date)
    publicado_em    data em que a fonte publicou (date ou vazio, quando a fonte não diz)
    area_ha         área da ocorrência inteira
    uf, cod_municipio_ibge
    link            página pública da fonte (quando existe)
    atributos       dict com campos da fonte, sem nada pessoal
    car_fonte       dict {código do CAR: ha} quando a própria fonte já cruzou com o CAR (MapBiomas Alerta)
    geometry        polígono (ponto do FIRMS vira o quadrado do pixel)

Nenhuma fonte grava nome, CPF ou CNPJ: o que é pessoal sai na entrada (privacidade.py).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from raiz.vigilancia.config import Config
from raiz.vigilancia.regras import Regras

COLUNAS = [
    "fonte",
    "chave",
    "classe",
    "data_evento",
    "publicado_em",
    "area_ha",
    "uf",
    "cod_municipio_ibge",
    "link",
    "atributos",
    "car_fonte",
    "geometry",
]
NOMES = ("mapbiomas_alerta", "firms", "ibama_embargo", "deter", "prodes")


@dataclass
class Contexto:
    regras: Regras
    cfg: Config
    hoje: dt.date
    ufs: list[str] = field(default_factory=list)  # UFs vigiadas (com polígono no Release dados ou com projeto)
    caixas: list[tuple[float, float, float, float]] = field(default_factory=list)  # bbox (graus) do que é vigiado


@dataclass
class Leitura:
    fonte: str
    ocorrencias: gpd.GeoDataFrame
    cursor: dict = field(default_factory=dict)  # estado novo da fonte (gravado em fontes.json)
    extras: dict = field(default_factory=dict)  # o que a fonte sabe além das ocorrências (ex.: embargos cancelados)
    nota: str = ""


def vazio() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({c: [] for c in COLUNAS if c != "geometry"}, geometry=[], crs=4674)


def montar(linhas: list[dict]) -> gpd.GeoDataFrame:
    if not linhas:
        return vazio()
    g = gpd.GeoDataFrame(linhas, geometry="geometry", crs=4674)
    for c in COLUNAS:
        if c not in g:
            g[c] = None
    return g[COLUNAS]


def data(v) -> dt.date | None:
    """Data de vários formatos das fontes (2026-10-30, 2026-10-30T00:00:00Z, 20261016, 30/10/2026)."""
    if v is None or (isinstance(v, float) and v != v) or v is pd.NaT:
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    s = str(v).strip()
    if not s:
        return None
    try:
        if len(s) == 8 and s.isdigit():
            return dt.date(int(s[:4]), int(s[4:6]), int(s[6:]))
        if len(s) >= 10 and s[2] == "/" and s[5] == "/":
            return dt.date(int(s[6:10]), int(s[3:5]), int(s[:2]))
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        return None


def caixa_toca(caixas: list[tuple[float, float, float, float]], x0: float, y0: float, x1: float, y1: float) -> bool:
    if not caixas:
        return True
    return any(not (x1 < a or x0 > c or y1 < b or y0 > d) for a, b, c, d in caixas)


_AREA = ("Polygon", "MultiPolygon")


def so_area(g):
    """Conserta a geometria e fica só com a parte de área. O make_valid às vezes devolve coleção mista (polígono com
    linha ou ponto solto), que quebra a interseção. Ponto continua ponto (termo do Ibama sem polígono)."""
    if g is None or g.is_empty:
        return g
    if g.geom_type in ("Point", "MultiPoint"):
        return g
    if g.geom_type == "GeometryCollection":
        # coleção mista vinda da fonte: conserta parte por parte (o make_valid recusa a coleção inteira)
        partes = [x for p in shapely.get_parts(g) if (x := so_area(p)) is not None and x.geom_type in _AREA]
        return _unir(partes)
    if not g.is_valid:
        g = _consertar(g)
        if g is None:
            return None
    if g.geom_type in _AREA:
        return g
    return _unir([p for p in shapely.get_parts(g) if p.geom_type in _AREA])


def _consertar(g):
    for f in (
        shapely.make_valid,
        lambda x: shapely.make_valid(x, method="structure", keep_collapsed=False),
        lambda x: x.buffer(0),
    ):
        try:
            return f(g)
        except shapely.errors.GEOSException:
            continue
    return None


def _unir(partes: list):
    if not partes:
        return None
    if len(partes) == 1:
        return partes[0]
    try:
        return shapely.union_all(partes)
    except shapely.errors.GEOSException:
        return shapely.MultiPolygon([q for p in partes for q in shapely.get_parts(p)])


def so_area_vetor(geos: np.ndarray) -> np.ndarray:
    tipos = shapely.get_type_id(geos)
    ruins = ~shapely.is_valid(geos) | ~np.isin(tipos, (0, 3, 4, 6))  # ponto, polígono, multiponto, multipolígono
    if not ruins.any():
        return geos
    geos = geos.copy()
    geos[ruins] = [so_area(g) for g in geos[ruins]]
    return geos
