"""Como achar a fazenda sem internet boa: Plus Code e link do Organic Maps (E9, passo 3 do lote anual).

- Plus Code (Open Location Code, especificação aberta, Apache-2.0): 10 caracteres, cerca de 14 x 14 m, como
  "7FG49QCJ+2V". Funciona no Google Maps, no Organic Maps e escrito à mão num papel.
- Link curto do Organic Maps (mapa livre, offline, com o pacote da região baixado): https://omaps.app/<10 caracteres>
  com o zoom e a coordenada no mesmo código (o formato "ge0" do Organic Maps, reimplementado a partir de
  libs/ge0/url_generator.cpp, Apache-2.0; ver NOTICE.md). Abre o app se ele estiver instalado, ou a página.

O ponto é um ponto dentro do imóvel (ponto de superfície do polígono do CAR), não a porteira de verdade: a porteira
vem do dono ou da visita de campo, e aí substitui este.
"""

from __future__ import annotations

import math

# --- Plus Code ------------------------------------------------------------------------------------------------------

_ALFABETO = "23456789CFGHJMPQRVWX"
_BASE = 20
_PRECISAO_LAT = 8000 * 5**5  # 20^3 x 5^(15 - 10): a mesma conta inteira da implementação de referência
_PRECISAO_LON = 8000 * 4**5


def plus_code(lat: float, lon: float) -> str:
    """Plus Code de 10 dígitos (8 + "+" + 2), como 8FVC9G8F+6X."""
    lat = min(90.0, max(-90.0, lat))
    while lon < -180:
        lon += 360
    while lon >= 180:
        lon -= 360
    if lat == 90:
        lat -= 0.000125  # o canto norte entra na última célula
    v_lat = int(round((lat + 90) * _PRECISAO_LAT, 6)) // 5**5
    v_lon = int(round((lon + 180) * _PRECISAO_LON, 6)) // 4**5
    codigo = ""
    for _ in range(5):
        codigo = _ALFABETO[v_lat % _BASE] + _ALFABETO[v_lon % _BASE] + codigo
        v_lat //= _BASE
        v_lon //= _BASE
    return codigo[:8] + "+" + codigo[8:]


# --- link do Organic Maps (formato ge0) -----------------------------------------------------------------------------

_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
_BITS = 30  # 10 bytes x 3 bits por coordenada
_MAX = (1 << _BITS) - 1
# o que o Organic Maps troca por %XX no nome (rfc3986); o resto, inclusive acento, vai como está
_RESERVADOS = set(" <>#%\"!*'();:@&=+$,/?[]{}\\|^`\x7f") | {chr(i) for i in range(0x20)}


def _iround(x: float) -> int:
    """std::lround: metade para longe do zero."""
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def _lat_int(lat: float, maximo: int) -> int:
    x = (lat + 90.0) / 180.0 * maximo
    return 0 if x < 0 else (maximo if x > maximo else _iround(x))


def _lon_180(lon: float) -> float:
    if lon >= 0:
        return math.fmod(lon + 180.0, 360.0) - 180.0
    v = math.fmod(lon - 180.0, 360.0) + 180.0
    return v if v < 180.0 else v - 360.0


def _lon_int(lon: float, maximo: int) -> int:
    x = (_lon_180(lon) + 180.0) / 360.0 * (maximo + 1.0) + 0.5
    return 0 if (x <= 0 or x >= maximo + 1) else int(x)


def _coordenada_ge0(lat: float, lon: float, n: int = 9) -> str:
    li, lo = _lat_int(lat, _MAX), _lon_int(lon, _MAX)
    out = []
    shift = _BITS - 3
    for _ in range(n):
        a, b = li >> shift & 7, lo >> shift & 7
        out.append(
            _B64[(a >> 2 & 1) << 5 | (b >> 2 & 1) << 4 | (a >> 1 & 1) << 3 | (b >> 1 & 1) << 2 | (a & 1) << 1 | (b & 1)]
        )
        shift -= 3
    return "".join(out)


def _nome_url(nome: str) -> str:
    nome = "".join("_" if c == " " else " " if c == "_" else c for c in nome)
    return "".join("".join(f"%{b:02X}" for b in c.encode()) if c in _RESERVADOS else c for c in nome)


def link_omaps(lat: float, lon: float, zoom: float = 15, nome: str = "") -> str:
    """https://omaps.app/<zoom e coordenada em 10 caracteres>[/nome], o mesmo do botão "compartilhar" do app."""
    z = 0 if zoom <= 4 else (63 if zoom >= 19.75 else int((zoom - 4) * 4))
    url = "https://omaps.app/" + _B64[z] + _coordenada_ge0(lat, lon)
    return url + "/" + _nome_url(nome) if nome else url


def ponto_dentro(geojson: dict | None) -> tuple[float, float] | None:
    """(lon, lat) de um ponto dentro do polígono (o centro, se cair dentro; senão um ponto de superfície)."""
    if not geojson:
        return None
    from shapely.geometry import shape

    g = shape(geojson)
    if g.is_empty:
        return None
    c = g.centroid
    p = c if g.contains(c) else g.representative_point()
    return round(p.x, 6), round(p.y, 6)


def localizacao(geojson: dict | None, nome: str = "") -> dict | None:
    """Plus Code e link do Organic Maps do ponto dentro do imóvel, para a ficha e o envio pelo WhatsApp."""
    p = ponto_dentro(geojson)
    if p is None:
        return None
    lon, lat = p
    return {
        "lon": lon,
        "lat": lat,
        "plus_code": plus_code(lat, lon),
        "omaps": link_omaps(lat, lon, 15, nome),
        "ponto": "dentro do imóvel (a porteira vem do dono ou da visita)",
    }
