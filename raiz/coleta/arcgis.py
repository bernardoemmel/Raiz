"""Fonte ArcGIS REST (Ibama, SFB, IPAAM, ANA), no molde do ArcGISFeatureServerSpider (desenho):

- lê os detalhes da camada (?f=json): campo de id, maxRecordCount e editingInfo.lastEditDate;
- se lastEditDate não mudou desde a última coleta, pula a camada inteira (nada é baixado);
- pagina por OBJECTID crescente (where id > último, orderByFields), não por offset, e confere o total com
  returnCountOnly: camada pela metade falha em vez de ser gravada.
"""

from __future__ import annotations

import io

import geopandas as gpd
import pandas as pd
import requests

from raiz.coleta.wfs import LeituraIncompleta


def detalhes(s: requests.Session, url: str, timeout: int = 60) -> dict:
    r = s.get(url, params={"f": "json"}, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    if "error" in j:
        raise RuntimeError(f"ArcGIS: {j['error']}")
    return j


def ultima_edicao(d: dict) -> int | None:
    return (d.get("editingInfo") or {}).get("lastEditDate")


def contar(s: requests.Session, url: str, where: str = "1=1", timeout: int = 120) -> int:
    r = s.get(f"{url}/query", params={"where": where, "returnCountOnly": "true", "f": "json"}, timeout=timeout)
    r.raise_for_status()
    return int(r.json()["count"])


def ler(
    s: requests.Session,
    url: str,
    where: str = "1=1",
    ultima_edicao_conhecida: int | None = None,
    srid: int = 4674,
    timeout: int = 600,
) -> tuple[gpd.GeoDataFrame | None, int | None]:
    """Devolve (camada, lastEditDate). Camada None quando lastEditDate não mudou."""
    d = detalhes(s, url)
    edicao = ultima_edicao(d)
    if ultima_edicao_conhecida is not None and edicao == ultima_edicao_conhecida:
        return None, edicao
    oid = d.get("objectIdField") or next(
        (f["name"] for f in d.get("fields", []) if f.get("type") == "esriFieldTypeOID"), "OBJECTID"
    )
    passo = int(d.get("maxRecordCount") or 1000)
    total = contar(s, url, where)
    partes, ultimo = [], -1
    while True:
        r = s.get(
            f"{url}/query",
            params={
                "where": f"({where}) AND {oid} > {ultimo}",
                "orderByFields": f"{oid} ASC",
                "resultRecordCount": passo,
                "outFields": "*",
                "outSR": srid,
                "f": "geojson",
            },
            timeout=timeout,
        )
        r.raise_for_status()
        feats = r.json().get("features", [])
        if not feats:
            break
        g = gpd.read_file(io.BytesIO(r.content), engine="pyogrio").set_crs(srid, allow_override=True)
        partes.append(g)
        ultimo = int(g[oid].max())
        if len(feats) < passo:
            break
    g = (
        gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), geometry="geometry", crs=srid)
        if partes
        else gpd.GeoDataFrame(geometry=[], crs=srid)
    )
    if len(g) != total:
        raise LeituraIncompleta(f"{url}: recebidas {len(g)} de {total} feições")
    return g, edicao
