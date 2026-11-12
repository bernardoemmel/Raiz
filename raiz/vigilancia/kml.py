"""KML sem GDAL: lê polígonos de projeto (Placemark com Polygon ou MultiGeometry e os campos de ExtendedData) e grava a
área afetada por um evento de perda (a Verra pede o KML do polígono afetado no relatório de perda).

Coordenadas em longitude e latitude (WGS 84; para esta escala, igual ao SIRGAS 2000 do CAR).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

import shapely
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

_NS = re.compile(r"^\{[^}]*\}")


def _tag(el: ET.Element) -> str:
    return _NS.sub("", el.tag)


def _coords(texto: str | None) -> list[tuple[float, float]]:
    out = []
    for parte in (texto or "").split():
        xy = parte.split(",")
        if len(xy) >= 2:
            out.append((float(xy[0]), float(xy[1])))
    return out


def _poligono(el: ET.Element) -> Polygon | None:
    externo, internos = None, []
    for filho in el:
        t = _tag(filho)
        if t not in ("outerBoundaryIs", "innerBoundaryIs"):
            continue
        anel = next((c for c in filho.iter() if _tag(c) == "coordinates"), None)
        pts = _coords(anel.text if anel is not None else None)
        if len(pts) < 3:
            continue
        if t == "outerBoundaryIs":
            externo = pts
        else:
            internos.append(pts)
    if not externo:
        return None
    p = Polygon(externo, internos)
    return p if p.is_valid else shapely.make_valid(p)


def _campos(pm: ET.Element) -> dict:
    campos = {}
    for el in pm.iter():
        t = _tag(el)
        if t == "SimpleData" and el.get("name"):
            campos[el.get("name")] = (el.text or "").strip()
        elif t == "Data" and el.get("name"):
            valor = next((c for c in el if _tag(c) == "value"), None)
            campos[el.get("name")] = (valor.text or "").strip() if valor is not None else ""
    return campos


def ler(conteudo: bytes | str) -> list[dict]:
    """Uma entrada por Placemark com polígono: {nome, campos, geometria (MultiPolygon em lon/lat)}."""
    if isinstance(conteudo, bytes):
        conteudo = conteudo.decode("utf-8", errors="replace")
    conteudo = re.sub(r"<!DOCTYPE[^>]*>", "", conteudo, flags=re.I)  # sem entidades externas
    raiz = ET.fromstring(conteudo)
    saida = []
    for pm in raiz.iter():
        if _tag(pm) != "Placemark":
            continue
        nome = next(((c.text or "").strip() for c in pm if _tag(c) == "name"), "")
        partes = [p for el in pm.iter() if _tag(el) == "Polygon" if (p := _poligono(el)) is not None]
        if not partes:
            continue
        geo = shapely.union_all(partes)
        if isinstance(geo, Polygon):
            geo = MultiPolygon([geo])
        elif not isinstance(geo, MultiPolygon):
            geo = MultiPolygon([g for g in getattr(geo, "geoms", []) if isinstance(g, Polygon)])
        saida.append({"nome": nome, "campos": _campos(pm), "geometria": geo})
    return saida


def _anel(coords) -> str:
    return " ".join(f"{x:.7f},{y:.7f},0" for x, y in coords)


def _poligono_kml(p: Polygon) -> str:
    internos = "".join(
        f"<innerBoundaryIs><LinearRing><coordinates>{_anel(i.coords)}</coordinates></LinearRing></innerBoundaryIs>"
        for i in p.interiors
    )
    return (
        f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{_anel(p.exterior.coords)}</coordinates></LinearRing>"
        f"</outerBoundaryIs>{internos}</Polygon>"
    )


def _geometria_kml(g: BaseGeometry) -> str:
    if isinstance(g, Polygon):
        return _poligono_kml(g)
    polis = [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon)]
    return "<MultiGeometry>" + "".join(_poligono_kml(p) for p in polis) + "</MultiGeometry>"


def escrever(nome_documento: str, placemarks: list[dict]) -> str:
    """placemarks: [{nome, geometria (lon/lat), campos: {nome: valor}}]. Devolve o texto do KML."""
    corpo = []
    for pm in placemarks:
        g = pm["geometria"]
        if g is None or g.is_empty:
            continue
        dados = "".join(
            f'<Data name="{escape(str(k))}"><value>{escape(str(v))}</value></Data>'
            for k, v in (pm.get("campos") or {}).items()
            if v is not None
        )
        corpo.append(
            f"<Placemark><name>{escape(pm.get('nome') or '')}</name>"
            f"<ExtendedData>{dados}</ExtendedData>{_geometria_kml(g)}</Placemark>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        f"<name>{escape(nome_documento)}</name>" + "".join(corpo) + "</Document></kml>\n"
    )
