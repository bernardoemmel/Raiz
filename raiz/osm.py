"""Cidades e estradas do OpenStreetMap a partir dos ladrilhos do Protomaps (build diário, PMTiles lido por faixa de
bytes). É a mesma fonte do mapa base (item 5 do docs/design/dados-para-o-front-v1.md): rios e estradas vêm do OSM,
não da Base Cartográfica do IBGE, que veda uso comercial. Dados © colaboradores do OpenStreetMap (ODbL 1.0): as colunas
derivadas (cidade_proxima, estrada_acesso) levam a atribuição na ficha e no NOTICE.md.

Lê só os ladrilhos da caixa do município num zoom baixo (lugares no 10, estradas no 11), com os diretórios em cache
na memória e os ladrilhos em cache no disco (dados/cache_osm/), então rodar de novo não baixa nada.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import shapely
from shapely.geometry import shape

from raiz import RAIZ_REPO

PROTOMAPS = "https://build.protomaps.com/{}.pmtiles"
ZOOM_LUGARES = 10
ZOOM_ESTRADAS = 11
CIDADES = ("city", "town")
VILAS = ("village",)
CLASSES_ESTRADA = ("highway", "major_road", "medium_road", "minor_road")


def build_recente(cliente: httpx.Client | None = None, dias: int = 15) -> str:
    c = cliente or httpx.Client(timeout=30)
    hoje = dt.date.today()
    for d in range(dias):
        dia = (hoje - dt.timedelta(days=d)).strftime("%Y%m%d")
        if c.head(PROTOMAPS.format(dia)).status_code == 200:
            return dia
    raise RuntimeError("nenhum build do Protomaps nos últimos dias")


class PMTilesRemoto:
    """Leitor de PMTiles por faixa de bytes (cabeçalho, diretórios e ladrilhos), com cache dos ladrilhos em disco."""

    def __init__(self, url: str, cache: Path | None = None, cliente: httpx.Client | None = None):
        from pmtiles.tile import deserialize_header

        self.url = url
        self.c = cliente or httpx.Client(timeout=120, follow_redirects=True)
        self.cache = cache
        self.dirs: dict[tuple[int, int], list] = {}
        self.header = deserialize_header(self._ler(0, 127))

    def _ler(self, inicio: int, tamanho: int) -> bytes:
        for tentativa in range(5):
            try:
                r = self.c.get(self.url, headers={"Range": f"bytes={inicio}-{inicio + tamanho - 1}"})
                r.raise_for_status()
                return r.content
            except httpx.HTTPError:
                if tentativa == 4:
                    raise
        return b""

    def _diretorio(self, inicio: int, tamanho: int):
        from pmtiles.tile import deserialize_directory

        if (inicio, tamanho) not in self.dirs:
            self.dirs[(inicio, tamanho)] = deserialize_directory(self._ler(inicio, tamanho))
        return self.dirs[(inicio, tamanho)]

    def ladrilho(self, z: int, x: int, y: int) -> bytes | None:
        from pmtiles.tile import Compression, find_tile, zxy_to_tileid

        arq = None
        if self.cache is not None:
            nome = hashlib.sha1(self.url.encode()).hexdigest()[:10]
            arq = self.cache / nome / f"{z}" / f"{x}_{y}.mvt"
            if arq.exists():
                dado = arq.read_bytes()
                return dado or None
        h = self.header
        tid = zxy_to_tileid(z, x, y)
        inicio, tamanho = h["root_offset"], h["root_length"]
        dado = None
        for _ in range(4):
            e = find_tile(self._diretorio(inicio, tamanho), tid)
            if e is None:
                break
            if e.run_length == 0:
                inicio, tamanho = h["leaf_directory_offset"] + e.offset, e.length
                continue
            dado = self._ler(h["tile_data_offset"] + e.offset, e.length)
            if h["tile_compression"] == Compression.GZIP:
                dado = gzip.decompress(dado)
            break
        if arq is not None:
            arq.parent.mkdir(parents=True, exist_ok=True)
            arq.write_bytes(dado or b"")
        return dado


def ladrilhos_na_caixa(z: int, caixa) -> list[tuple[int, int, int]]:
    def xy(lon, lat):
        n = 2**z
        x = int((lon + 180) / 360 * n)
        lat = max(min(lat, 85.05), -85.05)
        y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
        return min(max(x, 0), n - 1), min(max(y, 0), n - 1)

    x0, y1 = xy(caixa[0], caixa[1])
    x1, y0 = xy(caixa[2], caixa[3])
    return [(z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]


def _feicoes(dado: bytes, z: int, x: int, y: int, camada: str) -> list[tuple[dict, object]]:
    """Feições de uma camada do ladrilho MVT, com a geometria em lon/lat."""
    import mapbox_vector_tile

    d = mapbox_vector_tile.decode(dado, default_options={"y_coord_down": True})
    lay = d.get(camada)
    if not lay:
        return []
    ext = lay.get("extent", 4096)
    n = 2**z

    def lonlat(px, py):
        lon = (x + px / ext) / n * 360 - 180
        yy = (y + py / ext) / n
        lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yy))))
        return lon, lat

    out = []
    for f in lay["features"]:
        g = shape(f["geometry"])
        g = shapely.transform(g, lambda c: [list(lonlat(*p)) for p in c] if len(c) else c, interleaved=True)
        out.append((f.get("properties") or {}, g))
    return out


def _coletar(remoto: PMTilesRemoto, z: int, caixa, camada: str) -> list[tuple[dict, object]]:
    tiles = ladrilhos_na_caixa(z, caixa)
    with ThreadPoolExecutor(16) as ex:
        dados = list(ex.map(lambda t: remoto.ladrilho(*t), tiles))
    out = []
    for (tz, tx, ty), d in zip(tiles, dados, strict=True):
        if d:
            out += _feicoes(d, tz, tx, ty, camada)
    return out


def cache_padrao() -> Path:
    return RAIZ_REPO / "dados" / "cache_osm"


def lugares_e_estradas(caixa, dia: str | None = None, remoto: PMTilesRemoto | None = None) -> tuple[list, list]:
    """(cidades, estradas) dentro da caixa (lon0, lat0, lon1, lat1) mais uma margem de 0,5 grau para as cidades."""
    if remoto is None:
        dia = dia or build_recente()
        remoto = PMTilesRemoto(PROTOMAPS.format(dia), cache_padrao())
    x0, y0, x1, y1 = caixa
    lugares = []
    for p, g in _coletar(remoto, ZOOM_LUGARES, (x0 - 0.5, y0 - 0.5, x1 + 0.5, y1 + 0.5), "places"):
        tipo = p.get("kind_detail") or p.get("kind")
        if p.get("name") and tipo in CIDADES + VILAS and g.geom_type == "Point":
            lugares.append({"nome": p["name"], "tipo": tipo, "pop": p.get("population"), "geom": g})
    estradas = []
    for p, g in _coletar(remoto, ZOOM_ESTRADAS, (x0 - 0.1, y0 - 0.1, x1 + 0.1, y1 + 0.1), "roads"):
        nome = p.get("ref") or p.get("name")
        if nome and p.get("kind") in CLASSES_ESTRADA and not g.is_empty:
            estradas.append({"nome": str(nome).split(";")[0], "tipo": p.get("kind"), "geom": g})
    return lugares, estradas


_DIRECOES = ("N", "NE", "L", "SE", "S", "SO", "O", "NO")


def direcao(de, para) -> str:
    """Rumo de `de` para `para` em oito pontos (N, NE, L, SE, S, SO, O, NO), em graus de lon/lat corrigidos pela
    latitude."""
    dx = (para.x - de.x) * math.cos(math.radians((de.y + para.y) / 2))
    dy = para.y - de.y
    ang = (math.degrees(math.atan2(dx, dy)) + 360) % 360
    return _DIRECOES[int((ang + 22.5) // 45) % 8]


def km(a, b) -> float:
    """Distância de grande círculo em km."""
    la1, la2 = math.radians(a.y), math.radians(b.y)
    dla, dlo = la2 - la1, math.radians(b.x - a.x)
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def por_imovel(pontos: dict[str, object], lugares: list, estradas: list) -> dict[str, dict]:
    """Para cada imóvel (ponto dentro dele, em lon/lat): cidade mais próxima (cidade ou vila, preferindo cidade a até
    o dobro da distância da vila), distância, direção do imóvel visto da cidade e estrada com nome ou número mais
    próxima, com a distância."""
    cidades = [c for c in lugares if c["tipo"] in CIDADES] or lugares
    arvore = shapely.STRtree([e["geom"] for e in estradas]) if estradas else None
    out = {}
    for cod, p in pontos.items():
        d = {"cidade_proxima": None, "cidade_proxima_km": None, "cidade_proxima_direcao": None,
             "estrada_acesso": None, "estrada_acesso_km": None}  # fmt: skip
        if cidades:
            c = min(cidades, key=lambda c: km(p, c["geom"]))
            d.update(
                cidade_proxima=c["nome"],
                cidade_proxima_km=round(km(p, c["geom"]), 1),
                cidade_proxima_direcao=direcao(c["geom"], p),
            )
        if arvore is not None:
            i = int(arvore.nearest(p))
            e = estradas[i]
            perto = shapely.ops.nearest_points(p, e["geom"])[1]
            d.update(estrada_acesso=e["nome"], estrada_acesso_km=round(km(p, perto), 1))
        out[cod] = d
    return out


def atribuicao() -> str:
    return "Dados © colaboradores do OpenStreetMap (ODbL 1.0), via Protomaps"


def salvar_json(caminho: Path, dado) -> None:
    caminho.write_text(json.dumps(dado, ensure_ascii=False), encoding="utf-8")
