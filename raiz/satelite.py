"""Imagem de satélite por fazenda (design v1 do front, item 1), gerada no servidor e guardada em cache.

Hoje: Copernicus Sentinel-2 L2A em COG aberto (catálogo STAC Earth Search da Element 84, coleção sentinel-2-l2a). Cena
mais recente dos últimos 3 meses sem nuvem sobre o imóvel (máscara SCL); se não houver, a mediana das cenas limpas do
trimestre. Cor natural (TCI: B4, B3, B2) levemente dessaturada, recorte com 15% de margem em volta do imóvel.
Passado: Landsat 5 (Collection 2 nível 2, domínio público, USGS) pelo Planetary Computer, 1985 e 2008, mesmo recorte.
Nada de EOX, Esri, Planet NICFI ou Google; nada de imagem gerada por IA (a simulação é uma textura desenhada).

Saídas em WebP (o peso é conferido nos testes):
- hoje: 1024 px, abaixo de 150 KB, sem desenho (o front desenha por cima);
- hoje-produtor: 720 px, contorno branco de 3 px com borda escura de 1 px, entorno escurecido 45%, área que pode
  voltar a ser mata em hachura diagonal, 40 a 80 KB;
- hoje-celular e simulacao: o par de 480 px; na simulação a área que pode voltar é pintada com textura de copa e o
  selo "Simulação" vai escrito na imagem;
- 1985 e 2008: Landsat no mesmo recorte.
Cada imagem grava a data da cena, o satélite e a frase de crédito (metadados.json ao lado).
"""

from __future__ import annotations

import datetime as dt
import io
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from raiz import RAIZ_REPO
from raiz.config import config

EARTH_SEARCH = "https://earth-search.aws.element84.com/v1/search"
PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
PC_SAS = "https://planetarycomputer.microsoft.com/api/sas/v1/token/landsat-c2-l2"
MARGEM = 0.15
SCL_NUVEM = (0, 1, 3, 8, 9, 10)  # sem dado, saturado, sombra de nuvem, nuvem média e alta, cirro
TIPOS = {
    "hoje": {"px": 1024, "max_kb": 150, "min_kb": 0},
    "hoje-produtor": {"px": 720, "max_kb": 80, "min_kb": 40},
    "hoje-celular": {"px": 480, "max_kb": 60, "min_kb": 0},
    "simulacao": {"px": 480, "max_kb": 60, "min_kb": 0},
    "1985": {"px": 720, "max_kb": 80, "min_kb": 0},
    "2008": {"px": 720, "max_kb": 80, "min_kb": 0},
}


@dataclass
class Cena:
    rgb: np.ndarray  # altura x largura x 3, uint8
    caixa: tuple[float, float, float, float]  # lon0, lat0, lon1, lat1 do recorte (EPSG:4326)
    data: str
    satelite: str
    credito: str
    metodo: str  # "cena" ou "mediana"


def pasta() -> Path:
    return Path(getattr(config(), "imagens_dir", None) or RAIZ_REPO / "dados" / "imagens")


def caixa_com_margem(geom, margem: float = MARGEM) -> tuple[float, float, float, float]:
    """Caixa do imóvel (lon/lat) com 15% de margem de cada lado, quadrada o bastante para não achatar o desenho."""
    x0, y0, x1, y1 = geom.bounds
    w, h = x1 - x0, y1 - y0
    lado = max(w, h * 1.0) * (1 + 2 * margem)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    lw = max(lado, w * (1 + 2 * margem))
    lh = max(h * (1 + 2 * margem), lado * 0.75)
    return cx - lw / 2, cy - lh / 2, cx + lw / 2, cy + lh / 2


# --- leitura das cenas --------------------------------------------------------------------------------------------


def _janela(href: str, caixa, banda_shape=None, indexes=None, resampling=None):
    """Lê o recorte (lon/lat) de um COG na grade dele (ou reamostrado para banda_shape)."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds

    with rasterio.open(href) as r:
        b = transform_bounds("EPSG:4326", r.crs, *caixa, densify_pts=21)
        w = from_bounds(*b, transform=r.transform).round_offsets().round_lengths()
        kw = {"window": w, "boundless": True, "fill_value": 0}
        if banda_shape is not None:
            kw["out_shape"] = (r.count if indexes is None else len(indexes), *banda_shape)
            kw["resampling"] = resampling or Resampling.nearest
        return r.read(indexes, **kw)


def _nuvem(scl: np.ndarray, geom_mask: np.ndarray | None = None) -> float:
    v = scl if geom_mask is None else scl[geom_mask]
    return float(np.isin(v, SCL_NUVEM).mean()) if v.size else 1.0


def buscar_sentinel(caixa, hoje: dt.date | None = None, cliente=None) -> list[dict]:
    import httpx

    hoje = hoje or dt.date.today()
    c = cliente or httpx.Client(timeout=60)
    ini = (hoje - dt.timedelta(days=92)).isoformat()
    corpo = {
        "collections": ["sentinel-2-l2a"],
        "bbox": list(caixa),
        "datetime": f"{ini}T00:00:00Z/{hoje.isoformat()}T23:59:59Z",
        "limit": 60,
        "query": {"eo:cloud_cover": {"lt": 90}},
        "sortby": [{"field": "properties.datetime", "direction": "desc"}],
    }
    r = c.post(EARTH_SEARCH, json=corpo)
    r.raise_for_status()
    return r.json()["features"]


def _cobre(item: dict, caixa) -> bool:
    import shapely
    from shapely.geometry import shape

    return shape(item["geometry"]).covers(shapely.box(*caixa))


def cena_sentinel(geom, hoje: dt.date | None = None, cliente=None, ler=None) -> Cena:
    """A cena mais recente sem nuvem sobre o imóvel; senão a mediana das cenas limpas do trimestre."""
    ler = ler or _janela
    caixa = caixa_com_margem(geom)
    itens = [i for i in buscar_sentinel(caixa, hoje, cliente) if _cobre(i, caixa)]
    if not itens:
        raise LookupError("nenhuma cena do Sentinel-2 cobre o imóvel nos últimos 3 meses")
    limpas = []
    for item in itens[:12]:
        rgb = ler(item["assets"]["visual"]["href"], caixa)
        scl = ler(item["assets"]["scl"]["href"], caixa, banda_shape=rgb.shape[1:])[0]
        frac = _nuvem(scl)
        data = item["properties"]["datetime"][:10]
        if frac < 0.01:
            return Cena(np.moveaxis(rgb, 0, -1).astype(np.uint8), caixa, data, _nome_s2(item), credito_s2(data), "cena")
        if frac < 0.6:
            limpas.append((rgb, scl, data, item))
        if len(limpas) >= 6:
            break
    if not limpas:
        raise LookupError("só cenas com nuvem sobre o imóvel nos últimos 3 meses")
    pilha = np.stack([np.where(np.isin(s, SCL_NUVEM)[None], np.nan, r.astype(float)) for r, s, _, _ in limpas])
    import warnings

    with warnings.catch_warnings():  # pixel com nuvem em todas as cenas fica sem dado (preto), sem aviso
        warnings.simplefilter("ignore", RuntimeWarning)
        med = np.nan_to_num(np.nanmedian(pilha, axis=0), nan=0).astype(np.uint8)
    datas = sorted(d for _, _, d, _ in limpas)
    return Cena(np.moveaxis(med, 0, -1), caixa, f"{datas[0]} a {datas[-1]}", "Sentinel-2", credito_s2(datas[-1]),
                "mediana")  # fmt: skip


def _nome_s2(item: dict) -> str:
    return {"sentinel-2a": "Sentinel-2A", "sentinel-2b": "Sentinel-2B", "sentinel-2c": "Sentinel-2C"}.get(
        str(item["properties"].get("platform", "")).lower(), "Sentinel-2"
    )


def credito_s2(data: str) -> str:
    return f"Contains modified Copernicus Sentinel data {data[:4]}"


def cena_landsat(geom, ano: int, cliente=None, ler=None) -> Cena:
    """Landsat 5 (C2 L2) do ano, a cena com menos nuvem sobre o imóvel na seca (junho a setembro, se houver)."""
    import httpx

    ler = ler or _janela
    c = cliente or httpx.Client(timeout=60)
    caixa = caixa_com_margem(geom)
    token = c.get(PC_SAS).json()["token"]
    corpo = {
        "collections": ["landsat-c2-l2"],
        "bbox": list(caixa),
        "datetime": f"{ano}-01-01T00:00:00Z/{ano}-12-31T23:59:59Z",
        "query": {"platform": {"eq": "landsat-5"}, "eo:cloud_cover": {"lt": 60}},
        "limit": 50,
    }
    r = c.post(PC_STAC, json=corpo)
    r.raise_for_status()
    itens = [i for i in r.json()["features"] if _cobre(i, caixa)]
    if not itens:
        raise LookupError(f"nenhuma cena Landsat 5 cobre o imóvel em {ano}")
    itens.sort(
        key=lambda i: (int(i["properties"]["datetime"][5:7]) not in range(6, 10), i["properties"]["eo:cloud_cover"])
    )
    melhor = None
    for item in itens[:6]:
        href = {k: f"{item['assets'][k]['href']}?{token}" for k in ("red", "green", "blue", "qa_pixel")}
        qa = ler(href["qa_pixel"], caixa)[0]
        nuvem = float((((qa >> 3) & 1) | ((qa >> 4) & 1) | (qa == 1)).mean())
        if melhor is None or nuvem < melhor[0]:
            melhor = (nuvem, item, href)
        if nuvem < 0.01:
            break
    _, item, href = melhor
    bandas = [ler(href[k], caixa)[0].astype(float) * 0.0000275 - 0.2 for k in ("red", "green", "blue")]
    rgb = np.stack([np.clip(np.power(np.clip(b / 0.25, 0, 1), 1 / 1.6) * 255, 0, 255) for b in bandas], axis=-1)
    data = item["properties"]["datetime"][:10]
    return Cena(rgb.astype(np.uint8), caixa, data, "Landsat 5", f"Landsat 5, cortesia do USGS ({data[:4]})", "cena")


# --- desenho e WebP -----------------------------------------------------------------------------------------------


def _para_px(geom, caixa, largura: int, altura: int):
    """Geometria lon/lat para pixels da imagem (y para baixo)."""
    import shapely

    x0, y0, x1, y1 = caixa
    return shapely.transform(geom, lambda c: np.c_[(c[:, 0] - x0) / (x1 - x0) * largura,
                                                   (y1 - c[:, 1]) / (y1 - y0) * altura])  # fmt: skip


def _aneis(g):
    import shapely

    for p in shapely.get_parts(g):
        if p.geom_type == "Polygon":
            yield [tuple(x) for x in p.exterior.coords]
            for i in p.interiors:
                yield [tuple(x) for x in i.coords]


def _mascara(img_size, g) -> object:
    from PIL import Image, ImageDraw

    m = Image.new("L", img_size, 0)
    d = ImageDraw.Draw(m)
    import shapely

    for p in shapely.get_parts(g):
        if p.geom_type != "Polygon":
            continue
        d.polygon([tuple(x) for x in p.exterior.coords], fill=255)
        for i in p.interiors:
            d.polygon([tuple(x) for x in i.coords], fill=0)
    return m


def _base(cena: Cena, px: int):
    from PIL import Image, ImageEnhance

    img = Image.fromarray(cena.rgb, "RGB")
    w, h = img.size
    f = px / max(w, h)
    img = img.resize((max(1, round(w * f)), max(1, round(h * f))), Image.LANCZOS)
    return ImageEnhance.Color(img).enhance(0.82)  # levemente dessaturada


def _hachura(tamanho, passo: int = 9):
    from PIL import Image, ImageDraw

    w, h = tamanho
    t = Image.new("RGBA", tamanho, (0, 0, 0, 0))
    d = ImageDraw.Draw(t)
    for k in range(-h, w, passo):
        d.line([(k, h), (k + h, 0)], fill=(255, 255, 255, 170), width=2)
    return t


def _copa(tamanho, semente: int = 7):
    """Textura de copa de árvore desenhada (manchas verdes), nunca foto gerada por IA."""
    from PIL import Image, ImageDraw, ImageFilter

    rng = np.random.default_rng(semente)
    w, h = tamanho
    t = Image.new("RGB", tamanho, (34, 85, 40))
    d = ImageDraw.Draw(t)
    for _ in range(int(w * h / 60)):
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        r = rng.uniform(2, 6)
        g = int(rng.uniform(70, 125))
        d.ellipse([x - r, y - r, x + r, y + r], fill=(int(g * 0.45), g, int(g * 0.4)))
    return t.filter(ImageFilter.GaussianBlur(0.6))


def _contorno(img, g):
    from PIL import ImageDraw

    d = ImageDraw.Draw(img)
    for anel in _aneis(g):
        d.line(anel, fill=(20, 24, 22), width=5, joint="curve")
    for anel in _aneis(g):
        d.line(anel, fill=(255, 255, 255), width=3, joint="curve")


def _selo(img, texto: str = "Simulação"):
    from PIL import ImageDraw, ImageFont

    d = ImageDraw.Draw(img)
    tam = max(14, img.size[0] // 22)
    try:
        fonte = ImageFont.truetype("DejaVuSans-Bold.ttf", tam)
    except OSError:
        fonte = ImageFont.load_default(size=tam)
    x0, y0, x1, y1 = d.textbbox((0, 0), texto, font=fonte)
    pad = tam // 2
    caixa = (12, 12, 12 + (x1 - x0) + 2 * pad, 12 + (y1 - y0) + 2 * pad)
    d.rounded_rectangle(caixa, radius=pad, fill=(255, 255, 255))
    d.text((12 + pad - x0, 12 + pad - y0), texto, fill=(20, 60, 30), font=fonte)


def desenhar(cena: Cena, tipo: str, imovel_geom, pode_voltar=None):
    """Imagem PIL do tipo pedido. imovel_geom e pode_voltar em lon/lat."""
    from PIL import Image

    px = TIPOS[tipo]["px"]
    img = _base(cena, px)
    if tipo == "hoje":
        return img
    g = _para_px(imovel_geom, cena.caixa, *img.size)
    dentro = _mascara(img.size, g)
    if tipo in ("hoje-produtor",):
        escuro = Image.eval(img, lambda v: int(v * 0.55))  # entorno escurecido 45%
        img = Image.composite(img, escuro, dentro)
    if pode_voltar is not None and not pode_voltar.is_empty:
        pv = _mascara(img.size, _para_px(pode_voltar, cena.caixa, *img.size))
        if tipo == "hoje-produtor":
            img.paste(_hachura(img.size), (0, 0), Image.composite(_hachura(img.size).getchannel("A"),
                                                                   Image.new("L", img.size, 0), pv))  # fmt: skip
        elif tipo == "simulacao":
            img = Image.composite(_copa(img.size), img, pv)
    if tipo in ("hoje-produtor", "hoje-celular", "simulacao"):
        _contorno(img, g)
    if tipo == "simulacao":
        _selo(img)
    return img


def webp(img, max_kb: float, min_kb: float = 0) -> bytes:
    """Maior qualidade que cabe no teto; se ficar abaixo do piso mesmo no máximo, sai a de qualidade máxima."""

    def enc(q):
        b = io.BytesIO()
        img.save(b, "WEBP", quality=q, method=6)
        return b.getvalue()

    lo, hi, melhor = 5, 95, None
    while lo <= hi:
        q = (lo + hi) // 2
        dado = enc(q)
        if len(dado) <= max_kb * 1024:
            melhor, lo = dado, q + 1
        else:
            hi = q - 1
    if melhor is None:  # nem a qualidade 5 coube: diminui a imagem
        menor = img.resize((max(1, img.size[0] * 3 // 4), max(1, img.size[1] * 3 // 4)))
        return webp(menor, max_kb, min_kb)
    return melhor


@dataclass
class Imagem:
    tipo: str
    arquivo: str
    data_cena: str
    satelite: str
    credito: str
    metodo: str
    caixa: list
    largura: int
    altura: int
    bytes: int
    gerado_em: str
    # miniatura de ~25 bytes (raiz/thumbhash.py): o borrão com as cores da foto enquanto ela carrega
    thumbhash: str | None = None


def salvar(pasta_imovel: Path, tipo: str, cena: Cena, img) -> Imagem:
    t = TIPOS[tipo]
    dado = webp(img, t["max_kb"], t["min_kb"])
    pasta_imovel.mkdir(parents=True, exist_ok=True)
    arq = pasta_imovel / f"{tipo}.webp"
    arq.write_bytes(dado)
    from PIL import Image

    w, h = Image.open(io.BytesIO(dado)).size
    from raiz.thumbhash import de_imagem

    meta = Imagem(tipo, arq.name, cena.data, cena.satelite, cena.credito, cena.metodo, list(cena.caixa), w, h,
                  len(dado), dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), de_imagem(img))  # fmt: skip
    mf = pasta_imovel / "metadados.json"
    tudo = json.loads(mf.read_text(encoding="utf-8")) if mf.exists() else {}
    tudo[tipo] = asdict(meta)
    mf.write_text(json.dumps(tudo, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def gerar(cod_busca: str, imovel_geom, pode_voltar=None, tipos=None, hoje=None, cliente=None, ler=None) -> dict:
    """Gera (e guarda) as imagens pedidas de um imóvel. Devolve os metadados por tipo."""
    tipos = tipos or list(TIPOS)
    p = pasta() / cod_busca
    out = {}
    s2 = None
    for tipo in tipos:
        if tipo in ("1985", "2008"):
            cena = cena_landsat(imovel_geom, int(tipo), cliente, ler)
        else:
            s2 = s2 or cena_sentinel(imovel_geom, hoje, cliente, ler)
            cena = s2
        out[tipo] = asdict(salvar(p, tipo, cena, desenhar(cena, tipo, imovel_geom, pode_voltar)))
    return out


def metadados(cod_busca: str) -> dict:
    f = pasta() / cod_busca / "metadados.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def capa(cod_busca: str, tipo: str = "hoje-produtor") -> dict | None:
    """A foto de capa da ficha (satélite com o contorno), se já foi gerada: caminho na API, ThumbHash, tamanho e
    crédito. Não gera nada (a geração é na rota da imagem). Imagem antiga sem ThumbHash ganha o dela aqui."""
    meta = metadados(cod_busca).get(tipo)
    arq = pasta() / cod_busca / f"{tipo}.webp"
    if not meta or not arq.exists():
        return None
    if not meta.get("thumbhash"):
        from PIL import Image

        from raiz.thumbhash import de_imagem

        with Image.open(arq) as im:
            meta["thumbhash"] = de_imagem(im)
        mf = pasta() / cod_busca / "metadados.json"
        tudo = json.loads(mf.read_text(encoding="utf-8"))
        tudo[tipo] = meta
        mf.write_text(json.dumps(tudo, ensure_ascii=False, indent=1), encoding="utf-8")
    return {
        "tipo": tipo,
        "caminho": f"imoveis/{cod_busca}/imagem/{tipo}.webp",
        "thumbhash": meta["thumbhash"],
        "largura": meta["largura"],
        "altura": meta["altura"],
        "data_cena": meta["data_cena"],
        "credito": meta["credito"],
    }


def km_por_px(caixa, largura: int) -> float:  # pragma: no cover - utilidade para a legenda de escala
    return (caixa[2] - caixa[0]) * 111.32 * math.cos(math.radians((caixa[1] + caixa[3]) / 2)) / largura
