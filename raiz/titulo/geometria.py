"""Geometria do título (E5 passos 3 e 4): azimute e distância no elipsoide, fechamento do polígono e comparação entre
duas descrições da mesma terra (memorial, SIGEF, CAR).

- Elipsoide GRS80 (SIRGAS 2000) pelo pyproj.Geod (MIT), o mesmo cálculo do GeographicLib.
- Fechamento: percorre os lados (azimute e distância) a partir do primeiro vértice num plano local (projeção
  azimutal equidistante centrada nele), mede o erro de fechamento, a precisão relativa (1:N) e ajusta pela regra da
  bússola (Bowditch: a correção de cada vértice é proporcional à distância acumulada).
- Comparação: área, sobreposição (IoU = interseção / união) e maior afastamento entre as bordas (Hausdorff), num
  plano local em metros, numa escala própria de divergência D1 a D7 (o plano cita D1 a D7 sem defini-las; é esta):
    D1 coincide: afastamento até a tolerância
    D2 até 2 vezes a tolerância
    D3 quase coincide: sobreposição de 95% ou mais
    D4 difere pouco: 90% ou mais
    D5 difere: 70% ou mais
    D6 sobreposição parcial
    D7 não se sobrepõem
  A diferença de área sai à parte (dif_area_pct).
- Tolerâncias do georreferenciamento do INCRA: 0,50 m (limite artificial), 3,00 m (natural), 7,50 m (inacessível).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from pyproj import CRS, Geod, Transformer
from shapely.geometry import Polygon
from shapely.ops import transform

GEOD = Geod(ellps="GRS80")
TOLERANCIA_M = {"artificial": 0.50, "natural": 3.00, "inacessivel": 7.50}
CLASSES_D = {
    "D1": "coincide",
    "D2": "até 2 vezes a tolerância",
    "D3": "quase coincide (sobreposição de 95% ou mais)",
    "D4": "difere pouco (sobreposição de 90% ou mais)",
    "D5": "difere (sobreposição de 70% ou mais)",
    "D6": "sobreposição parcial",
    "D7": "não se sobrepõem",
}


# --- ângulos ---------------------------------------------------------------------------------------------------------

_DMS = re.compile(
    r"(?P<s>[-−])?\s*(?P<g>\d{1,3})\s*[°º]\s*(?P<m>\d{1,2})\s*['’′]\s*(?P<seg>\d{1,2}(?:[.,]\d+)?)?\s*(?:\"|”|″|'')?"
    r"\s*(?P<h>[NSEWLO](?![a-z]))?"
)


def dms_para_graus(texto: str) -> float | None:
    """'48°12'34,567" W' -> -48.2096...; '-2°34'56,7"' -> -2.58...; aceita vírgula decimal e hemisfério."""
    m = _DMS.search(str(texto))
    if not m:
        return None
    g = float(m.group("g")) + float(m.group("m")) / 60 + float((m.group("seg") or "0").replace(",", ".")) / 3600
    neg = bool(m.group("s")) or (m.group("h") or "").upper() in ("S", "W", "O")
    return -g if neg else g


def graus_para_dms(graus: float, casas: int = 2) -> str:
    sinal = "-" if graus < 0 else ""
    g = abs(graus)
    gi = int(g)
    m = (g - gi) * 60
    mi = int(m)
    s = round((m - mi) * 60, casas)
    if s >= 60:
        s, mi = 0.0, mi + 1
    if mi >= 60:
        mi, gi = 0, gi + 1
    seg = f"{s:0{3 + casas}.{casas}f}".replace(".", ",")
    return f"{sinal}{gi}°{mi:02d}'{seg}\""


def rumo_para_azimute(graus: float, ns: str, ew: str) -> float:
    """Rumo (0 a 90 graus com quadrante) para azimute (0 a 360, a partir do norte, sentido horário)."""
    ns, ew = ns.upper(), ew.upper().replace("L", "E").replace("O", "W")
    if ns == "N" and ew == "E":
        return graus
    if ns == "S" and ew == "E":
        return 180 - graus
    if ns == "S" and ew == "W":
        return 180 + graus
    return (360 - graus) % 360


def azimute_distancia(lon1: float, lat1: float, lon2: float, lat2: float) -> tuple[float, float]:
    az, _, d = GEOD.inv(lon1, lat1, lon2, lat2)
    return az % 360, d


def avancar(lon: float, lat: float, azimute: float, distancia: float) -> tuple[float, float]:
    lo, la, _ = GEOD.fwd(lon, lat, azimute, distancia)
    return lo, la


def utm_para_geo(e: float, n: float, fuso: int, sul: bool = True) -> tuple[float, float]:
    """SIRGAS 2000 / UTM (EPSG 31960 + fuso no sul, 31954 + fuso no norte)."""
    epsg = (31960 if sul else 31954) + int(fuso)
    t = Transformer.from_crs(epsg, 4674, always_xy=True)
    return t.transform(e, n)


def fuso_do_meridiano(mc: float) -> int:
    return int((180 + mc) // 6) + 1


# --- plano local -------------------------------------------------------------------------------------------------


def _local(lon0: float, lat0: float):
    crs = CRS.from_proj4(f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} +ellps=GRS80 +units=m +no_defs")
    ida = Transformer.from_crs(4674, crs, always_xy=True)
    volta = Transformer.from_crs(crs, 4674, always_xy=True)
    return ida, volta


def area_perimetro(poligono: Polygon) -> tuple[float, float]:
    """Área (ha) e perímetro (m) geodésicos de um polígono em graus (SIRGAS 2000)."""
    a, p = GEOD.geometry_area_perimeter(poligono)
    return abs(a) / 1e4, p


@dataclass
class Fechamento:
    perimetro_m: float
    erro_m: float
    erro_e_m: float
    erro_n_m: float
    precisao: float | None  # N de 1:N (None quando o erro é zero)
    ajustados: list[tuple[float, float]] = field(default_factory=list)  # vértices depois da regra da bússola

    @property
    def texto_precisao(self) -> str:
        return "sem erro" if self.precisao is None else f"1:{self.precisao:,.0f}".replace(",", ".")


def fechar(lon0: float, lat0: float, lados: list[tuple[float, float]]) -> Fechamento:
    """Percorre (azimute, distância) a partir do primeiro vértice e mede o fechamento; ajusta pela bússola."""
    ida, volta = _local(lon0, lat0)
    x, y = 0.0, 0.0
    pontos = [(x, y)]
    perim = 0.0
    for az, d in lados:
        r = math.radians(az)
        x, y = x + d * math.sin(r), y + d * math.cos(r)
        perim += d
        pontos.append((x, y))
    ex, ny = pontos[-1]  # deveria voltar a (0, 0)
    erro = math.hypot(ex, ny)
    ajust = []
    acum = 0.0
    for i, (px, py) in enumerate(pontos[:-1]):
        if i > 0:
            acum += lados[i - 1][1]
        f = acum / perim if perim else 0.0
        ajust.append(volta.transform(px - ex * f, py - ny * f))
    return Fechamento(perim, erro, ex, ny, (perim / erro) if erro > 1e-9 else None, ajust)


# --- comparação --------------------------------------------------------------------------------------------------


def comparar(a: Polygon, b: Polygon, tolerancia_m: float = TOLERANCIA_M["artificial"]) -> dict:
    """Compara duas descrições da mesma terra (polígonos em graus, SIRGAS 2000)."""
    c = a.centroid
    ida, _ = _local(c.x, c.y)
    pa = transform(ida.transform, a)
    pb = transform(ida.transform, b)
    area_a, area_b = pa.area / 1e4, pb.area / 1e4
    inter = pa.intersection(pb).area
    uniao = pa.union(pb).area
    iou = inter / uniao if uniao else 0.0
    haus = pa.boundary.hausdorff_distance(pb.boundary)
    dif = abs(area_a - area_b) / area_a * 100 if area_a else float("inf")
    if haus <= tolerancia_m:
        d = "D1"
    elif haus <= 2 * tolerancia_m:
        d = "D2"
    elif iou >= 0.95:
        d = "D3"
    elif iou >= 0.90:
        d = "D4"
    elif iou >= 0.70:
        d = "D5"
    elif iou > 0.0:
        d = "D6"
    else:
        d = "D7"
    return dict(
        area_a_ha=round(area_a, 4),
        area_b_ha=round(area_b, 4),
        dif_area_pct=round(dif, 2),
        iou=round(iou, 4),
        afastamento_max_m=round(haus, 2),
        tolerancia_m=tolerancia_m,
        classe=d,
        classe_texto=CLASSES_D[d],
    )
