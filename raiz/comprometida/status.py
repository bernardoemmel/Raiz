"""Status de sobreposição de cada CAR com projetos e concessões já existentes (tarefa "comprometida" do executor).

Entrada: geo_<mun>.parquet (polígono de cada CAR, do funil) e os limites coletados (raiz/comprometida/coleta.py:
comprometida_limites.parquet e comprometida_cobertura.json, em RAIZ_COMPROMETIDA_DIR ou cache/comprometida).
Saída: comprometida_<mun>.csv, uma linha por imóvel (colunas em docs/colunas.md):
  status_sobreposicao  livre | ja_comprometida | risco_sobreposicao | nao_verificado
  sobreposicao_ha      área em limite oficial e ativo (união, EPSG:5880); vazio quando não verificado
  sobreposicao_indicio_ha  área só em limite secundário (base científica) ou em limite oficial pequeno
  projeto_id           até 3 objetos que mais cobrem o imóvel (ex.: VCS665), do maior para o menor
  fonte                a(s) fonte(s) desses objetos
  data_consulta        data da coleta mais nova entre as fontes que cobriram
  comprometida_cobertura  completa | parcial | nenhuma (quão inteira foi a fonte que cobriu o imóvel)
  comprometida_versao
Regras:
  "livre" só quando alguma fonte cobriu a área (cobertura bbox do Brasil, estado consultado ou parcial) e nada cruza.
  Sem fonte, ou com a coleta indisponível, é nao_verificado: ausência de dado nunca vira terra livre.
  ja_comprometida: limite oficial e ativo cobre pelo menos 1 ha ou 5% do imóvel (imóvel pequeno conta pela fração).
  risco_sobreposicao: só indício (limite secundário: base científica, InfoAmazonia, REDD+ do Pará) ou limite oficial
    menor que isso (borda, erro de contorno).
  Limite amplo (limite_amplo, mais de 1 milhão de ha: área geográfica de projeto agrupado) não entra no cruzamento.
Confirma sobreposição geométrica, não titularidade nem exclusividade do carbono (docs/terra-comprometida.md).
Nunca nome, CPF ou proponente: só identificador público do projeto.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path

import geopandas as gpd
import pandas as pd

from raiz import terra_comprometida as tc

VERSAO = "comprometida-2026b"
LIMIAR_HA = 1.0
LIMIAR_FRACAO = 0.05
COLUNAS = ["cod_imovel", "status_sobreposicao", "sobreposicao_ha", "sobreposicao_indicio_ha", "projeto_id", "fonte",
           "data_consulta", "comprometida_cobertura", "comprometida_versao"]  # fmt: skip
STATUS = ("livre", "ja_comprometida", "risco_sobreposicao", "nao_verificado")


def pasta_limites() -> Path:
    if os.environ.get("RAIZ_COMPROMETIDA_DIR"):
        return Path(os.environ["RAIZ_COMPROMETIDA_DIR"])
    from raiz.funil.rodar import dir_trabalho

    return dir_trabalho() / "cache" / "comprometida"


def carregar_limites(pasta: Path | None = None):
    """(GeoDataFrame, cobertura) ou (None, []) quando a coleta ainda não chegou."""
    pasta = Path(pasta) if pasta else pasta_limites()
    f, m = pasta / "comprometida_limites.parquet", pasta / "comprometida_cobertura.json"
    if not f.exists() or not m.exists():
        return None, []
    g = gpd.read_parquet(f)
    g = g.set_crs(4326) if g.crs is None else g.to_crs(4326)
    if "limite_amplo" in g.columns:  # coleta antiga não tem a coluna
        g = g[~g.limite_amplo.fillna(False).astype(bool)].reset_index(drop=True)
    cob = json.loads(m.read_text(encoding="utf-8")).get("cobertura", [])
    return g, cob


def assinatura(pasta: Path | None = None) -> str | None:
    """Muda quando a coleta muda (o executor usa para refazer só esta tarefa)."""
    pasta = Path(pasta) if pasta else pasta_limites()
    f = pasta / "comprometida_limites.parquet"
    m = pasta / "comprometida_cobertura.json"
    if not f.exists() or not m.exists():
        return None
    # a cobertura leva a data da coleta: coleta nova sem polígono novo também atualiza data_consulta
    return hashlib.sha256(f.read_bytes() + m.read_bytes()).hexdigest()[:16]


def versao() -> str:
    return VERSAO


def _num(v) -> float | None:
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def classificar(dto: dict, ha_car: float | None) -> tuple[str, float | None, float | None]:
    """(status, ha oficial, ha indício) a partir do resultado de terra_comprometida.cruzar."""
    if dto["situacao"] == "nao_verificado":
        return "nao_verificado", None, None
    c = _num(dto["area_confirmada"]["valor"]) or 0.0
    i = _num(dto["area_indicio"]["valor"]) or 0.0
    grande = c >= LIMIAR_HA or (bool(ha_car) and c / ha_car >= LIMIAR_FRACAO)
    if c > 0 and grande:
        return "ja_comprometida", round(c, 4), round(i, 4)
    if c > 0 or i > 0:
        return "risco_sobreposicao", round(c, 4), round(i, 4)
    return "livre", 0.0, 0.0


def _cobertura_do_imovel(dto: dict) -> str:
    estados = [c["estado"] for c in dto["cobertura"] if c["fonte_id"] != "berkeley"]
    return "nenhuma" if not estados else "completa" if "consultado" in estados else "parcial"


def avaliar_imovel(geom, cod: str, ha: float | None, candidatos: list[dict], coberturas: list[dict], hoje: str) -> dict:
    uf = cod.split("-")[0]
    dto = tc.cruzar(geom, uf, candidatos, coberturas, em=hoje, _normalizados=True)
    status, c, i = classificar(dto, ha)
    ordem = sorted((e for e in dto["evidencias"] if e["area"]["valor"]), key=lambda e: -e["area"]["valor"])
    # O mesmo projeto pode vir de várias fontes (Verra, InfoAmazonia, REDD+ do Pará): conta uma vez no projeto_id.
    ids = list(dict.fromkeys(e["objeto_id"] for e in ordem))[:3]
    top = [e for e in ordem if e["objeto_id"] in ids]
    return {
        "cod_imovel": cod,
        "status_sobreposicao": status,
        "sobreposicao_ha": c,
        "sobreposicao_indicio_ha": i,
        "projeto_id": "|".join(ids) or None,
        "fonte": "|".join(dict.fromkeys(e["fonte_id"] for e in top)) or None,
        "data_consulta": max((x["consultado_em"] for x in dto["cobertura"] if x["consultado_em"]), default=None),
        "comprometida_cobertura": _cobertura_do_imovel(dto),
    }


def calcular_municipio(pasta: str | Path, cod: int, limites=None, cobertura=None, hoje: str | None = None):
    """DataFrame com COLUNAS para o município. Sem limites coletados, todos nao_verificado."""
    pasta = Path(pasta)
    hoje = hoje or dt.date.today().isoformat()
    car = gpd.read_parquet(pasta / f"geo_{cod}.parquet")[["cod_imovel", "geometry"]]
    car = car.set_crs(4674) if car.crs is None else car
    car = car.to_crs(4326)
    if limites is None and cobertura is None:
        limites, cobertura = carregar_limites()
    ha = {}
    f = pasta / f"imoveis_{cod}.csv"
    if f.exists():
        im = pd.read_csv(f, usecols=lambda c: c in ("cod_imovel", "ha"), dtype={"cod_imovel": str})
        ha = dict(zip(im.cod_imovel, im.ha, strict=True)) if "ha" in im.columns else {}
    pronta = limites is not None
    idx = limites.sindex if pronta and len(limites) else None
    linhas = []
    for c, g in zip(car.cod_imovel.astype(str), car.geometry, strict=True):
        if g is None or g.is_empty:
            linhas.append(
                {"cod_imovel": c, "status_sobreposicao": "nao_verificado", "comprometida_cobertura": "nenhuma"}
            )
            continue
        cands = []
        if idx is not None:
            for _, r in limites.iloc[list(idx.query(g, predicate="intersects"))].iterrows():
                d = {k: (None if pd.isna(r[k]) else r[k]) for k in tc_campos()}
                d["geometry"] = r.geometry
                cands.append(d)
        linhas.append(avaliar_imovel(g, c, _num(ha.get(c)), cands, cobertura or [], hoje))
    df = pd.DataFrame(linhas)
    df["comprometida_versao"] = f"{VERSAO}+{assinatura() or 'sem_limites'}"
    for col in COLUNAS:
        if col not in df.columns:
            df[col] = None
    return df[COLUNAS]


def tc_campos() -> list[str]:
    return ["fonte_id", "objeto_id", "registro", "tipo", "situacao", "certeza", "uf", "fonte_url", "data_referencia",
            "observado_em", "inicio", "fim"]  # fmt: skip


def escrever_municipio(pasta: str | Path, cod: int, **kw) -> pd.DataFrame:
    df = calcular_municipio(pasta, cod, **kw)
    df.to_csv(Path(pasta) / f"comprometida_{cod}.csv", index=False)
    return df


def resumo(df: pd.DataFrame, ha: pd.Series | None = None) -> dict:
    """Agregado do município (é o que pode ir a público): contagem e hectares por status."""
    out = {s: int((df.status_sobreposicao == s).sum()) for s in STATUS}
    out["imoveis"] = int(len(df))
    return out
