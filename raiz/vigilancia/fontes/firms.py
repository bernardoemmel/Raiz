"""NASA FIRMS, focos de calor do VIIRS (375 m) nos satélites NOAA-20 (J1) e NOAA-21 (J2).

Sem chave: arquivos públicos da América do Sul (24h, 48h, 7d), sem login. Com FIRMS_MAP_KEY: API de área sobre o
Brasil (até 5 dias por pedido). Cada foco vira o quadrado do pixel (scan x track em km, em volta do ponto), que é o
que o satélite realmente viu; o cruzamento com o imóvel usa esse quadrado.

Dado da NASA (LANCE/FIRMS), de uso livre com citação: "NRT VIIRS 375 m Active Fire product VJ114IMGTDL_NRT e
VJ214IMGTDL_NRT, distribuído pelo NASA FIRMS".
"""

from __future__ import annotations

import io
import math
import os

import pandas as pd
from shapely.geometry import box

from raiz.vigilancia import rede
from raiz.vigilancia.fontes import Contexto, Leitura, caixa_toca, data, montar

BASE_PUBLICA = (
    "https://firms.modaps.eosdis.nasa.gov/data/active_fire/{pasta}/csv/{prefixo}_VIIRS_C2_South_America_{janela}.csv"
)
BASE_API = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{chave}/{fonte}/{bbox}/{dias}"


def _confianca(v) -> str:
    s = str(v).strip().lower()
    if s in ("h", "high", "alta"):
        return "alta"
    if s in ("l", "low", "baixa"):
        return "baixa"
    return "nominal"


def pixel(lon: float, lat: float, scan_km: float | None, track_km: float | None, padrao_m: float = 375):
    """Quadrado do pixel em graus: scan no sentido leste-oeste, track no norte-sul (aproximação boa para 375 m)."""
    sx = (scan_km * 1000 if scan_km and scan_km == scan_km else padrao_m) / 2
    sy = (track_km * 1000 if track_km and track_km == track_km else padrao_m) / 2
    dx = sx / (111_320 * max(math.cos(math.radians(lat)), 0.01))
    dy = sy / 110_574
    return box(lon - dx, lat - dy, lon + dx, lat + dy), (2 * sx) * (2 * sy) / 1e4


def _csv(texto: str, sat: str) -> pd.DataFrame:
    if not texto.strip() or texto.lstrip().startswith("<"):
        raise ValueError("FIRMS não retornou CSV de focos; não equivale a zero ocorrências")
    df = pd.read_csv(io.StringIO(texto))
    if not {"latitude", "longitude", "acq_date", "acq_time"}.issubset(df.columns):
        raise ValueError("CSV do FIRMS não tem as colunas obrigatórias")
    if "satellite" not in df:
        df["satellite"] = sat
    return df


def baixar(ctx: Contexto, primeira: bool) -> tuple[pd.DataFrame, dict]:
    regra = ctx.regras.fonte("firms")
    chave = os.environ.get("FIRMS_MAP_KEY")
    partes, falhas = [], {}
    for sat, s in regra["satelites"].items():
        if chave:
            dias = 5 if primeira else 2
            bbox = ",".join(str(v) for v in regra["bbox_brasil"])
            url = BASE_API.format(chave=chave, fonte=s["api"], bbox=bbox, dias=dias)
        else:
            janela = regra.get("primeira_janela", "7d") if primeira else regra.get("janela", "48h")
            url = BASE_PUBLICA.format(pasta=s["pasta"], prefixo=s["prefixo"], janela=janela)
        try:
            partes.append(_csv(rede.pedir("GET", url, timeout=300).text, sat))
        except (RuntimeError, ValueError) as ex:
            falhas[sat] = rede.limpo(str(ex))[:200]
    if not partes:
        raise RuntimeError("FIRMS NOAA-20 e NOAA-21 indisponíveis: " + "; ".join(falhas.values()))
    return pd.concat(partes, ignore_index=True), falhas


def normalizar(df: pd.DataFrame, ctx: Contexto) -> list[dict]:
    regra = ctx.regras.fonte("firms")
    x0, y0, x1, y1 = regra["bbox_brasil"]
    padrao_m = float(ctx.regras.get("firms_pixel_m", 375))
    linhas = []
    for r in df.itertuples(index=False):
        lon, lat = float(r.longitude), float(r.latitude)
        if not (x0 <= lon <= x1 and y0 <= lat <= y1):
            continue
        d = data(getattr(r, "acq_date", None))
        hora = str(getattr(r, "acq_time", "")).zfill(4)
        sat = str(getattr(r, "satellite", ""))
        geo, ha = pixel(lon, lat, getattr(r, "scan", None), getattr(r, "track", None), padrao_m)
        if not caixa_toca(ctx.caixas, *geo.bounds):
            continue
        conf = _confianca(getattr(r, "confidence", "n"))
        linhas.append(
            {
                "fonte": "firms",
                "chave": f"{sat}|{d}|{hora}|{lat:.5f}|{lon:.5f}",
                "classe": f"foco_{conf}",
                "data_evento": d,
                "publicado_em": d,
                "area_ha": round(ha, 2),
                "uf": None,
                "cod_municipio_ibge": None,
                "link": f"https://firms.modaps.eosdis.nasa.gov/map/#d:{d};@{lon:.4f},{lat:.4f},14.0z",
                "atributos": {
                    "satelite": sat,
                    "hora_utc": hora,
                    "frp_mw": _num(getattr(r, "frp", None)),
                    "brilho_ti4_k": _num(getattr(r, "bright_ti4", None)),
                    "dia_noite": str(getattr(r, "daynight", "")),
                    "confianca_fonte": str(getattr(r, "confidence", "")),
                    "versao": str(getattr(r, "version", "")),
                    "lon": round(lon, 5),
                    "lat": round(lat, 5),
                },
                "car_fonte": None,
                "geometry": geo,
            }
        )
    return linhas


def _num(v):
    try:
        f = float(v)
        return None if f != f else round(f, 2)
    except (TypeError, ValueError):
        return None


def ler(ctx: Contexto, estado: dict) -> Leitura:
    primeira = not estado.get("ultima_leitura")
    df, falhas = baixar(ctx, primeira)
    linhas = normalizar(df, ctx) if len(df) else []
    oc = montar(linhas).drop_duplicates("chave")
    modo = "api" if os.environ.get("FIRMS_MAP_KEY") else "arquivo público"
    return Leitura(
        "firms",
        oc,
        cursor={"modo": modo},
        extras={"falhas": falhas},
        nota=f"{len(df)} focos na América do Sul ({modo}); satélites indisponíveis: {len(falhas)}",
    )
