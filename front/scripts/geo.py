"""Geometrias do front da Raíz, só de fontes públicas e sem nome, CPF ou CNPJ.

Uso (da raiz do repositório):
  node front/scripts/baixar-dados.mjs --geo --exigir
  python front/scripts/geo.py --dados dados/estados  # todos os municípios do Release
  python front/scripts/geo.py 1507300 1504950        # consulta direta antiga, para diagnóstico

Saída em front/geo/ (fora do git, é dado gerado e pode ser grande):
  municipio_<cod>.geojson   divisa do município (TerraBrasilis, municipalities_legal_amazon)
  imoveis_<cod>.geojson.gz  polígonos do GeoParquet do motor, só CAR e geometry, gzip lido no navegador
  ti_<cod>.geojson          terras indígenas na caixa do município (TerraBrasilis)
  uc_<cod>.geojson          unidades de conservação na caixa do município (TerraBrasilis)
  rios_<cod>.geojson        hidrografia do PRODES na caixa do município (a mesma que o motor usa para a APP)
  base_<UF>.pmtiles         fundo uniforme do estado até z10, compartilhado por todos os seus municípios
  fontes/<fonte>/<faixa>.pbf  letras dos rótulos do mapa (Noto Sans, licença OFL, do protomaps/basemaps-assets)
  brasil_municipios.geojson municípios do Brasil, simplificados para a escala do país (TerraBrasilis, por bioma)
  brasil_estados.geojson    os 27 estados (os mesmos municípios juntados), com o ponto do rótulo
  base_brasil.pmtiles       Brasil inteiro até z6, com overzoom; detalhe estadual sobreposto no navegador
E grava no front (vão para o git, são pequenos):
  compartilhado/brasil-estados.ts   contorno dos estados para o mini mapa (Natural Earth, domínio público)
  compartilhado/ibge-municipios.ts  códigos dos municípios de cada estado (DTB do IBGE), para saber se o estado está
                                    completo
  indice.json               o que já foi gerado, lido pelo front para saber o que existe

Roda de novo sem baixar o que já existe (apague o arquivo para baixar de novo).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from threading import Lock

import requests
import shapely
import shapely.ops
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
    dados = json.dumps({"type": "FeatureCollection", "features": feicoes}, separators=(",", ":")).encode()
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    temporario.write_bytes(gzip.compress(dados, mtime=0) if nome.endswith(".gz") else dados)
    temporario.replace(caminho)
    return caminho.stat().st_size


def feicao(geom, props: dict) -> dict:
    return {"type": "Feature", "properties": props, "geometry": mapping(geom)}


# --- divisa do município ------------------------------------------------------------------------------------------


def municipio(cod: str):
    arq = SAIDA / f"municipio_{cod}.geojson"
    if arq.exists():
        g = json.loads(arq.read_text())["features"][0]
        return shape(g["geometry"]), g["properties"]["nome"]
    nacional = SAIDA / "brasil_municipios.geojson"
    if nacional.exists():
        for f in json.loads(nacional.read_text())["features"]:
            if str(f["properties"]["cod_ibge"]) == cod:
                salvar(arq.name, [f])
                return shape(f["geometry"]), f["properties"]["nome"]
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


def imoveis(cod: str, uf: str | None = None) -> None:
    uf = (uf or UF_IBGE[cod[:2]]).lower()
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


def camada_tb(cod: str, nome: str, camada: str, caixa, campos: dict[str, str], tolerancia: float, dentro=None) -> None:
    """Baixa a camada na caixa do município. Com `dentro` (a divisa), recorta no contorno: terra indígena e unidade de
    conservação não podem aparecer fora do município no mapa (guia, item 3.3)."""
    arq = SAIDA / f"{nome}_{cod}.geojson"
    if arq.exists():
        if dentro is not None:
            recortar_no_municipio(arq, dentro)
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
        if dentro is not None:
            g = so_poligonos(arredondar(valido(g).intersection(dentro), 5))
            if g.is_empty:
                continue
        props = {novo: f["properties"].get(velho) for velho, novo in campos.items()}
        feicoes.append(feicao(g, props))
    tam = salvar(arq.name, feicoes)
    print(f"   {len(feicoes)} feições, {tam / 1e3:.0f} kB")


def so_poligonos(g):
    """Depois de um recorte, fica só o que tem área (o recorte pode deixar linhas e pontos soltos na divisa)."""
    if g.is_empty or g.geom_type in ("Polygon", "MultiPolygon"):
        return g
    partes = [p for p in getattr(g, "geoms", []) if p.geom_type in ("Polygon", "MultiPolygon")]
    return shapely.union_all(partes) if partes else shapely.Polygon()


def recortar_no_municipio(arq: Path, dentro) -> None:
    """Recorta no contorno do município um arquivo já baixado (gerado antes do recorte existir). Não baixa nada."""
    dados = json.loads(arq.read_text())
    feicoes, mudou = [], False
    for f in dados["features"]:
        g = shape(f["geometry"])
        if dentro.contains(g):
            feicoes.append(f)
            continue
        mudou = True
        r = so_poligonos(arredondar(valido(g).intersection(dentro), 5))
        if not r.is_empty:
            feicoes.append(feicao(r, f["properties"]))
    if mudou:
        salvar(arq.name, feicoes)
        print(f"   {arq.name}: recortado na divisa ({len(feicoes)} feições)")


# --- mapa base: recorte do build diário do Protomaps ---------------------------------------------------------------


class Remoto:
    """Lê um PMTiles remoto por faixas de bytes, guardando cabeçalho e diretórios."""

    def __init__(self, url: str):
        self.url = url
        self.cache: dict[tuple[int, int], list] = {}
        self.trava = Lock()
        self.header = deserialize_header(self.ler(0, 127))

    def ler(self, inicio: int, tamanho: int) -> bytes:
        r = baixar(self.url, headers={"Range": f"bytes={inicio}-{inicio + tamanho - 1}"}, timeout=120)
        if r.status_code != 206 or len(r.content) != tamanho:
            raise RuntimeError("o servidor do mapa não respeitou HTTP Range")
        return r.content

    def diretorio(self, inicio: int, tamanho: int):
        # o deserialize_directory do pmtiles já descompacta
        chave = (inicio, tamanho)
        with self.trava:
            if chave not in self.cache:
                # Interpretar uma vez: nos estados são milhares de tiles lendo os mesmos diretórios.
                self.cache[chave] = deserialize_directory(self.ler(inicio, tamanho))
            return self.cache[chave]

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


@lru_cache(maxsize=1)
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
        for tid, d in zip(ids, dados, strict=True):
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


MUNICIPIOS_BIOMA = [
    ("prodes-legal-amz", "municipalities_legal_amazon"),
    ("prodes-cerrado-nb", "municipalities_cerrado_biome"),
    ("prodes-caatinga-nb", "municipalities_caatinga_biome"),
    ("prodes-mata-atlantica-nb", "municipalities_mata_atlantica_biome"),
    ("prodes-pampa-nb", "municipalities_pampa_biome"),
    ("prodes-pantanal-nb", "municipalities_pantanal_biome"),
]
UF_IBGE = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO", "21": "MA", "22": "PI",
    "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA", "31": "MG", "32": "ES",
    "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}


def valido(g):
    """Conserta o polígono; se o make_valid recusar (mistura de dimensões), refaz com buffer(0). Fica só com área."""
    try:
        if not g.is_valid:
            g = shapely.make_valid(g)
    except Exception:  # noqa: BLE001
        g = g.buffer(0)
    if g.geom_type == "GeometryCollection":
        g = shapely.union_all([p for p in g.geoms if p.geom_type in ("Polygon", "MultiPolygon")])
    return g


def municipios_brasil() -> None:
    """Todos os municípios, para a tela de entrada: pintar o que já foi processado e deixar clicar em qualquer um."""
    arq = SAIDA / "brasil_municipios.geojson"
    if arq.exists():
        return
    cache = SAIDA / "cache"
    cache.mkdir(exist_ok=True)
    partes: dict[str, list] = {}
    nomes: dict[str, str] = {}
    for ws, camada in MUNICIPIOS_BIOMA:
        bruto = cache / f"{camada}.geojson"
        if not bruto.exists():
            print(f" municípios: {camada}")
            fs, inicio = [], 0
            while True:
                try:
                    r = baixar(
                        TB_WFS,
                        dict(
                            service="WFS",
                            version="2.0.0",
                            request="GetFeature",
                            typeNames=f"{ws}:{camada}",
                            outputFormat="application/json",
                            srsName="EPSG:4326",
                            count=500,
                            startIndex=inicio,
                            sortBy="geocodigo",
                        ),
                        timeout=900,
                    )
                except RuntimeError as ex:
                    # Não gravar o começo de uma camada como cache completo: a próxima rodada deve tentar de novo.
                    raise RuntimeError(f"limites incompletos em {camada}: {ex}") from ex
                lote = r.json()["features"]
                fs += lote
                if len(lote) < 500:
                    break
                inicio += 500
            bruto.write_text(json.dumps({"type": "FeatureCollection", "features": fs}))
        for f in json.loads(bruto.read_text())["features"]:
            p = f["properties"]
            cod = str(p.get("geocodigo") or "")[:7]
            if not cod or not f.get("geometry"):
                continue
            g = valido(shape(f["geometry"]))
            if g.is_empty:
                continue
            partes.setdefault(cod, []).append(g.simplify(0.003, preserve_topology=True))
            nomes[cod] = p.get("nome") or nomes.get(cod, "")
    feicoes = []
    for cod, gs in sorted(partes.items()):
        g = shapely.union_all(gs) if len(gs) > 1 else gs[0]
        g = arredondar(g.simplify(0.01, preserve_topology=True), 3)
        if g.is_empty:
            continue
        feicoes.append(feicao(g, {"cod_ibge": cod, "nome": nomes[cod], "uf": UF_IBGE.get(cod[:2], "")}))
    tam = salvar(arq.name, feicoes)
    print(f"   {len(feicoes)} municípios, {tam / 1e6:.1f} MB")


def estados_brasil() -> None:
    """Contorno dos 27 estados, juntando os municípios do TerraBrasilis (a divisa bate com a dos municípios), com o
    ponto do rótulo dentro de cada um. O mapa da entrada pinta o estado pela situação e aproxima nele ao tocar."""
    arq = SAIDA / "brasil_estados.geojson"
    if arq.exists():
        return
    cache = SAIDA / "cache"
    partes: dict[str, list] = {}
    for _, camada in MUNICIPIOS_BIOMA:
        bruto = cache / f"{camada}.geojson"
        if not bruto.exists():
            continue
        for f in json.loads(bruto.read_text())["features"]:
            cod = str(f["properties"].get("geocodigo") or "")[:7]
            uf = UF_IBGE.get(cod[:2])
            if uf and f.get("geometry"):
                g = valido(shape(f["geometry"]))
                if not g.is_empty:
                    partes.setdefault(uf, []).append(g)
    if not partes:
        print(" estados: falta o cache dos municípios (rode sem apagar front/geo/cache)")
        return
    feicoes = []
    for uf, gs in sorted(partes.items()):
        # as divisas dos municípios do mesmo estado coincidem: a união fecha sem fresta; o pequeno buffer cola o que
        # sobrar de diferença entre as camadas de bioma
        g = valido(shapely.union_all(gs).buffer(0.0005).buffer(-0.0005))
        g = arredondar(g.simplify(0.01, preserve_topology=True), 3)
        p = shapely.ops.polylabel(max(getattr(g, "geoms", [g]), key=lambda x: x.area), tolerance=0.01)
        feicoes.append(feicao(g, {
            "uf": uf,
            "cod": next(c for c, u in UF_IBGE.items() if u == uf),
            "rotulo": [round(p.x, 3), round(p.y, 3)],
        }))
    tam = salvar(arq.name, feicoes)
    print(f"   {len(feicoes)} estados, {tam / 1e6:.1f} MB")


DTB = "https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/divisao_territorial/"


def lista_ibge() -> None:
    """Lista oficial dos municípios por estado (Divisão Territorial Brasileira do IBGE, a mais recente), gravada no
    front: é com ela que o plugin de dados diz se o motor já processou o estado inteiro. Só códigos, sem nome."""
    import io
    import re
    import xml.etree.ElementTree as ET
    import zipfile

    destino = SAIDA.parent / "compartilhado" / "ibge-municipios.ts"
    anos = sorted(set(re.findall(r'href="(\d{4})/"', baixar(DTB, timeout=120).text)))
    for ano in reversed(anos):
        pasta = baixar(DTB + ano + "/", timeout=120).text
        nome = next(iter(re.findall(r'href="(DTB_\d{4}\.zip)"', pasta)), None)
        if nome:
            break
    else:
        raise RuntimeError("nenhuma DTB na pasta do IBGE")
    zipado = SAIDA / "cache" / nome
    if not zipado.exists():
        zipado.write_bytes(baixar(DTB + ano + "/" + nome, timeout=600).content)
    z = zipfile.ZipFile(zipado)
    planilha = next(n for n in z.namelist() if re.search(r"MUNICIPIOS\.ods$", n))
    ods = zipfile.ZipFile(io.BytesIO(z.read(planilha)))
    t = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
    por_uf: dict[str, list[str]] = {}
    data_base = ""
    for linha in ET.fromstring(ods.read("content.xml")).iter(t + "table-row"):
        celulas: list[str] = []
        for c in linha.findall(t + "table-cell"):
            celulas += ["".join(c.itertext())] * min(int(c.get(t + "number-columns-repeated", "1")), 20)
        if celulas and celulas[0].startswith("DATA BASE"):
            data_base = celulas[0].split(":", 1)[1].strip()
        # colunas pelo nome do cabeçalho seriam o certo, mas a planilha repete a linha de título; o código completo
        # do município é a única célula de 7 números da linha
        cod = next((c for c in celulas if re.fullmatch(r"\d{7}", c)), None)
        if cod and cod[:2] in UF_IBGE:
            por_uf.setdefault(UF_IBGE[cod[:2]], []).append(cod)
    total = sum(len(v) for v in por_uf.values())
    if total < 5500:
        raise RuntimeError(f"a DTB {ano} veio com {total} municípios; esperava uns 5.570")
    linhas = [
        "/**",
        f" * Municípios por UF pela Divisão Territorial Brasileira do IBGE ({nome[:-4].replace('_', ' ')}, data base",
        f" * {data_base}): {total:,} municípios.".replace(",", "."),
        " * Gerado por front/scripts/geo.py; não editar à mão.",
        " * O plugin de dados compara com o que o motor processou para dizer se o estado está completo.",
        " * Só os códigos: os 2 primeiros números são os do estado e ficam de fora para o arquivo ficar pequeno.",
        " */",
        "",
        f'export const LISTA_IBGE = "{nome[:-4].replace("_", " ")} (data base {data_base})"',
        "",
        "const CODIGOS: Record<string, string> = {",
        *[f'  {uf}: "{" ".join(c[2:] for c in sorted(cs))}",' for uf, cs in sorted(por_uf.items())],
        "}",
        "",
        "const UF_COD: Record<string, string> = {",
        *[f'  {uf}: "{cs[0][:2]}",' for uf, cs in sorted(por_uf.items())],
        "}",
        "",
        "/** os códigos IBGE (7 números) dos municípios do estado, ou [] se a sigla não existe */",
        "export function municipiosDoEstado(uf: string): string[] {",
        "  const lista = CODIGOS[uf]",
        '  return lista ? lista.split(" ").map((c) => UF_COD[uf] + c) : []',
        "}",
        "",
    ]
    destino.write_text("\n".join(linhas))
    print(f" lista do IBGE: {total} municípios ({nome}), {destino.stat().st_size / 1e3:.0f} kB em {destino.name}")


NATURAL_EARTH = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_1_states_provinces.geojson"


def estados_svg() -> None:
    """Contorno dos estados em SVG para o mini mapa do Brasil (Natural Earth, domínio público), gravado no front."""
    destino = SAIDA.parent / "compartilhado" / "brasil-estados.ts"
    r = baixar(NATURAL_EARTH, timeout=300)
    estados = [f for f in r.json()["features"] if f["properties"].get("adm0_a3") == "BRA"]
    lat0 = -15.0
    k = math.cos(math.radians(lat0))
    geoms = {f["properties"]["postal"]: shape(f["geometry"]).simplify(0.12, preserve_topology=True) for f in estados}
    x0, y0, x1, y1 = shapely.union_all(list(geoms.values())).bounds
    largura = 120.0
    escala = largura / ((x1 - x0) * k)
    altura = (y1 - y0) * escala

    def caminho(g) -> str:
        poligonos = [g] if g.geom_type == "Polygon" else list(g.geoms)
        partes = []
        for p in poligonos:
            pts = [((x - x0) * k * escala, (y1 - y) * escala) for x, y in p.exterior.coords]
            partes.append("M" + "L".join(f"{a:.1f},{b:.1f}" for a, b in pts) + "Z")
        return "".join(partes)

    linhas = [
        "/**",
        " * Contorno dos estados do Brasil para o mini mapa (guia, item 2.1, parte 8).",
        " * Gerado por front/scripts/geo.py a partir do Natural Earth 1:50m (domínio público). Não editar à mão.",
        " */",
        "",
        f"export const LARGURA = {largura:.0f}",
        f"export const ALTURA = {altura:.1f}",
        "",
        "/** lon/lat para a posição no desenho (a mesma projeção do contorno) */",
        "export function projetar(lon: number, lat: number): [number, number] {",
        f"  return [(lon - ({x0:.4f})) * {k * escala:.5f}, ({y1:.4f} - lat) * {escala:.5f}]",
        "}",
        "",
        "export const ESTADOS: Record<string, string> = {",
    ]
    for uf in sorted(geoms):
        linhas.append(f'  {uf}: "{caminho(geoms[uf])}",')
    linhas.append("}")
    destino.write_text("\n".join(linhas) + "\n")
    print(f" mini mapa: {len(geoms)} estados, {destino.stat().st_size / 1e3:.0f} kB em {destino.name}")


def base_regiao(nome: str, caixa, dia: str | None, zoom: int) -> None:
    """Cobertura uniforme: todos os tiles até zoom; o navegador pode fazer overzoom sem buracos.

    Um arquivo por UF evita repetir o fundo de municípios vizinhos. Tiles são gravados em ordem,
    em lotes de 128, para não manter o mapa de um estado inteiro na memória.
    """
    arq = SAIDA / nome
    if arq.exists():
        with arq.open("rb") as f:
            h = deserialize_header(f.read(127))
        if h["max_zoom"] == zoom:
            return
    dia = dia or build_recente()
    remoto = Remoto(PROTOMAPS.format(dia))
    ids = sorted({zxy_to_tileid(*p) for z in range(zoom + 1) for p in ladrilhos_na_caixa(z, caixa)})
    print(f" {nome}: {len(ids)} ladrilhos, cobertura uniforme até zoom {zoom} (build {dia})", flush=True)
    meta = remoto.metadados()
    meta["attribution"] = '<a href="https://openstreetmap.org/copyright">© OpenStreetMap</a>'
    meta["description"] = f"Recorte uniforme para a Raíz, build {dia} do Protomaps"
    temporario = arq.with_suffix(".tmp")
    with temporario.open("wb") as f, ThreadPoolExecutor(16) as ex:
        w = Writer(f)
        for inicio in range(0, len(ids), 128):
            lote = ids[inicio:inicio + 128]
            for tid, dado in zip(lote, ex.map(remoto.ladrilho, lote), strict=True):
                if dado:
                    w.write_tile(tid, dado)
            if inicio % 1024 == 0:
                print(f"   {nome}: {min(inicio + 128, len(ids))}/{len(ids)} ladrilhos", flush=True)
        w.finalize(
            {
                "tile_type": TileType.MVT,
                "tile_compression": remoto.header["tile_compression"],
                "min_lon_e7": int(caixa[0] * 1e7),
                "min_lat_e7": int(caixa[1] * 1e7),
                "max_lon_e7": int(caixa[2] * 1e7),
                "max_lat_e7": int(caixa[3] * 1e7),
                "center_zoom": min(zoom, 4),
                "center_lon_e7": int((caixa[0] + caixa[2]) / 2 * 1e7),
                "center_lat_e7": int((caixa[1] + caixa[3]) / 2 * 1e7),
            },
            meta,
        )
    temporario.replace(arq)
    print(f"   {arq.name}: {arq.stat().st_size / 1e6:.1f} MB", flush=True)


def base_brasil(dia: str | None, cods: list[str] | None = None) -> None:
    """País inteiro até z6; o detalhe de cada UF é uma segunda fonte, nunca buracos neste arquivo."""
    base_regiao("base_brasil.pmtiles", BRASIL, dia, 6)


def indice(cods: list[str] | None = None, falhas: dict[str, str] | None = None) -> None:
    itens: dict[str, dict] = {}
    for f in sorted(SAIDA.glob("*_*.*")):
        nome = f.name.removesuffix(".gz")
        stem, extensao = nome.rsplit(".", 1)
        if stem.startswith("brasil_") or stem == "base_brasil":
            continue
        tipo, resto = stem.split("_", 1)
        if extensao not in ("geojson", "pmtiles") or not (len(resto) == 7 and resto.isdigit()):
            continue
        if cods is not None and resto not in cods:
            continue
        itens.setdefault(resto, {})[tipo] = {"arquivo": f.name, "bytes": f.stat().st_size}
    for cod in cods or []:
        uf = UF_IBGE[cod[:2]]
        arq = SAIDA / f"base_{uf}.pmtiles"
        if arq.exists():
            itens.setdefault(cod, {})["base"] = {"arquivo": arq.name, "bytes": arq.stat().st_size}
    brasil = {
        nome: {"arquivo": arq, "bytes": (SAIDA / arq).stat().st_size}
        for nome, arq in (
            ("municipios", "brasil_municipios.geojson"),
            ("estados", "brasil_estados.geojson"),
            ("base", "base_brasil.pmtiles"),
        )
        if (SAIDA / arq).exists()
    }
    (SAIDA / "indice.json").write_text(
        json.dumps(
            {
                "gerado_em": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                "brasil": brasil,
                "municipios": itens,
                "sem_contorno": {cod: motivo for cod, motivo in (falhas or {}).items()},
            },
            indent=1,
        )
    )


def municipios_publicados(dados: Path) -> dict[str, Path]:
    """Só municípios com dados por fazenda; a lista vem do Release, nunca de dois códigos fixos."""
    manifesto = dados / "estados.json"
    ufs = json.loads(manifesto.read_text())["estados"] if manifesto.exists() else UF_IBGE.values()
    return {
        f.stem.removeprefix("imoveis_"): f
        for uf in sorted(ufs)
        for f in sorted((dados / uf).glob("imoveis_???????.csv"))
        if f.stem.removeprefix("imoveis_").isdigit()
    }


def exportar_geometria(csv_imoveis: Path, cache: dict) -> tuple[int, int]:
    """GeoParquet do próprio Release; expõe só CAR e contorno, preservando inclusive áreas pequenas."""
    import geopandas as gpd

    cod = csv_imoveis.stem.removeprefix("imoveis_")
    origem = csv_imoveis.with_name(f"geo_{cod}.parquet")
    if not origem.exists():
        raise FileNotFoundError("o Release ainda não contém o desenho deste município")
    destino = SAIDA / f"imoveis_{cod}.geojson.gz"
    assinatura = hashlib.sha256(origem.read_bytes() + csv_imoveis.read_bytes()).hexdigest()
    if cache.get(cod, {}).get("sha256") == assinatura and destino.exists():
        return cache[cod]["imoveis"], destino.stat().st_size
    with csv_imoveis.open(encoding="utf-8-sig", newline="") as f:
        existentes = {linha["cod_imovel"] for linha in csv.DictReader(f)}
    dados = gpd.read_parquet(origem, columns=["cod_imovel", "geometry"]).to_crs(4326)
    feicoes, vistos = [], set()
    for car, bruto in zip(dados.cod_imovel, dados.geometry, strict=True):
        if car not in existentes or car in vistos or bruto is None or bruto.is_empty:
            continue
        geom = so_poligonos(valido(bruto))
        if geom.is_empty:
            continue
        menor = arredondar(geom.simplify(0.00002, preserve_topology=True), 6)
        # A simplificação nunca pode eliminar uma fazenda pequena.
        feicoes.append(feicao(menor if not menor.is_empty else geom, {"cod_imovel": car}))
        vistos.add(car)
    if existentes and not feicoes:
        raise ValueError("o desenho publicado não contém nenhum dos CARs da tabela")
    tamanho = salvar(destino.name, feicoes)
    # Um cache antigo não deve fazer o build duplicar os polígonos ou criar centenas de milhares de fichas.
    (SAIDA / f"imoveis_{cod}.geojson").unlink(missing_ok=True)
    cache[cod] = {"sha256": assinatura, "imoveis": len(feicoes), "sem_geometria": len(existentes - vistos)}
    return len(feicoes), tamanho


def conferir_limites(publicados: dict[str, Path], fronteiras: dict, estados: list[dict] | None = None) -> None:
    """Cache antigo podia ter sido gravado pela metade após uma falha do WFS. Não publicar essa lacuna."""
    faltantes = set(publicados) - fronteiras.keys()
    ufs_ausentes = set()
    if estados is not None:
        ufs_ausentes = {UF_IBGE[cod[:2]] for cod in publicados} - {f["properties"]["uf"] for f in estados}
    if not faltantes and not ufs_ausentes:
        return
    # Dados gerados, nunca fontes do motor: a rodada seguinte refaz o cache em vez de repetir a lacuna para sempre.
    for nome in ("brasil_municipios.geojson", "brasil_estados.geojson"):
        (SAIDA / nome).unlink(missing_ok=True)
    for _, camada in MUNICIPIOS_BIOMA:
        (SAIDA / "cache" / f"{camada}.geojson").unlink(missing_ok=True)
    raise RuntimeError(
        f"limites nacionais incompletos: municípios {sorted(faltantes)}, UFs {sorted(ufs_ausentes)}; "
        "cache parcial invalidado para nova tentativa"
    )


def do_release(dados: Path, sem_base: bool = False) -> None:
    """Gera o desenho de todo município publicado, sem repetir o download do CAR feito pelo motor."""
    SAIDA.mkdir(parents=True, exist_ok=True)
    publicados = municipios_publicados(dados)
    if not publicados:
        raise RuntimeError(f"nenhum município publicado em {dados}; o site não será substituído pela amostra")
    caminho_cache = SAIDA / "cache" / "exportacao-v1.json"
    caminho_cache.parent.mkdir(exist_ok=True)
    cache = json.loads(caminho_cache.read_text()) if caminho_cache.exists() else {}
    falhas = {}
    total = 0
    for cod, csv_imoveis in publicados.items():
        try:
            quantidade, tamanho = exportar_geometria(csv_imoveis, cache)
            total += tamanho
            print(f" {cod}: {quantidade} desenhos, {tamanho / 1e6:.2f} MB gzip", flush=True)
        except (FileNotFoundError, ValueError) as ex:
            falhas[cod] = str(ex)
            # Não anunciar como atual um arquivo velho de um município cujo pacote mudou ou falta.
            for sufixo in (".geojson", ".geojson.gz"):
                (SAIDA / f"imoveis_{cod}{sufixo}").unlink(missing_ok=True)
            print(f"::warning::{cod}: {ex}", flush=True)
        caminho_cache.write_text(json.dumps(cache))
    municipios_brasil()
    estados_brasil()
    fronteiras = {
        str(f["properties"]["cod_ibge"]): f
        for f in json.loads((SAIDA / "brasil_municipios.geojson").read_text())["features"]
    }
    estados = json.loads((SAIDA / "brasil_estados.geojson").read_text())["features"]
    conferir_limites(publicados, fronteiras, estados if not sem_base else None)
    for cod in publicados:
        if cod in fronteiras and not (SAIDA / f"municipio_{cod}.geojson").exists():
            salvar(f"municipio_{cod}.geojson", [fronteiras[cod]])
    if not sem_base:
        fontes()
        dia = None  # só procura um build remoto se alguma base ainda não estiver no cache
        base_brasil(dia)
        ufs = {UF_IBGE[cod[:2]] for cod in publicados}
        for f in estados:
            uf = f["properties"]["uf"]
            if uf in ufs:
                caixa = shape(f["geometry"]).bounds
                # Margem para rios/estradas na borda e cobertura até z10 em todo estado, sem municípios em branco.
                caixa = (caixa[0] - .05, caixa[1] - .05, caixa[2] + .05, caixa[3] + .05)
                base_regiao(f"base_{uf}.pmtiles", caixa, dia, 10)
    # Retira bases municipais duplicadas do cache antigo. O índice aponta todos para a mesma base estadual.
    for arq in SAIDA.glob("base_???????.pmtiles"):
        arq.unlink()
    indice(list(publicados), falhas)
    print(f" {len(publicados) - len(falhas)}/{len(publicados)} municípios com desenho; {total / 1e6:.1f} MB gzip")


def main(cods: list[str]) -> None:
    SAIDA.mkdir(exist_ok=True)
    dia = None
    falhas = []
    for cod in cods:
        try:
            dia = um_municipio(cod, dia)
        except Exception as ex:  # noqa: BLE001
            # servidor fora (CAR, TerraBrasilis): segue com o resto; na próxima rodada tenta de novo o que faltou
            print(f"   {cod} não saiu agora: {str(ex)[:160]}")
            falhas.append(cod)
    fontes()
    municipios_brasil()
    estados_brasil()
    if not (SAIDA.parent / "compartilhado" / "ibge-municipios.ts").exists():
        lista_ibge()
    if not (SAIDA.parent / "compartilhado" / "brasil-estados.ts").exists():
        estados_svg()
    if not (SAIDA / "base_brasil.pmtiles").exists():
        base_brasil(dia or build_recente(), cods)
    indice()
    if falhas:
        print(f"Faltaram {len(falhas)} município(s): {', '.join(falhas)}")


def um_municipio(cod: str, dia):
    """Divisa, imóveis do CAR, terra indígena, UC, rios e o recorte do mapa base de um município."""
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
        dentro=geom,
    )
    camada_tb(
        cod,
        "uc",
        "prodes-legal-amz:conservation_units_legal_amazon",
        caixa,
        {"nome": "nome", "categoria": "categoria", "grupo": "grupo"},
        0.0005,
        dentro=geom,
    )
    camada_tb(cod, "rios", "prodes-legal-amz:hydrography", caixa, {}, 0.0002)
    if not (SAIDA / f"base_{cod}.pmtiles").exists():
        dia = dia or build_recente()
        base(cod, caixa, dia)
    return dia


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("codigos", nargs="*")
    parser.add_argument("--dados", type=Path, help="pasta dos CSV e GeoParquet baixados do Release")
    parser.add_argument("--sem-base", action="store_true", help="só exportar os desenhos, sem baixar o fundo")
    args = parser.parse_args()
    if args.dados:
        do_release(args.dados, sem_base=args.sem_base)
    elif args.codigos:
        main(args.codigos)
    else:
        parser.error("informe --dados <pasta do Release> ou códigos IBGE explícitos")
