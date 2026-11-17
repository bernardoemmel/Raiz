"""TerraClass (INPE/Embrapa) por imóvel: pasto sujo (pastagem arbustiva/arbórea), pasto limpo (herbácea) e vegetação
secundária. O MapBiomas chama tudo de "pastagem"; o TerraClass separa o pasto que já está virando mato, o que muda o
custo (regeneração assistida é mais barata que plantio) e a adicionalidade (a linha de base dinâmica da VM0047 desconta
o que regeneraria sozinho).

Entrada: GeoTIFFs em cache/ambiental/terraclass/ chamados terraclass_<bioma>_<ano>[_<recorte>].tif, cada um com a
legenda ao lado (mesmo nome, .json: {"<valor>": "<nome da classe>"}). Sem legenda, usa a legenda de reserva do
TerraClass Amazônia (raiz/regras/padroes/ambiental.yaml). As classes são casadas pelo NOME (sem acento), não pelo
número, porque Amazônia e Cerrado numeram diferente.
Sem arquivo que cubra o imóvel: colunas vazias e a fonte entra em ambiental_nao_verificadas (o TerraClass é
complemento: não impede o "livre").
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

COLUNAS = ("tc_pasto_sujo_ha", "tc_pasto_limpo_ha", "tc_vegetacao_secundaria_ha")
_NOME = re.compile(r"terraclass_(?P<bioma>[a-z_]+?)_(?P<ano>\d{4})(?:_.+)?\.tif$", re.I)


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper()


def arquivos(pasta: Path) -> list[dict]:
    """Os rasters do TerraClass na pasta, do ano mais novo para o mais velho."""
    out = []
    for f in sorted(Path(pasta).glob("terraclass_*.tif")) if Path(pasta).exists() else []:
        m = _NOME.match(f.name)
        if m:
            out.append({"arquivo": f, "bioma": m["bioma"].lower(), "ano": int(m["ano"])})
    return sorted(out, key=lambda d: -d["ano"])


def legenda(arquivo: Path, regra: dict) -> dict[int, str]:
    j = Path(arquivo).with_suffix(".json")
    if j.exists():
        return {int(k): _norm(v) for k, v in json.loads(j.read_text(encoding="utf-8")).items()}
    return {int(k): _norm(v) for k, v in regra["terraclass"]["legenda_amazonia"].items()}


def grupos(leg: dict[int, str], regra: dict) -> dict[str, list[int]]:
    """valores do raster de cada grupo (pasto_sujo, pasto_limpo, vegetacao_secundaria), pelo nome da classe."""
    tc = regra["terraclass"]
    out = {}
    for g in ("pasto_sujo", "pasto_limpo", "vegetacao_secundaria"):
        chaves = [_norm(x) for x in tc[g]]
        out[g] = [v for v, nome in leg.items() if any(c in nome for c in chaves)]
    return out


def por_imovel(car, pasta: Path, regra: dict) -> pd.DataFrame:
    """Hectares de cada grupo por imóvel, do arquivo mais novo que cobre cada um (tc_ano e tc_fonte dizem qual)."""
    import rasterio
    from rasterio.features import geometry_mask
    from rasterio.windows import from_bounds

    car = car[["cod_imovel", "geometry"]].reset_index(drop=True)
    out = pd.DataFrame({"cod_imovel": car.cod_imovel.astype(str).values})
    for c in COLUNAS:
        out[c] = np.nan
    out["tc_ano"] = pd.array([pd.NA] * len(out), dtype="Int64")
    out["tc_fonte"] = None
    feito = np.zeros(len(car), bool)
    for a in arquivos(pasta):
        if feito.all():
            break
        gr = grupos(legenda(a["arquivo"], regra), regra)
        with rasterio.open(a["arquivo"]) as src:
            g = car.to_crs(src.crs)
            geografico = bool(src.crs and src.crs.is_geographic)
            b = src.bounds
            for i, geom in enumerate(g.geometry.values):
                if feito[i] or geom is None or geom.is_empty:
                    continue
                x0, y0, x1, y1 = geom.bounds
                if x1 < b.left or x0 > b.right or y1 < b.bottom or y0 > b.top:
                    continue
                w0 = from_bounds(x0, y0, x1, y1, src.transform)
                c0, r0 = int(np.floor(w0.col_off)), int(np.floor(w0.row_off))
                c1, r1 = int(np.ceil(w0.col_off + w0.width)), int(np.ceil(w0.row_off + w0.height))
                w = rasterio.windows.Window(c0, r0, c1 - c0, r1 - r0)
                w = w.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
                if w.width <= 0 or w.height <= 0:
                    continue
                arr = src.read(1, window=w)
                tr = src.window_transform(w)
                m = ~geometry_mask([geom], out_shape=arr.shape, transform=tr, all_touched=False)
                if not m.any():  # imóvel menor que um pixel: usa o que toca
                    m = ~geometry_mask([geom], out_shape=arr.shape, transform=tr, all_touched=True)
                if src.nodata is not None and (arr[m] == src.nodata).all():
                    continue
                if geografico:
                    lat = tr.f + tr.e * (np.arange(arr.shape[0]) + 0.5)
                    cel = (abs(tr.a) * 111320.0 * np.cos(np.radians(lat)) * abs(tr.e) * 110574.0 / 1e4)[:, None]
                    area = np.broadcast_to(cel, arr.shape)
                else:
                    area = np.full(arr.shape, abs(tr.a * tr.e) / 1e4)
                for nome, col in zip(("pasto_sujo", "pasto_limpo", "vegetacao_secundaria"), COLUNAS, strict=True):
                    out.loc[i, col] = round(float(area[m & np.isin(arr, gr[nome])].sum()), 4)
                out.loc[i, "tc_ano"] = a["ano"]
                out.loc[i, "tc_fonte"] = f"terraclass_{a['bioma']}_{a['ano']}"
                feito[i] = True
    return out
