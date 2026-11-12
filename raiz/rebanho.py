"""Rebanho por fazenda e metano do gado (E4), fora do motor (motor/ não se edita).

O total de bovinos do município na Pesquisa da Pecuária Municipal (PPM, IBGE) é espalhado pelas fazendas do CAR pelo
pasto de cada uma vezes a produtividade do pasto (uGPP do Global Pasture Watch; sem ela, o vigor do MapBiomas), com o
total do município preservado e cabeças inteiras (resto maior). A faixa P10 a P90 sai de três desenhos do peso (sem a
produtividade, com ela e com ela ao quadrado) e do erro do total do município (o Censo Agro 2017 contra a PPM de 2017,
levado à PPM de hoje). Metano: Tier 1 do
IPCC por cabeça, em CO2 equivalente.

Grava rebanho_<mun>.csv (docs/colunas.md), lido pelo nome no vazamento (cabeças que saem da área restaurada) e em quem
compra (E6). Pequena nunca sai: toda fazenda com pasto recebe a sua parte. Sem nome, CPF ou CNPJ.
"""

from __future__ import annotations

import hashlib
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

PADROES = Path(__file__).parent / "regras" / "padroes"
ARQ_REGRA = PADROES / "rebanho.yaml"


@lru_cache(maxsize=4)
def _ler(arq: str, _marca: float) -> dict:
    r = yaml.safe_load(Path(arq).read_text(encoding="utf-8"))
    h = hashlib.sha256(Path(arq).read_bytes())
    h.update((PADROES / r["ppm"]["arquivo"]).read_bytes())
    r["versao_completa"] = f"{r['versao']}+{h.hexdigest()[:8]}"
    return r


def regra(arq: Path | None = None) -> dict:
    a = Path(arq or ARQ_REGRA)
    return _ler(str(a), a.stat().st_mtime)


def versao() -> str:
    return regra()["versao_completa"]


@lru_cache(maxsize=2)
def _ppm(arquivo: str) -> dict[int, tuple[float | None, float | None]]:
    import pandas as pd

    t = pd.read_csv(PADROES / arquivo)
    a, b = (c for c in t.columns if c.startswith("bovinos_"))
    return {int(c): (None if pd.isna(x) else float(x), None if pd.isna(y) else float(y))
            for c, x, y in zip(t.cod_ibge, t[a], t[b], strict=True)}  # fmt: skip


def bovinos_municipio(cod: int, r: dict | None = None) -> tuple[float | None, float | None]:
    """Cabeças de bovinos no município: PPM do ano corrente e do ano do Censo."""
    r = r or regra()
    return _ppm(r["ppm"]["arquivo"]).get(int(cod), (None, None))


@lru_cache(maxsize=2)
def _censo(arquivo: str) -> dict[int, float]:
    import pandas as pd

    t = pd.read_csv(PADROES / arquivo)
    return {int(c): float(v) for c, v in zip(t.cod_ibge, t.bovinos_cab, strict=True) if pd.notna(v) and v > 0}


def censo_2017(cod: int, r: dict | None = None) -> float | None:
    """Bovinos no Censo Agro 2017 (a mesma tabela da âncora do gado do valor para quem restaura)."""
    r = r or regra()
    return _censo(r["ppm"]["censo_arquivo"]).get(int(cod))


def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def pasto(linha: dict) -> float:
    """Pasto da fazenda (MapBiomas do ano mais novo; sem ele, o pasto do motor), lido pelo nome."""
    import re

    anos = sorted(int(m.group(1)) for k in linha if (m := re.fullmatch(r"mb_pasto_(\d{4})_ha", str(k))))
    for a in reversed(anos):
        x = _num(linha.get(f"mb_pasto_{a}_ha"))
        if x is not None:
            return max(x, 0.0)
    return max(_num(linha.get("pasto_ha")) or 0.0, 0.0)


def produtividade(linhas: list[dict], r: dict) -> tuple[np.ndarray, list[str]]:
    """Produtividade relativa do pasto de cada fazenda (média 1 no município): uGPP do GPW; sem ela, o vigor."""
    ug = np.array([_num(li.get("gpw_ugpp")) for li in linhas], dtype=float)
    vig = r["espalhar"]["vigor_relativo"]
    out, fonte = np.ones(len(linhas)), ["neutra"] * len(linhas)
    ok = np.isfinite(ug) & (ug > 0)
    if ok.any():
        out[ok] = ug[ok] / np.nanmean(ug[ok])
        for i in np.flatnonzero(ok):
            fonte[i] = "gpw"
    for i, li in enumerate(linhas):
        if ok[i]:
            continue
        v = _num(li.get("mb_pasto_vigor_principal"))
        if v is not None and int(round(v)) in {int(k) for k in vig}:
            out[i] = float({int(k): x for k, x in vig.items()}[int(round(v))])
            fonte[i] = "vigor"
    return out, fonte


def inteiros(x: np.ndarray, total: int) -> np.ndarray:
    """Cabeças inteiras que somam o total (resto maior, como o IntPopGrids)."""
    if total <= 0 or x.sum() <= 0:
        return np.zeros(len(x), dtype=int)
    alvo = x / x.sum() * total
    base = np.floor(alvo).astype(int)
    falta = int(total - base.sum())
    if falta > 0:
        base[np.argsort(-(alvo - base), kind="stable")[:falta]] += 1
    return base


def espalhar(linhas: list[dict], cod_municipio: int, r: dict | None = None) -> list[dict]:
    """Rebanho de cada fazenda do município (P10, P50, P90), lotação e metano."""
    r = r or regra()
    e = r["espalhar"]
    total, total_censo = bovinos_municipio(cod_municipio, r)
    pastos = np.array([pasto(li) for li in linhas], dtype=float)
    prod, fontes = produtividade(linhas, r)
    soma_pasto = float(pastos.sum())
    out = []
    if total is None or soma_pasto <= 0:
        for li in linhas:
            out.append({"cod_imovel": str(li["cod_imovel"]), "rebanho_fonte": "sem_ppm" if total is None else
                        "sem_pasto"})  # fmt: skip
        return out
    lot_mun = total / soma_pasto
    # Zero informado pela PPM é ausência de rebanho, não uma lotação pequena a elevar ao piso.
    if total > 0:
        lot_mun = min(max(lot_mun, float(e["lotacao_min_cab_ha"])), float(e["lotacao_max_cab_ha"]))
    total_ef = lot_mun * soma_pasto  # com a lotação dentro dos limites
    desenhos = []
    for ex in [float(e["expoente"]), *[float(x) for x in e["expoentes_faixa"]]]:
        w = pastos * prod**ex
        desenhos.append(w / w.sum() * total_ef if w.sum() > 0 else w)
    p50 = inteiros(desenhos[0], int(round(total_ef)))
    alts = [*desenhos[1:]]
    censo = censo_2017(cod_municipio, r)
    fator_censo = censo / total_censo if censo and total_censo else None
    if fator_censo:  # o erro do próprio total: o Censo de 2017 contra a PPM de 2017 no município, levado a hoje
        alts.append(desenhos[0] * fator_censo)
    lo = np.minimum.reduce([p50.astype(float), *alts])
    hi = np.maximum.reduce([p50.astype(float), *alts])
    m = r["metano"]
    t_cab = (float(m["enterico_kg_ch4_cab_ano"]) + float(m["dejetos_kg_ch4_cab_ano"])) * float(m["gwp100"]) / 1000
    ver = r["versao_completa"]
    for i, li in enumerate(linhas):
        out.append({
            "cod_imovel": str(li["cod_imovel"]),
            "rebanho_cab_p10": int(math.floor(lo[i])), "rebanho_cab_p50": int(p50[i]),
            "rebanho_cab_p90": int(math.ceil(hi[i])),
            "rebanho_lotacao_cab_ha": round(p50[i] / pastos[i], 3) if pastos[i] > 0 else None,
            "rebanho_pasto_ha": round(float(pastos[i]), 2),
            "rebanho_produtividade": round(float(prod[i]), 3), "rebanho_produtividade_fonte": fontes[i],
            "rebanho_fonte": f"ppm_{r['ppm']['ano']}_dasimetrico",
            "rebanho_municipio_ppm": int(total), "rebanho_municipio_lotacao_cab_ha": round(lot_mun, 3),
            "rebanho_censo_sobre_ppm_2017": None if fator_censo is None else round(fator_censo, 3),
            "metano_tco2e_ano_p10": round(lo[i] * t_cab, 1), "metano_tco2e_ano_p50": round(p50[i] * t_cab, 1),
            "metano_tco2e_ano_p90": round(hi[i] * t_cab, 1),
            "rebanho_versao": ver,
        })  # fmt: skip
    return out


def calcular_municipio(pasta: str | Path, cod: int, r: dict | None = None):
    """rebanho_<mun>.csv (DataFrame) a partir das saídas do motor (imoveis, mapbiomas, direto), lidas pelo nome."""
    import pandas as pd

    from raiz.privacidade import remover_colunas_pessoais

    r = r or regra()
    pasta = Path(pasta)
    im, _ = remover_colunas_pessoais(pd.read_csv(pasta / f"imoveis_{cod}.csv", low_memory=False))
    im["cod_imovel"] = im.cod_imovel.astype(str)
    for tipo in ("mapbiomas", "direto"):
        f = pasta / f"{tipo}_{cod}.csv"
        if f.exists():
            x = pd.read_csv(f, low_memory=False)
            x["cod_imovel"] = x.cod_imovel.astype(str)
            novas = [c for c in x.columns if c == "cod_imovel" or c not in im.columns]
            im = im.merge(x[novas].drop_duplicates("cod_imovel"), on="cod_imovel", how="left")
    return pd.DataFrame(espalhar(im.to_dict("records"), int(cod), r))


def versao_do_arquivo(f: Path) -> str | None:
    import pandas as pd

    if not Path(f).exists():
        return None
    try:
        v = pd.read_csv(f, usecols=["rebanho_versao"], nrows=5).rebanho_versao.dropna()
    except ValueError:
        return None
    return str(v.iloc[0]) if len(v) else None


def escrever_municipio(pasta: str | Path, cod: int) -> dict:
    df = calcular_municipio(pasta, cod)
    df.to_csv(Path(pasta) / f"rebanho_{cod}.csv", index=False)
    p50 = df["rebanho_cab_p50"] if "rebanho_cab_p50" in df else None
    return {"imoveis": int(len(df)), "cabecas": int(p50.sum()) if p50 is not None else 0, "versao": versao()}
