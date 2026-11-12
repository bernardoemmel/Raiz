"""Geometrias do front da Raíz, só de fontes públicas e sem nome, CPF ou CNPJ.

Uso (da raiz do repositório):
  pip install requests shapely pmtiles        # todas BSD-3 / Apache-2.0
  python front/scripts/geo.py 1507300 1504950 # códigos IBGE dos municípios

Saída em front/geo/ (fora do git, é dado gerado e pode ser grande):
  municipio_<cod>.geojson   divisa do município (TerraBrasilis, municipalities_legal_amazon)
  imoveis_<cod>.geojson     polígonos do CAR (WFS do SICAR), IRU e não cancelados, como o motor filtra;
                            propriedades: cod_imovel, area, m_fiscal, status_imovel (nada pessoal)
  ti_<cod>.geojson          terras indígenas na caixa do município (TerraBrasilis)
  uc_<cod>.geojson          unidades de conservação na caixa do município (TerraBrasilis)
  rios_<cod>.geojson        hidrografia do PRODES na caixa do município (a mesma que o motor usa para a APP)
  base_<cod>.pmtiles        mapa base recortado do build diário do Protomaps (dados © OpenStreetMap, ODbL)
  fontes/<fonte>/<faixa>.pbf  letras dos rótulos do mapa (Noto Sans, licença OFL, do protomaps/basemaps-assets)
  indice.json               o que já foi gerado, lido pelo front para saber o que existe

Roda de novo sem baixar o que já existe (apague o arquivo para baixar de novo).
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
import shapely
from pmtiles.tile import Compression, TileType, deserialize_directory, deserialize_header, find_tile, zxy_to_tileid
from pmtiles.writer import Writer
from shapely.geometry import box, mapping, shape

SAIDA = Path(__file__).resolve().parent.parent / "geo"
CAR_WFS = "https://geoserver.car.gov.br/geoserver/sicar/wfs"
TB_WFS = "https://terrabrasilis.dpi.inpe.br/geoserver/ows"
PROTOMAPS = "https://build.protomaps.com/{}.pmtiles"
BRASIL = (-74.0, -34.0, -34.0, 5.5)

class TLSAntigo(requests.adapters.HTTPAdapter):
    """O servidor do CAR usa TLS antigo; o Python novo recusa sem isto (o mesmo ajuste de motor/raiz_estado.py)."""

    @staticmethod
    def _ctx():
        import ssl

        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
        return ctx

    def init_poolmanager(self, *a, **k):
        k["ssl_context"] = self._ctx()
        return super().init_poolmanager(*a, **k)

    def proxy_manager_for(self, proxy, **k):
        k["ssl_context"] = self._ctx()
        return super().proxy_manager_for(proxy, **k)


S = requests.Session()
S.headers["User-Agent"] = "raiz-front-geo/1.0"
S.mount("https://geoserver.car.gov.br", TLSAntigo())


def baixar(url: str, params: dict | None = None, headers: dict | None = None, tentativas: int = 5, timeout: int = 300):
    for i in range(tentativas):
        try:
            r = S.get(url, params=params, headers=headers, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as ex:  # noqa: BLE001
            print(f"   tentativa {i + 1} falhou: {str(ex)[:120]}")
            time.sleep(2 * 2**i)
    raise RuntimeError("download falhou: " + url)


def arredondar(geom, casas: int = 6):
    return shapely.set_precision(geom, 10**-casas) if not geom.is_empty else geom


def salvar(nome: str, feicoes: list[dict]) -> int:
    caminho = SAIDA / nome
    caminho.write_text(json.dumps({"type": "FeatureCollection", "features": feicoes}, separators=(",", ":")))
    return caminho.stat().st_size


def feicao(geom, props: dict) -> dict:
    return {"type": "Feature", "properties": props, "geometry": mapping(geom)}


# --- divisa do município ------------------------------------------------------------------------------------------


def municipio(cod: str):
    arq = SAIDA / f"municipio_{cod}.geojson"
    if arq.exists():
        g = json.loads(arq.read_text())["features"][0]
        return shape(g["geometry"]), g["properties"]["nome"]
    print(f" divisa de {cod}")
    r = baixar(
        TB_WFS,
        dict(
            service="WFS",
            version="1.0.0",
            request="GetFeature",
            typeName="prodes-legal-amz:municipalities_legal_amazon",
            outputFormat="application/json",
            srsName="EPSG:4326",
            CQL_FILTER=f"geocodigo='{cod}'",
        ),
    )
    fs = r.json()["features"]
    if not fs:
        raise SystemExit(f"município {cod} não está na camada da Amazônia Legal do TerraBrasilis")
    geom = shapely.union_all([shape(f["geometry"]) for f in fs])
    nome = fs[0]["properties"]["nome"]
    geom = arredondar(geom.simplify(0.0003, preserve_topology=True), 5)
    salvar(arq.name, [feicao(geom, {"cod_ibge": cod, "nome": nome})])
    return geom, nome


# --- polígonos do CAR ---------------------------------------------------------------------------------------------


def imoveis(cod: str, uf: str = "pa") -> None:
    arq = SAIDA / f"imoveis_{cod}.geojson"
    if arq.exists():
        return
    print(f" CAR de {cod}")
    feicoes, inicio, vistos = [], 0, set()
    while True:
        r = baixar(
            CAR_WFS,
            dict(
                service="WFS",
                version="2.0.0",
                request="GetFeature",
                typeNames=f"sicar:sicar_imoveis_{uf}",
                outputFormat="application/json",
                CQL_FILTER=f"cod_municipio_ibge={cod}",
                sortBy="cod_imovel",
                count=5000,
                startIndex=inicio,
            ),
            timeout=900,
        )
        fs = r.json()["features"]
        for f in fs:
            p = f["properties"]
            # o mesmo filtro do motor: só imóvel rural (IRU) e não cancelado
            if p.get("tipo_imovel") != "IRU" or p.get("status_imovel") == "CA" or p["cod_imovel"] in vistos:
                continue
            if not f.get("geometry"):
                continue
            vistos.add(p["cod_imovel"])
            g = shape(f["geometry"])
            if not g.is_valid:
                g = shapely.make_valid(g)
            g = arredondar(g.simplify(0.00002, preserve_topology=True), 6)
            if g.is_empty:
                continue
            props = {k: p.get(k) for k in ("cod_imovel", "area", "m_fiscal", "status_imovel")}
            feicoes.append(feicao(g, props))
        print(f"   {len(feicoes)} imóveis")
        if len(fs) < 5000:
            break
        inicio += 5000
    tam = salvar(arq.name, feicoes)
    print(f"   {arq.name}: {tam / 1e6:.1f} MB")


# --- TerraBrasilis: terra indígena, unidade de conservação, rios ---------------------------------------------------


def camada_tb(cod: str, nome: str, camada: str, caixa, campos: dict[str, str], tolerancia: float) -> None:
    arq = SAIDA / f"{nome}_{cod}.geojson"
    if arq.exists():
        return
    print(f" {nome} de {cod}")
    x0, y0, x1, y1 = caixa
    r = baixar(
        TB_WFS,
        dict(
            service="WFS",
            version="1.0.0",
            request="GetFeature",
            typeName=camada,
            outputFormat="application/json",
            srsName="EPSG:4326",
            bbox=f"{x0},{y0},{x1},{y1}",
        ),
        timeout=900,
    )
    recorte = box(*caixa)
    feicoes = []
    for f in r.json()["features"]:
        if not f.get("geometry"):
            continue
        g = shape(f["geometry"])
        if not g.is_valid:
            g = shapely.make_valid(g)
        g = g.intersection(recorte)
        if g.is_empty:
            continue
        g = arredondar(g.simplify(tolerancia, preserve_topology=True), 5)
        props = {novo: f["properties"].get(velho) for velho, novo in campos.items()}
        feicoes.append(feicao(g, props))
    tam = salvar(arq.name, feicoes)
    print(f"   {len(feicoes)} feições, {tam / 1e3:.0f} kB")


# --- mapa base: recorte do build diário do Protomaps ---------------------------------------------------------------


class Remoto:
    """Lê um PMTiles remoto por faixas de bytes, guardando cabeçalho e diretórios."""

    def __init__(self, url: str):
        self.url = url
        self.cache: dict[tuple[int, int], bytes] = {}
        self.header = deserialize_header(self.ler(0, 127))

    def ler(self, inicio: int, tamanho: int) -> bytes:
        r = baixar(self.url, headers={"Range": f"bytes={inicio}-{inicio + tamanho - 1}"}, timeout=120)
        return r.content

    def diretorio(self, inicio: int, tamanho: int):
        # o deserialize_directory do pmtiles já descompacta
        chave = (inicio, tamanho)
        if chave not in self.cache:
            self.cache[chave] = self.ler(inicio, tamanho)
        return deserialize_directory(self.cache[chave])

    def metadados(self) -> dict:
        h = self.header
        dado = self.ler(h["metadata_offset"], h["metadata_length"])
        if h["internal_compression"] == Compression.GZIP:
            dado = gzip.decompress(dado)
        return json.loads(dado)

    def ladrilho(self, tid: int) -> bytes | None:
        h = self.header
        inicio, tamanho = h["root_offset"], h["root_length"]
        for _ in range(4):
            e = find_tile(self.diretorio(inicio, tamanho), tid)
            if e is None:
                return None
            if e.run_length == 0:
                inicio, tamanho = h["leaf_directory_offset"] + e.offset, e.length
                continue
            return self.ler(h["tile_data_offset"] + e.offset, e.length)
        return None


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


def build_recente() -> str:
    hoje = dt.date.today()
    for d in range(0, 15):
        dia = (hoje - dt.timedelta(days=d)).strftime("%Y%m%d")
        r = S.head(PROTOMAPS.format(dia), timeout=30)
        if r.status_code == 200:
            return dia
    raise RuntimeError("não achei build do Protomaps nos últimos 15 dias")


def base(cod: str, caixa, dia: str) -> None:
    arq = SAIDA / f"base_{cod}.pmtiles"
    if arq.exists():
        return
    remoto = Remoto(PROTOMAPS.format(dia))
    x0, y0, x1, y1 = caixa
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    regiao = (cx - 6, cy - 5, cx + 6, cy + 5)
    # o zoom máximo cresce até uns 1.500 ladrilhos na caixa do município (São Félix: 12; município pequeno: 14)
    zmax = 9
    while zmax < 14 and len(ladrilhos_na_caixa(zmax + 1, caixa)) <= 1500:
        zmax += 1
    pedidos: list[tuple[int, int, int]] = []
    for z in range(0, 6):
        pedidos += ladrilhos_na_caixa(z, BRASIL)
    for z in range(6, 9):
        pedidos += ladrilhos_na_caixa(z, regiao)
    for z in range(9, zmax + 1):
        pedidos += ladrilhos_na_caixa(z, caixa)
    print(f" mapa base de {cod}: {len(pedidos)} ladrilhos, zoom 0 a {zmax} (build {dia})")
    ids = sorted({zxy_to_tileid(*p) for p in pedidos})
    with ThreadPoolExecutor(16) as ex:
        dados = list(ex.map(remoto.ladrilho, ids))
    meta = remoto.metadados()
    meta["attribution"] = meta.get("attribution") or '<a href="https://openstreetmap.org/copyright">© OpenStreetMap</a>'
    meta["description"] = f"Recorte para a Raíz (município {cod}) do build {dia} do Protomaps"
    h = remoto.header
    temp = arq.with_suffix(".tmp")
    with open(temp, "wb") as f:
        w = Writer(f)
        for tid, d in zip(ids, dados):
            if d:
                w.write_tile(tid, d)
        w.finalize(
            {
                "tile_type": TileType.MVT,
                "tile_compression": h["tile_compression"],
                "min_lon_e7": int(BRASIL[0] * 1e7),
                "min_lat_e7": int(BRASIL[1] * 1e7),
                "max_lon_e7": int(BRASIL[2] * 1e7),
                "max_lat_e7": int(BRASIL[3] * 1e7),
                "center_zoom": 9,
                "center_lon_e7": int(cx * 1e7),
                "center_lat_e7": int(cy * 1e7),
            },
            meta,
        )
    temp.rename(arq)
    print(f"   {arq.name}: {arq.stat().st_size / 1e6:.1f} MB")


FONTES = "https://protomaps.github.io/basemaps-assets/fonts/{}/{}.pbf"


def fontes() -> None:
    """Letras dos rótulos: Latim básico, Latim estendido e pontuação bastam para os nomes de lugar do Brasil."""
    for fonte in ("Noto Sans Regular", "Noto Sans Medium", "Noto Sans Italic"):
        pasta = SAIDA / "fontes" / fonte
        pasta.mkdir(parents=True, exist_ok=True)
        for faixa in ("0-255", "256-511", "7680-7935", "8192-8447"):
            arq = pasta / f"{faixa}.pbf"
            if not arq.exists():
                arq.write_bytes(baixar(FONTES.format(fonte.replace(" ", "%20"), faixa)).content)


def indice() -> None:
    itens: dict[str, dict] = {}
    for f in sorted(SAIDA.glob("*_*.*")):
        tipo, resto = f.stem.split("_", 1)
        if f.suffix not in (".geojson", ".pmtiles"):
            continue
        itens.setdefault(resto, {})[tipo] = {"arquivo": f.name, "bytes": f.stat().st_size}
    (SAIDA / "indice.json").write_text(
        json.dumps({"gerado_em": dt.datetime.now().isoformat(timespec="seconds"), "municipios": itens}, indent=1)
    )


def main(cods: list[str]) -> None:
    SAIDA.mkdir(exist_ok=True)
    dia = None
    for cod in cods:
        geom, nome = municipio(cod)
        print(f"{cod} {nome}")
        x0, y0, x1, y1 = geom.bounds
        caixa = (x0 - 0.05, y0 - 0.05, x1 + 0.05, y1 + 0.05)
        imoveis(cod)
        camada_tb(
            cod,
            "ti",
            "prodes-legal-amz:indigenous_area_legal_amazon",
            caixa,
            {"terrai_nom": "nome", "fase_ti": "fase"},
            0.0005,
        )
        camada_tb(
            cod,
            "uc",
            "prodes-legal-amz:conservation_units_legal_amazon",
            caixa,
            {"nome": "nome", "categoria": "categoria", "grupo": "grupo"},
            0.0005,
        )
        camada_tb(cod, "rios", "prodes-legal-amz:hydrography", caixa, {}, 0.0002)
        if not (SAIDA / f"base_{cod}.pmtiles").exists():
            dia = dia or build_recente()
            base(cod, caixa, dia)
    fontes()
    indice()


if __name__ == "__main__":
    main(sys.argv[1:] or ["1507300", "1504950"])
