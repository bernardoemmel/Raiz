"""Leitura de WFS (GeoServer: SICAR, TerraBrasilis, Geoportal do INCRA).

- Assinatura barata antes de baixar: contagem (resultType=hits) + valor mais novo do campo de data (1 linha
  ordenada pela data, só aquele campo). Se a assinatura do município não mudou, nada é baixado.
- Leitura paginada com ordem estável (sortBy), filtro CQL por município e por data, e conferência da contagem:
  linhas recebidas tem de bater com numberMatched; se não bater, a leitura falha em vez de gravar um município pela
  metade (guarda de qualidade).
- Campos da camada pelo DescribeFeatureType (para saber em que UF existe data_atualizacao).
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass

import geopandas as gpd
import pandas as pd
import requests


class LeituraIncompleta(RuntimeError):
    pass


@dataclass(frozen=True)
class Camada:
    url: str
    nome: str
    versao: str = "2.0.0"
    srs: str = "EPSG:4674"
    geometria: str = "geometry"


def _params(c: Camada, **kw) -> dict:
    p = {"service": "WFS", "version": c.versao, "request": "GetFeature"}
    p["typeNames" if c.versao.startswith("2") else "typeName"] = c.nome
    p.update({k: v for k, v in kw.items() if v is not None})
    return p


def _bbox(c: Camada, bbox: str | tuple[float, float, float, float] | None) -> str | None:
    """Preserva o texto/eixo da coleta; tuplas usam x/y e o SRS declarado na camada."""
    if bbox is None or isinstance(bbox, str):
        return bbox
    return ",".join(map(str, bbox)) + f",{c.srs}"


def _bbox_nao_nulo(c: Camada, bbox: str | tuple[float, float, float, float], campo: str) -> str:
    """Um único filtro FES: GeoServer rejeita os parâmetros bbox e CQL_FILTER juntos.

    O Envelope conserva a ordem e o CRS do parâmetro bbox da coleta. No SIGEF,
    geometry é o campo espacial e a URN EPSG:4674 exige coordenadas lat/lon.
    """
    if not c.versao.startswith("2"):
        raise ValueError("consulta de data com bbox requer WFS 2.0")
    a, b, d, e, srs = _bbox(c, bbox).split(",", 4)
    fes, gml = "http://www.opengis.net/fes/2.0", "http://www.opengis.net/gml/3.2"
    filtro = ET.Element(f"{{{fes}}}Filter")
    conjuncao = ET.SubElement(filtro, f"{{{fes}}}And")
    caixa = ET.SubElement(conjuncao, f"{{{fes}}}BBOX")
    ET.SubElement(caixa, f"{{{fes}}}ValueReference").text = c.geometria
    envelope = ET.SubElement(caixa, f"{{{gml}}}Envelope", {"srsName": srs})
    ET.SubElement(envelope, f"{{{gml}}}lowerCorner").text = f"{a} {b}"
    ET.SubElement(envelope, f"{{{gml}}}upperCorner").text = f"{d} {e}"
    negacao = ET.SubElement(conjuncao, f"{{{fes}}}Not")
    nulo = ET.SubElement(negacao, f"{{{fes}}}PropertyIsNull")
    ET.SubElement(nulo, f"{{{fes}}}ValueReference").text = campo
    return ET.tostring(filtro, encoding="unicode")


def contar(
    s: requests.Session,
    c: Camada,
    cql: str | None = None,
    timeout: int = 120,
    *,
    bbox: str | tuple[float, float, float, float] | None = None,
) -> int:
    r = s.get(c.url, params=_params(c, resultType="hits", CQL_FILTER=cql, bbox=_bbox(c, bbox)), timeout=timeout)
    r.raise_for_status()
    m = re.search(r'number(?:Matched|OfFeatures)="(\d+)"', r.text)
    if not m:
        raise ValueError(f"resposta sem contagem para {c.nome}")
    return int(m.group(1))


def mais_novo(
    s: requests.Session,
    c: Camada,
    campo: str,
    cql: str | None = None,
    timeout: int = 120,
    *,
    bbox: str | tuple[float, float, float, float] | None = None,
) -> str | None:
    """Valor mais novo de `campo` (1 linha ordenada pela data, decrescente; só aquele campo).
    No GeoServer do CAR (Postgres), DESC põe os nulos primeiro: o filtro IS NOT NULL é obrigatório."""
    ordem = f"{campo} DESC" if c.versao.startswith("2") else f"{campo} D"
    chave_qtd = "count" if c.versao.startswith("2") else "maxFeatures"
    # sem parênteses: o GeoServer do CAR responde 500 a "(a=1) AND b IS NOT NULL" (visto em 12/11/2026); os filtros
    # da Raíz só usam AND, então o sentido é o mesmo
    filtro = f"{campo} IS NOT NULL" if not cql else f"{cql} AND {campo} IS NOT NULL"
    if bbox is not None:
        if cql:
            raise ValueError("não combinar CQL e bbox na consulta da data mais nova")
        filtros = {"filter": _bbox_nao_nulo(c, bbox, campo)}
    else:
        filtros = {"CQL_FILTER": filtro}
    p = _params(
        c,
        sortBy=ordem,
        propertyName=campo,
        outputFormat="application/json",
        **filtros,
        **{chave_qtd: 1},
    )
    r = s.get(c.url, params=p, timeout=timeout)
    r.raise_for_status()
    feats = r.json().get("features", [])
    return (feats[0].get("properties") or {}).get(campo) if feats else None


def assinatura(
    s: requests.Session,
    c: Camada,
    campo_data: str | None,
    cql: str | None = None,
    *,
    bbox: str | tuple[float, float, float, float] | None = None,
) -> str:
    n = contar(s, c, cql, bbox=bbox)
    novo = mais_novo(s, c, campo_data, cql, bbox=bbox) if campo_data and n else None
    return f"{n}|{novo or ''}"


def campos(s: requests.Session, c: Camada, timeout: int = 60) -> set[str]:
    p = {"service": "WFS", "version": c.versao, "request": "DescribeFeatureType"}
    p["typeNames" if c.versao.startswith("2") else "typeName"] = c.nome
    r = s.get(c.url, params=p, timeout=timeout)
    r.raise_for_status()
    return set(re.findall(r'<xsd:element[^>]*\bname="([^"]+)"', r.text)) - {c.nome.split(":")[-1]}


def paginas(
    s: requests.Session,
    c: Camada,
    ordenar_por: str,
    cql: str | None = None,
    pagina: int = 10000,
    bbox: str | tuple[float, float, float, float] | None = None,
    timeout: int = 600,
) -> Iterator[gpd.GeoDataFrame]:
    """Páginas do GetFeature em GeoJSON. Confere o total com numberMatched/totalFeatures quando o servidor informa."""
    chave_qtd = "count" if c.versao.startswith("2") else "maxFeatures"
    inicio, recebidas, total = 0, 0, None
    while True:
        extra = {
            chave_qtd: pagina,
            "startIndex": inicio,
            "sortBy": ordenar_por,
            "outputFormat": "application/json",
            "srsName": c.srs,
        }
        if bbox is not None:  # texto pronto (ex.: lat/lon com urn, como o motor faz no SIGEF) ou (x0, y0, x1, y1)
            extra["bbox"] = _bbox(c, bbox)
        r = s.get(c.url, params=_params(c, CQL_FILTER=cql, **extra), timeout=timeout)
        r.raise_for_status()
        j = r.json()
        total = j.get("numberMatched", j.get("totalFeatures", total))
        if isinstance(total, str):
            total = None if total == "unknown" else int(total)
        feats = j.get("features", [])
        g = gpd.read_file(io.BytesIO(r.content), engine="pyogrio") if feats else gpd.GeoDataFrame(geometry=[], crs=4674)
        if len(g):
            # GeoJSON sem membro "crs" é lido como 4326; as coordenadas vêm no srsName que pedimos (como no motor)
            g = g.set_crs(c.srs, allow_override=True)
        recebidas += len(g)
        if len(g):
            yield g
        if len(feats) < pagina:
            break
        inicio += pagina
    if total is not None and recebidas != total:
        raise LeituraIncompleta(f"{c.nome}: recebidas {recebidas} de {total} linhas")


def ler(
    s: requests.Session, c: Camada, ordenar_por: str, cql: str | None = None, pagina: int = 10000, bbox=None
) -> gpd.GeoDataFrame:
    partes = list(paginas(s, c, ordenar_por, cql, pagina, bbox))
    if not partes:
        return gpd.GeoDataFrame(geometry=[], crs=4674)
    return gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), geometry="geometry", crs=partes[0].crs)
