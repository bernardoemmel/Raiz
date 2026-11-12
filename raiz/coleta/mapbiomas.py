"""MapBiomas sem Earth Engine, pela API da Plataforma (rodada 9; testado pelo fundador em 12/11/2026).

    base = https://prd.plataforma.mapbiomas.org/api/v1/brazil      cabeçalho tenant-id: mapbiomas (sem login)
    GET  {base}/territories/search/<nome>        -> município = categoria 230 (pega o id)
    POST {base}/maps/exports  {territoryId, subthemeKey, years}
    GET  {base}/maps/exports/{id}                 -> até status READY
    GET  {base}/maps/exports/{id}/download        -> ZIP com o GeoTIFF

O formato exato das respostas não está documentado: a leitura é tolerante (id em `id`/`exportId`, categoria em
`category`/`categoryId`/`category.id`) e falha com mensagem clara quando não acha. Transições de cobertura por imóvel
saem de dois anos do mesmo recorte (mesma grade), somando pixels por imóvel com numpy (sem Earth Engine).
"""

from __future__ import annotations

import io
import math
import time
import unicodedata
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests

from raiz.coleta.manifesto import carregar

FONTE = "mapbiomas_plataforma"


class ErroMapBiomas(RuntimeError):
    pass


def _cfg():
    f = carregar().fonte(FONTE)
    return (
        f.url.rstrip("/"),
        dict(f.model_extra.get("cabecalhos", {})),
        int(f.model_extra.get("categoria_municipio", 230)),
    )


def _itens(j) -> list[dict]:
    if isinstance(j, list):
        return j
    for k in ("data", "items", "territories", "results"):
        if isinstance(j, dict) and isinstance(j.get(k), list):
            return j[k]
    return []


def _categoria(item: dict):
    c = item.get("category", item.get("categoryId", item.get("category_id")))
    return c.get("id") if isinstance(c, dict) else c


def _sem_acento(t: str) -> str:
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()


def territorio_municipio(s: requests.Session, nome: str, uf: str | None = None, cod_ibge: int | None = None) -> int:
    base, cab, cat = _cfg()
    r = s.get(f"{base}/territories/search/{nome}", headers=cab, timeout=60)
    r.raise_for_status()
    cands = [i for i in _itens(r.json()) if str(_categoria(i)) == str(cat)]
    if cod_ibge is not None:  # se o IBGE vier em algum campo, ele decide
        por_cod = [i for i in cands if str(cod_ibge) in {str(v) for v in i.values()}]
        cands = por_cod or cands
    if len(cands) > 1 and uf:
        por_uf = [
            i
            for i in cands
            if uf.upper() in str(i.get("name", "")).upper() or uf.upper() in {str(v).upper() for v in i.values()}
        ]
        cands = por_uf or cands
    if len(cands) > 1:
        exato = [i for i in cands if _sem_acento(str(i.get("name", ""))).startswith(_sem_acento(nome))]
        cands = exato if len(exato) == 1 else cands
    if len(cands) != 1:
        raise ErroMapBiomas(f"território do município '{nome}' ({uf}): {len(cands)} candidatos na categoria {cat}")
    return int(cands[0]["id"])


def exportar(
    s: requests.Session,
    territorio: int,
    subtema: str,
    anos: list[int],
    espera_s: float = 10,
    limite_s: float = 1800,
    dormir=time.sleep,
) -> bytes:
    """Pede a exportação, espera ficar pronta e devolve o ZIP."""
    base, cab, _ = _cfg()
    r = s.post(
        f"{base}/maps/exports",
        json={"territoryId": territorio, "subthemeKey": subtema, "years": anos},
        headers=cab,
        timeout=60,
    )
    r.raise_for_status()
    j = r.json()
    eid = j.get("id", j.get("exportId")) if isinstance(j, dict) else None
    if eid is None:
        raise ErroMapBiomas(f"exportação sem id: {str(j)[:200]}")
    inicio = time.monotonic()
    while True:
        st = s.get(f"{base}/maps/exports/{eid}", headers=cab, timeout=60)
        st.raise_for_status()
        status = str((st.json() or {}).get("status", "")).upper()
        if status == "READY":
            break
        if status in {"ERROR", "FAILED", "CANCELED"}:
            raise ErroMapBiomas(f"exportação {eid} terminou em {status}")
        if time.monotonic() - inicio > limite_s:
            raise ErroMapBiomas(f"exportação {eid} não ficou pronta em {limite_s:.0f} s")
        dormir(espera_s)
    d = s.get(f"{base}/maps/exports/{eid}/download", headers=cab, timeout=600)
    d.raise_for_status()
    return d.content


def extrair_tifs(zip_bytes: bytes, pasta: Path) -> list[Path]:
    pasta.mkdir(parents=True, exist_ok=True)
    out = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for n in z.namelist():
            if n.lower().endswith((".tif", ".tiff")) and not n.startswith("__MACOSX"):
                destino = pasta / Path(n).name
                destino.write_bytes(z.read(n))
                out.append(destino)
    if not out:
        raise ErroMapBiomas("ZIP sem GeoTIFF")
    return sorted(out)


def _ha_pixel(transform, crs, linhas: np.ndarray) -> np.ndarray:
    if crs is not None and crs.is_projected:
        return np.full(linhas.shape, abs(transform.a * transform.e) / 1e4)
    lat = transform.f + (linhas + 0.5) * transform.e
    return abs(transform.a * 111_320 * transform.e * 110_574) * np.cos(np.radians(lat)) / 1e4


def transicoes(
    tif_de: str | Path,
    tif_para: str | Path,
    imoveis: gpd.GeoDataFrame,
    chave: str = "cod_imovel",
    banda_de: int = 1,
    banda_para: int = 1,
) -> pd.DataFrame:
    """Área (ha) de cada transição de classe (de -> para) dentro de cada imóvel. Os dois rasters precisam estar na
    mesma grade (mesmo recorte exportado). Imóvel sobreposto: vale o último desenhado (camadas separadas são a E2)."""
    import rasterio
    from rasterio.features import rasterize

    with rasterio.open(tif_de) as a, rasterio.open(tif_para) as b:
        if (a.transform, a.shape, a.crs) != (b.transform, b.shape, b.crs):
            raise ErroMapBiomas("os dois anos não estão na mesma grade")
        de, para = a.read(banda_de), b.read(banda_para)
        transform, crs = a.transform, a.crs
    g = imoveis.to_crs(crs) if crs is not None and imoveis.crs is not None else imoveis
    ids = np.arange(1, len(g) + 1, dtype=np.int64)
    rotulo = rasterize(
        zip(g.geometry.values, ids, strict=True), out_shape=de.shape, transform=transform, fill=0, dtype="int64"
    )
    dentro = rotulo > 0
    if not dentro.any():
        return pd.DataFrame(columns=[chave, "de", "para", "pixels", "ha"])
    linhas = np.nonzero(dentro)[0]
    df = pd.DataFrame(
        {
            "id": rotulo[dentro],
            "de": de[dentro].astype(int),
            "para": para[dentro].astype(int),
            "ha": _ha_pixel(transform, crs, linhas),
        }
    )
    t = df.groupby(["id", "de", "para"], as_index=False).agg(pixels=("ha", "size"), ha=("ha", "sum"))
    t[chave] = g[chave].to_numpy()[t["id"].to_numpy() - 1]
    t["ha"] = t.ha.round(4)
    return t[[chave, "de", "para", "pixels", "ha"]].sort_values([chave, "de", "para"]).reset_index(drop=True)


def area_por_pixel_aproximada(lat: float, res_graus: float) -> float:
    m = res_graus * 111_320
    return m * m * math.cos(math.radians(lat)) / 1e4
