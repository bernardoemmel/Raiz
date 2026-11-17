"""Cruzamento das camadas estaduais com cada imóvel do município (mesmo desenho das restrições nacionais).

Entrada: geo_<mun>.parquet (CAR de imóvel rural do funil), imoveis_<mun>.csv (área, se houver), a coleta
(raiz/estaduais/coleta.py: estaduais_<fonte>.parquet + estaduais_cobertura.json em RAIZ_ESTADUAIS_DIR ou
cache/estaduais) e as regras de matrícula (raiz/estaduais/matriculas.yaml).
Saída: estaduais_<mun>.csv, uma linha por imóvel (COLUNAS):
  estadual_status            exclusao | ressalva | livre | nao_verificado
  estadual_motivos           códigos separados por "|" (texto em raiz/regras/padroes/fontes_estaduais.yaml)
  estadual_informacoes       marcas que não restringem (prioridade de restauração, terra legitimada...)
  estadual_conferir          checklist de validação humana (fontes sem camada pública, bloqueios de matrícula)
  estaduais_nao_verificadas  fontes da UF que não cobriram o imóvel (bloqueio fora do Brasil, fora do ar)
  estadual_exclusao_ha / estadual_ressalva_ha  área sobreposta (união) das feições de cada efeito
  estadual_fontes            fontes que cruzaram o imóvel
Regras: exclusão só quando a sobreposição passa do limiar (1 ha ou 5% do imóvel); só na borda vira ressalva
"<motivo>_borda"; ponto com efeito de exclusão (sem área) vira ressalva. "livre" só quando todas as fontes
restritivas da UF cobriram o imóvel e nada cruzou. Nunca descarta imóvel por tamanho. Sem nome, CPF ou CNPJ.
"""

from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
import yaml

from raiz.estaduais.coleta import COBERTURA, catalogo

REGRA = Path(__file__).parents[1] / "regras" / "padroes" / "fontes_estaduais.yaml"
MATRICULAS = Path(__file__).with_name("matriculas.yaml")
CRS_AREA = 5880
STATUS = ("exclusao", "ressalva", "livre", "nao_verificado")
RESTRITIVOS = ("exclusao", "ressalva")
COLUNAS = [
    "cod_imovel",
    "estadual_status",
    "estadual_motivos",
    "estadual_informacoes",
    "estadual_conferir",
    "estaduais_nao_verificadas",
    "estadual_exclusao_ha",
    "estadual_ressalva_ha",
    "estadual_fontes",
    "estaduais_versao",
]
UF_IBGE = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO", "21": "MA", "22": "PI",
    "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA", "31": "MG", "32": "ES",
    "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}  # fmt: skip


@lru_cache(maxsize=1)
def regra() -> dict:
    return yaml.safe_load(REGRA.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def matriculas() -> list[dict]:
    return yaml.safe_load(MATRICULAS.read_text(encoding="utf-8")).get("regras") or []


def versao() -> str:
    h = hashlib.sha256(REGRA.read_bytes() + MATRICULAS.read_bytes())
    for f in sorted(Path(__file__).with_name("fontes").glob("*.yaml")):
        h.update(f.read_bytes())
    return f"{regra()['versao']}+{h.hexdigest()[:8]}"


def pasta_camadas() -> Path:
    if os.environ.get("RAIZ_ESTADUAIS_DIR"):
        return Path(os.environ["RAIZ_ESTADUAIS_DIR"])
    from raiz.funil.rodar import dir_trabalho

    return dir_trabalho() / "cache" / "estaduais"


def assinatura(pasta: Path | None = None) -> str | None:
    """Muda quando a coleta muda (o executor usa para refazer só esta tarefa)."""
    pasta = Path(pasta) if pasta else pasta_camadas()
    m = pasta / COBERTURA
    if not m.exists():
        return None
    h = hashlib.sha256(m.read_bytes())
    for f in sorted(pasta.glob("estaduais_*.parquet")):
        h.update(f.name.encode() + str(f.stat().st_size).encode())
    return h.hexdigest()[:16]


class Camadas:
    """Coleta estadual já lida, por fonte (lida uma vez por processo e reaproveitada nos municípios)."""

    def __init__(self, pasta: Path | None = None):
        self.pasta = Path(pasta) if pasta else pasta_camadas()
        m = self.pasta / COBERTURA
        self.cobertura = json.loads(m.read_text(encoding="utf-8")).get("fontes", {}) if m.exists() else {}
        self._cache: dict[str, gpd.GeoDataFrame | None] = {}

    def coberta(self, fonte_id: str) -> bool:
        return (self.cobertura.get(fonte_id) or {}).get("estado") in ("consultado", "parcial") and (
            self.pasta / f"estaduais_{fonte_id}.parquet"
        ).exists()

    def camada(self, fonte_id: str) -> gpd.GeoDataFrame | None:
        if fonte_id not in self._cache:
            f = self.pasta / f"estaduais_{fonte_id}.parquet"
            g = gpd.read_parquet(f) if f.exists() else None
            if g is not None:
                g = (g.set_crs(4674) if g.crs is None else g).to_crs(CRS_AREA)
                g = g[g.geometry.notna() & ~g.geometry.is_empty].reset_index(drop=True)
                g["geometry"] = shapely.make_valid(g.geometry.values)
            self._cache[fonte_id] = g
        return self._cache[fonte_id]


def _passa(x: float, ha: float | None, r: dict) -> bool:
    return x > 0 and (x >= r["limiar_ha"] or (bool(ha) and x / ha >= r["limiar_fracao"]))


def _medir(base: gpd.GeoDataFrame, g: gpd.GeoDataFrame) -> pd.DataFrame:
    """Pares (imóvel, feição) que se tocam, com ha de interseção (0 para ponto dentro do imóvel)."""
    ib, ic = g.sindex.query(base.geometry.values, predicate="intersects")
    if not len(ib):
        return pd.DataFrame(columns=["i", "c", "ha", "ponto"])
    geo = g.geometry.values[ic]
    ponto = np.array([x.geom_type in ("Point", "MultiPoint") for x in geo])
    ha = np.zeros(len(ib))
    if (~ponto).any():
        ha[~ponto] = shapely.area(shapely.intersection(base.geometry.values[ib[~ponto]], geo[~ponto])) / 1e4
    return pd.DataFrame({"i": ib, "c": ic, "ha": ha, "ponto": ponto})


def regras_matricula(uf: str, cod: int) -> list[dict]:
    return [m for m in matriculas() if m.get("uf") == uf and int(cod) in {int(k) for k in (m.get("municipios") or {})}]


def calcular_municipio(pasta: str | Path, cod: int, camadas: Camadas | None = None, uf: str | None = None):
    """DataFrame com COLUNAS para o município (uma linha por cod_imovel de geo_<mun>.parquet)."""
    pasta = Path(pasta)
    r = regra()
    tol = r["tolerancia_ha"]
    camadas = camadas or Camadas()
    uf = uf or UF_IBGE.get(str(cod)[:2], "")
    base = gpd.read_parquet(pasta / f"geo_{cod}.parquet")[["cod_imovel", "geometry"]]
    base = (base.set_crs(4674) if base.crs is None else base).to_crs(CRS_AREA)
    base = base[base.geometry.notna()].reset_index(drop=True)
    base["geometry"] = shapely.make_valid(base.geometry.values)
    base["cod_imovel"] = base.cod_imovel.astype(str)
    ha = dict(zip(base.cod_imovel, base.geometry.area / 1e4, strict=True))
    f = pasta / f"imoveis_{cod}.csv"
    if f.exists():
        im = pd.read_csv(f, usecols=lambda c: c in ("cod_imovel", "ha"), dtype={"cod_imovel": str})
        if "ha" in im.columns:
            ha.update({c: v for c, v in zip(im.cod_imovel, im.ha, strict=True) if c in ha and pd.notna(v)})

    n = len(base)
    exc = [[] for _ in range(n)]
    res = [[] for _ in range(n)]
    info = [[] for _ in range(n)]
    fontes_cruzadas = [[] for _ in range(n)]
    exc_geo = [[] for _ in range(n)]
    res_geo = [[] for _ in range(n)]
    conferir, nao_verificadas, essenciais = [], [], []

    for fonte in catalogo([uf]) if uf else []:
        fid = fonte["id"]
        if fonte.get("acesso") == "regra":  # regra estadual ainda pendente: só checklist
            conferir.append(fonte["motivo"])
            continue
        if fonte.get("acesso") != "aberto" or fonte["tipo"] not in ("wfs", "arcgis"):
            # sem camada (bloqueada fora do Brasil, sem download): não verificada e item do checklist
            nao_verificadas.append(fid)
            essenciais.append(fid)
            conferir.append(fonte["motivo"])
            continue
        if fonte["efeito"] in RESTRITIVOS:
            essenciais.append(fid)
        if not camadas.coberta(fid):
            nao_verificadas.append(fid)
            continue
        g = camadas.camada(fid)
        if g is None or not len(g) or not len(base):
            continue
        pares = _medir(base, g)
        if not len(pares):
            continue
        pares["efeito"] = g.efeito.values[pares.c.values.astype(int)]
        pares["motivo"] = g.motivo.values[pares.c.values.astype(int)]
        for (i, efeito, motivo), grupo in pares.groupby(["i", "efeito", "motivo"]):
            i = int(i)
            pts = grupo[grupo.ponto]
            pol = grupo[~grupo.ponto]
            area = 0.0
            if len(pol):
                partes = shapely.intersection(base.geometry.values[i], g.geometry.values[pol.c.values.astype(int)])
                uniao = shapely.union_all(partes)
                area = uniao.area / 1e4
            marcou = False
            if efeito == "exclusao":
                if _passa(area, ha.get(base.cod_imovel[i]), r):
                    exc[i].append(motivo)
                    exc_geo[i].append(uniao)
                    marcou = True
                elif area >= tol:
                    res[i].append(f"{motivo}_borda")
                    res_geo[i].append(uniao)
                    marcou = True
                if len(pts):
                    res[i].append(motivo if motivo.endswith("_ponto") else f"{motivo}_ponto")
                    marcou = True
            elif efeito == "ressalva":
                if len(pts) or _passa(area, ha.get(base.cod_imovel[i]), r):
                    res[i].append(motivo)
                    if area:
                        res_geo[i].append(uniao)
                    marcou = True
            elif efeito == "informativo" and (len(pts) or area >= tol):
                info[i].append(motivo)
                marcou = True
            if marcou and fid not in fontes_cruzadas[i]:
                fontes_cruzadas[i].append(fid)

    for m in regras_matricula(uf, cod):
        conferir.append(m["motivo"])
        for i in range(n):
            res[i].append(m["motivo"])

    linhas = []
    sem_cobertura = set(nao_verificadas) & set(essenciais)
    for i, c in enumerate(base.cod_imovel):
        e, s = list(dict.fromkeys(exc[i])), list(dict.fromkeys(res[i]))
        status = "exclusao" if e else "ressalva" if s else ("nao_verificado" if sem_cobertura or not uf else "livre")
        uniao_exc = shapely.union_all(exc_geo[i]).area / 1e4 if exc_geo[i] else 0.0
        uniao_res = shapely.union_all(res_geo[i]).area / 1e4 if res_geo[i] else 0.0
        linhas.append(
            {
                "cod_imovel": c,
                "estadual_status": status,
                "estadual_motivos": "|".join(e + s) or None,
                "estadual_informacoes": "|".join(dict.fromkeys(info[i])) or None,
                "estadual_conferir": "|".join(dict.fromkeys(conferir)) or None,
                "estaduais_nao_verificadas": "|".join(nao_verificadas) or None,
                "estadual_exclusao_ha": round(uniao_exc, 4),
                "estadual_ressalva_ha": round(uniao_res, 4),
                "estadual_fontes": "|".join(fontes_cruzadas[i]) or None,
            }
        )
    df = pd.DataFrame(linhas, columns=COLUNAS)
    df["estaduais_versao"] = f"{versao()}+{assinatura(camadas.pasta) or 'sem_coleta'}"
    return df[COLUNAS]


def escrever_municipio(pasta: str | Path, cod: int, **kw) -> pd.DataFrame:
    df = calcular_municipio(pasta, cod, **kw)
    df.to_csv(Path(pasta) / f"estaduais_{cod}.csv", index=False)
    return df


def resumo(df: pd.DataFrame) -> dict:
    """Agregado do município (pode ir a público): contagem por status e por motivo."""
    out = {s: int((df.estadual_status == s).sum()) for s in STATUS}
    motivos = df.estadual_motivos.dropna().str.split("|").explode()
    out["motivos"] = {k: int(v) for k, v in motivos.value_counts().items()}
    out["imoveis"] = int(len(df))
    return out
