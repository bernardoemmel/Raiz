"""Vegetação e relevo de cada CAR do município (tarefa "ambiental" do executor, folha do grafo: só depende do funil).

Entrada: geo_<mun>.parquet e imoveis_<mun>.csv (funil); ambiental_vegetacao.parquet e ambiental_cobertura.json da
coleta (raiz/ambiental/coleta.py, Release insumos, em RAIZ_AMBIENTAL_DIR ou cache/ambiental); TerraClass em
cache/ambiental/terraclass/ (quando houver); ANADEM lido direto do servidor da ANA; cobertura do MapBiomas do estado
(cache/mapbiomas/<UF>/) para saber se a APP de relevo está aberta.
Saída: ambiental_<mun>.csv, uma linha por imóvel (COLUNAS; docs/vegetacao-relevo.md):
  ambiental_status   ressalva | livre | nao_verificado   (nada aqui exclui imóvel)
  ambiental_motivos  códigos separados por "|" (raiz/regras/padroes/ambiental.yaml, seção motivos)
  ambiental_nao_verificadas  fontes que não cobriram (vegetacao, relevo, terraclass, mapbiomas)
  reserva legal pela vegetação (rl_*_ha, pct_RL_vegetacao, deficit e área além da RL recalculados), Lei da Mata
  Atlântica, TerraClass e APP de relevo.
Regras: "livre" só quando vegetação e relevo cobriram o imóvel e nada marcou. Os limiares medem a área marcada
(ha ou fração do imóvel), nunca o tamanho da fazenda.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml

from raiz.ambiental import relevo as RV
from raiz.ambiental import terraclass as TC
from raiz.ambiental import vegetacao as VG

REGRA = Path(__file__).parents[1] / "regras" / "padroes" / "ambiental.yaml"
NOMES = {"vegetacao": "ambiental_vegetacao.parquet", "cobertura": "ambiental_cobertura.json"}
COLUNAS = [
    "cod_imovel", "ambiental_status", "ambiental_motivos", "ambiental_nao_verificadas",
    "rl_floresta_ha", "rl_cerrado_ha", "rl_campos_ha", "rl_transicao_ha", "fora_amazonia_legal_ha",
    "vegetacao_coberta_ha", "pct_RL_vegetacao", "pct_RL_alem_vegetacao", "deficit_RL_vegetacao_ha",
    "deficit_RL_alem_vegetacao_ha", "alem_RL_vegetacao_ha", "rl_base_fonte", "rl_diferenca_ha", "lei_mata_atlantica_ha",
    "tc_pasto_sujo_ha", "tc_pasto_limpo_ha", "tc_vegetacao_secundaria_ha", "tc_ano", "tc_fonte",
    "app_declividade_ha", "app_topo_morro_ha", "app_relevo_ha", "app_relevo_aberta_ha", "relevo_fonte",
    "ambiental_versao",
]  # fmt: skip
STATUS = ("ressalva", "livre", "nao_verificado")
COD_UF = {11: "RO", 12: "AC", 13: "AM", 14: "RR", 15: "PA", 16: "AP", 17: "TO", 21: "MA", 22: "PI", 23: "CE",
          24: "RN", 25: "PB", 26: "PE", 27: "AL", 28: "SE", 29: "BA", 31: "MG", 32: "ES", 33: "RJ", 35: "SP",
          41: "PR", 42: "SC", 43: "RS", 50: "MS", 51: "MT", 52: "GO", 53: "DF"}  # fmt: skip
log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def regra() -> dict:
    return yaml.safe_load(REGRA.read_text(encoding="utf-8"))


def pasta_camadas() -> Path:
    if os.environ.get("RAIZ_AMBIENTAL_DIR"):
        return Path(os.environ["RAIZ_AMBIENTAL_DIR"])
    from raiz.funil.rodar import dir_trabalho

    return dir_trabalho() / "cache" / "ambiental"


def assinatura(pasta: Path | None = None) -> str | None:
    """Muda quando a coleta muda (o executor usa para refazer só esta tarefa)."""
    pasta = Path(pasta) if pasta else pasta_camadas()
    m = pasta / NOMES["cobertura"]
    if not m.exists():
        return None
    h = hashlib.sha256(m.read_bytes())
    for f in sorted([*pasta.glob("ambiental_*"), *pasta.glob("terraclass/terraclass_*")]):
        if f.name != NOMES["cobertura"]:
            h.update(f.name.encode() + str(f.stat().st_size).encode())
    return h.hexdigest()[:16]


def versao() -> str:
    return f"{regra()['versao']}+{hashlib.sha256(REGRA.read_bytes()).hexdigest()[:8]}"


class Camadas:
    """O que a coleta deixou (lido uma vez por processo)."""

    def __init__(self, pasta: Path | None = None, relevo: bool | None = None):
        self.pasta = Path(pasta) if pasta else pasta_camadas()
        m = self.pasta / NOMES["cobertura"]
        self.cobertura = json.loads(m.read_text(encoding="utf-8")).get("fontes", {}) if m.exists() else {}
        f = self.pasta / NOMES["vegetacao"]
        self.vegetacao = f if f.exists() else None
        self.terraclass = self.pasta / "terraclass"
        # RAIZ_AMBIENTAL_RELEVO=0 desliga o relevo (testes; máquina sem rede): o imóvel fica nao_verificado nele
        self.relevo = relevo if relevo is not None else os.environ.get("RAIZ_AMBIENTAL_RELEVO", "1") != "0"


def _mapbiomas_cobertura(uf: str) -> Path | None:
    from raiz.funil.rodar import dir_trabalho

    fs = sorted((dir_trabalho() / "cache" / "mapbiomas" / uf).glob(f"{uf}_cobertura_*.tif"))
    return fs[-1] if fs else None


def _passa(ha, total, r) -> np.ndarray:
    ha = pd.to_numeric(ha, errors="coerce").fillna(0.0).to_numpy(float)
    total = pd.to_numeric(total, errors="coerce").to_numpy(float)
    frac = np.divide(ha, total, out=np.zeros_like(ha), where=np.nan_to_num(total) > 0)
    return (ha >= r["limiar_ha"]) | ((ha > 0.1) & (frac >= r["limiar_fracao"]))


def calcular_municipio(pasta: str | Path, cod: int, camadas: Camadas | None = None, leitor_relevo=None,
                       cobertura_mapbiomas: Path | None | bool = None) -> pd.DataFrame:  # fmt: skip
    """DataFrame com COLUNAS para o município."""
    r = regra()
    pasta = Path(pasta)
    camadas = camadas or Camadas()
    uf = COD_UF[int(cod) // 100000]
    car = gpd.read_parquet(pasta / f"geo_{cod}.parquet")[["cod_imovel", "geometry"]]
    car = (car.set_crs(4674) if car.crs is None else car).reset_index(drop=True)
    car["cod_imovel"] = car.cod_imovel.astype(str)
    car = car.drop_duplicates("cod_imovel").reset_index(drop=True)
    im = pd.read_csv(pasta / f"imoveis_{cod}.csv", dtype={"cod_imovel": str}, low_memory=False)
    im = im.drop_duplicates("cod_imovel").set_index("cod_imovel").reindex(car.cod_imovel)

    # reserva legal pela vegetação
    veg = VG.ler(camadas.vegetacao, car.to_crs(4674).total_bounds) if camadas.vegetacao else None
    m = VG.por_imovel(car, veg, uf, r).set_index("cod_imovel")
    p = VG.percentuais(m, r)
    m = m.join(p)
    precisa = {"ha", "nao_floresta_ha", "floresta_rem_ha", "desm_total_ha"}
    if precisa <= set(im.columns):
        fmb = pasta / f"mapbiomas_{cod}.csv"
        mb = (
            pd.read_csv(fmb, dtype={"cod_imovel": str}).drop_duplicates("cod_imovel").set_index("cod_imovel")
            if fmb.exists()
            else None
        )
        nao_flo = (m.rl_cerrado_ha.fillna(0) + m.rl_campos_ha.fillna(0) + m.fora_amazonia_legal_ha.fillna(0)) > (
            0.5 * m.ha_geo
        )
        m = m.join(VG.deficit(im, m.pct_RL_vegetacao, m.pct_RL_alem_vegetacao, mb=mb, nao_floresta=nao_flo))
        if "alem_RL_ha" in im:
            m["rl_diferenca_ha"] = (m.alem_RL_vegetacao_ha - im.alem_RL_ha.astype(float)).round(4)
    ha = im.ha.astype(float) if "ha" in im else m.ha_geo

    # TerraClass
    m = m.join(TC.por_imovel(car, camadas.terraclass, r).set_index("cod_imovel"))

    # relevo (ANADEM) e APP aberta (MapBiomas)
    if camadas.relevo:
        mb = _mapbiomas_cobertura(uf) if cobertura_mapbiomas is None else (cobertura_mapbiomas or None)
        try:
            m = m.join(RV.por_imovel(car, r, cobertura_tif=mb, leitor=leitor_relevo).set_index("cod_imovel"))
        except Exception as ex:  # servidor fora do ar: o imóvel fica nao_verificado no relevo, a tarefa segue
            log.warning("relevo %s: %s", cod, ex)
    for c in COLUNAS:
        if c not in m.columns and c not in ("cod_imovel",):
            m[c] = np.nan

    # status e motivos
    mot: dict[str, np.ndarray] = {}
    pct_motor = pd.to_numeric(im.get("pct_RL"), errors="coerce") if "pct_RL" in im else pd.Series(np.nan, m.index)
    dif = (m.pct_RL_vegetacao - pct_motor).abs()
    mot["rl_vegetacao_diverge"] = (dif >= r["reserva_legal"]["divergencia_pontos"]).to_numpy()
    mot["rl_transicao"] = _passa(m.rl_transicao_ha, ha, r)
    mot["fora_amazonia_legal_maranhao"] = _passa(m.fora_amazonia_legal_ha, ha, r) & (uf == "MA")
    mot["lei_mata_atlantica"] = _passa(m.lei_mata_atlantica_ha, ha, r)
    mot["pasto_sujo"] = _passa(m.tc_pasto_sujo_ha, ha, r)
    mot["regeneracao_existente"] = _passa(m.tc_vegetacao_secundaria_ha, ha, r)
    mot["app_relevo_aberta"] = _passa(m.app_relevo_aberta_ha, ha, r)
    mot["relevo_sem_anadem"] = (
        _passa(m.app_relevo_ha, ha, r) & m.relevo_fonte.fillna("").str.contains("copernicus").to_numpy()
    )
    nv: dict[str, np.ndarray] = {
        "vegetacao": (m.vegetacao_coberta_ha.isna() | (m.vegetacao_coberta_ha < 0.5 * m.ha_geo)).to_numpy(),
        "relevo": m.app_relevo_ha.isna().to_numpy(),
        "terraclass": m.tc_ano.isna().to_numpy(),
        "mapbiomas": (m.app_relevo_aberta_ha.isna() & m.app_relevo_ha.notna()).to_numpy(),
    }
    n = len(m)
    motivos = ["|".join(k for k, v in mot.items() if v[i]) or None for i in range(n)]
    falta = ["|".join(k for k, v in nv.items() if v[i]) or None for i in range(n)]
    ess = r["fontes_essenciais"]
    status = []
    for i in range(n):
        if any(nv[f][i] for f in ess):
            status.append("nao_verificado")
        elif motivos[i]:
            status.append("ressalva")
        else:
            status.append("livre")
    m["ambiental_status"] = status
    m["ambiental_motivos"] = motivos
    m["ambiental_nao_verificadas"] = falta
    m["ambiental_versao"] = f"{versao()}+{assinatura(camadas.pasta) or 'sem_coleta'}"
    m = m.reset_index().rename(columns={"index": "cod_imovel"})
    for c in ("rl_floresta_ha", "rl_cerrado_ha", "rl_campos_ha", "rl_transicao_ha", "fora_amazonia_legal_ha",
              "vegetacao_coberta_ha", "lei_mata_atlantica_ha"):  # fmt: skip
        m[c] = pd.to_numeric(m[c], errors="coerce").round(4)
    return m[COLUNAS]


def escrever_municipio(pasta: str | Path, cod: int, **kw) -> pd.DataFrame:
    df = calcular_municipio(pasta, cod, **kw)
    f = Path(pasta) / f"ambiental_{cod}.csv"
    tmp = f.with_suffix(".tmp.csv")
    df.to_csv(tmp, index=False)
    tmp.replace(f)
    return df


def resumo(df: pd.DataFrame) -> dict:
    """Agregado do município: contagem por status e por motivo (é o que pode ir a público)."""
    out = {s: int((df.ambiental_status == s).sum()) for s in STATUS}
    mot = df.ambiental_motivos.dropna().str.split("|").explode().value_counts()
    out["motivos"] = {k: int(v) for k, v in mot.items()}
    out["imoveis"] = int(len(df))
    return out
