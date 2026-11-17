"""Fontes complementares de cada CAR do município (tarefa "complementares" do executor, folha do grafo).

Entrada: geo_<mun>.parquet (CAR de imóvel rural do funil), imoveis_<mun>.csv (área) e as camadas da coleta
(raiz/complementares/coleta.py, em RAIZ_COMPLEMENTARES_DIR ou cache/complementares).
Saída: complementares_<mun>.csv, uma linha por imóvel (COLUNAS abaixo, docs/colunas.md):
  complementar_status    exclusao (sai do lote) | ressalva (fica marcado) | livre | nao_verificado
  complementar_motivos   códigos separados por "|" (raiz/regras/padroes/complementares.yaml, seção motivos)
  complementares_nao_verificadas  fontes que não cobriram o imóvel
  e as medidas de cada fonte.
Regras: "livre" só quando as fontes essenciais cobriram e nada cruzou (ausência de dado nunca vira livre).
Sobreposição conta quando passa de limiar_ha ou de limiar_fracao do imóvel; abaixo de tolerancia_ha é ruído de
contorno. Nunca descarta imóvel por tamanho. Sem nome, CPF, CNPJ ou valor de crédito: só datas, áreas e códigos.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely
import yaml

from raiz.complementares.coleta import FONTES, FONTES_IMPORTADAS, GLEBAS, META_IMPORTADA, NOMES
from raiz.restricoes.status import _cruzados, _passa, _uniao_por_imovel

REGRA = Path(__file__).parents[1] / "regras" / "padroes" / "complementares.yaml"
CRS_AREA = 5880
COLUNAS = [
    "cod_imovel",
    "complementar_status",
    "complementar_motivos",
    "complementares_nao_verificadas",
    "sicor_operacoes_n",
    "sicor_vencimento_max",
    "sicor_emissao_ultima",
    "sicor_area_financiada_ativa_ha",
    "sicor_floresta",
    "sicor_gleba_recente_ha",
    "sicor_gleba_ativa_ha",
    "sicor_gleba_floresta_ha",
    "quilombola_localidades_dentro_n",
    "quilombola_localidade_km",
    "quilombola_certificada_fcp",
    "quilombola_fora_territorio",
    "palmares_certificadas_municipio",
    "palmares_sem_titulo_municipio",
    "mpf_territorio_ha",
    "restauracao_externa_ha",
    "restauracao_externa_fontes",
    "restauracao_externa_ids",
    "complementares_versao",
]
STATUS = ("exclusao", "ressalva", "livre", "nao_verificado")
log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def regra() -> dict:
    return yaml.safe_load(REGRA.read_text(encoding="utf-8"))


def pasta_camadas() -> Path:
    if os.environ.get("RAIZ_COMPLEMENTARES_DIR"):
        return Path(os.environ["RAIZ_COMPLEMENTARES_DIR"])
    from raiz.funil.rodar import dir_trabalho

    return dir_trabalho() / "cache" / "complementares"


def assinatura(pasta: Path | None = None) -> str | None:
    """Muda quando a coleta muda (o executor usa para refazer só esta tarefa)."""
    pasta = Path(pasta) if pasta else pasta_camadas()
    m = pasta / NOMES["cobertura"]
    if not m.exists():
        return None
    h = hashlib.sha256(m.read_bytes())
    for f in sorted(pasta.glob("complementares_*")):
        if f.name != NOMES["cobertura"]:
            h.update(f.name.encode() + str(f.stat().st_size).encode())
    return h.hexdigest()[:16]


def versao() -> str:
    return f"{regra()['versao']}+{hashlib.sha256(REGRA.read_bytes()).hexdigest()[:8]}"


# --- camadas -----------------------------------------------------------------------------------------------------


def _geo(f: Path):
    if not f.exists():
        return None
    g = gpd.read_parquet(f)
    return (g.set_crs(4674) if g.crs is None else g).to_crs(CRS_AREA)


class Camadas:
    """As camadas da coleta já lidas (uma vez por processo; as glebas do SICOR, uma vez por UF)."""

    def __init__(self, pasta: Path | None = None):
        self.pasta = Path(pasta) if pasta else pasta_camadas()
        m = self.pasta / NOMES["cobertura"]
        self.cobertura = json.loads(m.read_text(encoding="utf-8")).get("fontes", {}) if m.exists() else {}
        # importadas que chegaram depois da última coleta: o meta ao lado do arquivo vale
        for fonte in FONTES_IMPORTADAS:
            meta = self.pasta / META_IMPORTADA.format(fonte=fonte)
            if (self.cobertura.get(fonte) or {}).get("estado") != "consultado" and meta.exists():
                self.cobertura[fonte] = json.loads(meta.read_text(encoding="utf-8"))
        f = self.pasta / NOMES["sicor_car"]
        self.sicor_car = pd.read_parquet(f).set_index("cod_imovel") if f.exists() else None
        self.quilombolas = _geo(self.pasta / NOMES["ibge_quilombolas"])
        f = self.pasta / NOMES["palmares"]
        self.palmares = pd.read_csv(f).set_index("cod_ibge") if f.exists() else None
        self.mpf = _geo(self.pasta / NOMES["mpf_territorios"]) if self.coberta("mpf_territorios") else None
        partes = [_geo(self.pasta / NOMES[f]) for f in ("observatorio", "restor") if self.coberta(f)]
        partes = [p for p in partes if p is not None and len(p)]
        self.restauracao = gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), crs=CRS_AREA) if partes else None
        self._glebas: dict[str, gpd.GeoDataFrame | None] = {}

    def glebas(self, uf: str):
        if uf not in self._glebas:
            self._glebas[uf] = _geo(self.pasta / GLEBAS.format(uf=uf))
        return self._glebas[uf]

    def coberta(self, fonte: str) -> bool:
        c = self.cobertura.get(fonte) or {}
        if fonte == "sicor":
            return c.get("estado") in ("consultado", "parcial") and self.sicor_car is not None
        if fonte == "ibge_quilombolas":
            return c.get("estado") == "consultado" and getattr(self, "quilombolas", None) is not None
        if fonte == "palmares":
            return c.get("estado") == "consultado" and getattr(self, "palmares", None) is not None
        return c.get("estado") == "consultado" and (self.pasta / NOMES[fonte]).exists()


# --- medidas -----------------------------------------------------------------------------------------------------


def _sicor(base, camadas: Camadas, uf: str, hoje: str, medidas: dict, r: dict) -> None:
    h = pd.Timestamp(hoje)
    recente = (h - pd.DateOffset(years=r["sicor"]["anos_uso_recente"])).strftime("%Y-%m-%d")
    sc = camadas.sicor_car
    for c in base.cod_imovel:
        if sc is not None and c in sc.index:
            x = sc.loc[c]
            venc_flo = x.get("floresta_vencimento_max")
            medidas[c].update(
                sicor_operacoes_n=int(x.operacoes_n),
                sicor_vencimento_max=x.vencimento_max,
                sicor_emissao_ultima=x.emissao_ultima,
                sicor_area_financiada_ativa_ha=float(x.area_financiada_ativa_ha or 0),
                sicor_floresta=bool(x.floresta),
                _sicor_floresta_vigente=bool(x.floresta) and isinstance(venc_flo, str) and venc_flo >= recente,
            )
        else:
            medidas[c].update(sicor_operacoes_n=0)
    g = camadas.glebas(uf)
    if g is None or not len(g):
        for c in base.cod_imovel:
            medidas[c].update(sicor_gleba_recente_ha=0.0, sicor_gleba_ativa_ha=0.0, sicor_gleba_floresta_ha=0.0)
        return
    hoje_s = h.strftime("%Y-%m-%d")
    ativa = g[g.vencimento.fillna("") >= hoje_s]
    rec = g[g.emissao.fillna("") >= recente]
    vigente = (g.vencimento.fillna("") >= hoje_s) | (g.emissao.fillna("") >= recente)
    flo = g[g.floresta.fillna(False).astype(bool) & vigente]
    a, rc, fl = (_uniao_por_imovel(base, x if len(x) else None) for x in (ativa, rec, flo))
    for c in base.cod_imovel:
        medidas[c].update(
            sicor_gleba_ativa_ha=round(a[c], 4),
            sicor_gleba_recente_ha=round(rc[c], 4),
            sicor_gleba_floresta_ha=round(fl[c], 4),
        )


def _quilombolas(base, camadas: Camadas, cod: int, medidas: dict, r: dict) -> None:
    q = camadas.quilombolas
    raio = r["quilombolas"]["raio_km"] * 1000
    dentro = _cruzados(base, q, 0.0)
    perto_b, perto_q = q.sindex.query(base.geometry.values, predicate="dwithin", distance=raio) if len(q) else ([], [])
    dist = {}
    if len(perto_b):
        d = shapely.distance(base.geometry.values[perto_b], q.geometry.values[perto_q])
        t = pd.DataFrame({"i": perto_b, "q": perto_q, "d": d}).sort_values("d").drop_duplicates("i")
        dist = {int(i): (float(dd), int(qq)) for i, qq, dd in zip(t.i, t.q, t.d, strict=True)}
    pal = camadas.palmares
    cert = sem = None
    if pal is not None and camadas.coberta("palmares"):
        cert = int(pal.certificadas_n.get(cod, 0))
        sem = int(pal.certificadas_sem_titulo_n.get(cod, 0))
    for i, c in enumerate(base.cod_imovel):
        objs = dentro.get(i, [])
        perto = dist.get(i)
        alvo = objs[0] if objs else (perto[1] if perto else None)
        medidas[c].update(
            quilombola_localidades_dentro_n=len(objs),
            quilombola_localidade_km=round(perto[0] / 1000, 3) if perto else None,
            quilombola_certificada_fcp=bool(q.certificada_fcp.iloc[alvo]) if alvo is not None else None,
            quilombola_fora_territorio=(not bool(q.territorio_oficial.iloc[alvo])) if alvo is not None else None,
            palmares_certificadas_municipio=cert,
            palmares_sem_titulo_municipio=sem,
        )


def _poligonos_externos(base, camada, medidas: dict, coluna: str, ids: bool = False) -> None:
    ha = _uniao_por_imovel(base, camada)
    quais = _cruzados(base, camada, regra()["tolerancia_ha"]) if ids else {}
    for i, c in enumerate(base.cod_imovel):
        medidas[c][coluna] = round(ha[c], 4)
        if ids and quais.get(i):
            s = camada.iloc[quais[i]]
            medidas[c]["restauracao_externa_fontes"] = "|".join(sorted(set(s.fonte.astype(str))))
            medidas[c]["restauracao_externa_ids"] = "|".join(dict.fromkeys(s.objeto_id.astype(str)))[:200] or None


# --- classificação -----------------------------------------------------------------------------------------------


def classificar(m: dict, ha: float | None, verificadas: set[str], r: dict | None = None) -> tuple[str, list[str]]:
    """(status, motivos) de um imóvel a partir das medidas. Exclusão vem antes de ressalva; os motivos ficam todos."""
    r = r or regra()
    tol = r["tolerancia_ha"]
    exc, res = [], []
    if m.get("quilombola_localidades_dentro_n"):
        exc.append("localidade_quilombola_dentro")
    elif m.get("quilombola_localidade_km") is not None:
        res.append("localidade_quilombola_proxima")
    mpf = m.get("mpf_territorio_ha")
    if _passa(mpf, ha, r):
        exc.append("territorio_tradicional_mpf")
    elif (mpf or 0) >= tol:
        res.append("territorio_tradicional_mpf_borda")
    hoje = m.get("_hoje") or dt.date.today().isoformat()
    ativo = bool(m.get("sicor_operacoes_n")) and (m.get("sicor_vencimento_max") or "") >= hoje
    if ativo or _passa(m.get("sicor_gleba_ativa_ha"), ha, r):
        res.append("credito_rural_ativo")
    elif _passa(m.get("sicor_gleba_recente_ha"), ha, r):
        res.append("uso_agricola_recente")
    if m.get("_sicor_floresta_vigente") or _passa(m.get("sicor_gleba_floresta_ha"), ha, r):
        res.append("credito_rural_floresta")
    rest = m.get("restauracao_externa_ha")
    if _passa(rest, ha, r):
        res.append("restauracao_existente")
    elif (rest or 0) >= tol:
        res.append("restauracao_existente_borda")
    if exc:
        return "exclusao", exc + res
    if res:
        return "ressalva", res
    if set(r["fontes_essenciais"]) <= verificadas:
        return "livre", []
    return "nao_verificado", []


def calcular_municipio(pasta: str | Path, cod: int, camadas: Camadas | None = None, hoje: str | None = None):
    pasta = Path(pasta)
    r = regra()
    hoje = hoje or dt.date.today().isoformat()
    camadas = camadas or Camadas()
    base = gpd.read_parquet(pasta / f"geo_{cod}.parquet")[["cod_imovel", "geometry"]]
    base = (base.set_crs(4674) if base.crs is None else base).to_crs(CRS_AREA)
    base = base[base.geometry.notna()].reset_index(drop=True)
    base["geometry"] = shapely.make_valid(base.geometry.values)
    base["cod_imovel"] = base.cod_imovel.astype(str)
    uf = base.cod_imovel.iloc[0].split("-")[0] if len(base) else ""
    ha: dict = {}
    f = pasta / f"imoveis_{cod}.csv"
    if f.exists():
        im = pd.read_csv(f, usecols=lambda c: c in ("cod_imovel", "ha"), dtype={"cod_imovel": str})
        ha = dict(zip(im.cod_imovel, im.ha, strict=True)) if "ha" in im.columns else {}
    areas = base.geometry.area.values / 1e4
    for c, a in zip(base.cod_imovel, areas, strict=True):
        if c not in ha or pd.isna(ha[c]):
            ha[c] = float(a)

    verificadas = {f for f in FONTES if camadas.coberta(f)}
    medidas: dict[str, dict] = {c: {"_hoje": hoje} for c in base.cod_imovel}
    if "sicor" in verificadas:
        _sicor(base, camadas, uf, hoje, medidas, r)
    if "ibge_quilombolas" in verificadas:
        _quilombolas(base, camadas, int(cod), medidas, r)
    if "mpf_territorios" in verificadas:
        _poligonos_externos(base, camadas.mpf, medidas, "mpf_territorio_ha")
    if camadas.restauracao is not None:
        _poligonos_externos(base, camadas.restauracao, medidas, "restauracao_externa_ha", ids=True)

    linhas = []
    for c in base.cod_imovel:
        m = medidas[c]
        status, motivos = classificar(m, ha.get(c), verificadas, r)
        linha = {k: m.get(k) for k in COLUNAS if k in m}
        linha.update(
            cod_imovel=c,
            complementar_status=status,
            complementar_motivos="|".join(motivos) or None,
            complementares_nao_verificadas="|".join(f for f in FONTES if f not in verificadas) or None,
        )
        linhas.append(linha)
    df = pd.DataFrame(linhas, columns=COLUNAS)
    df["complementares_versao"] = f"{versao()}+{assinatura(camadas.pasta) or 'sem_coleta'}"
    return df[COLUNAS]


def escrever_municipio(pasta: str | Path, cod: int, **kw) -> pd.DataFrame:
    df = calcular_municipio(pasta, cod, **kw)
    df.to_csv(Path(pasta) / f"complementares_{cod}.csv", index=False)
    return df


def resumo(df: pd.DataFrame) -> dict:
    """Agregado do município (é o que pode ir a público): contagem por status e por motivo."""
    out = {s: int((df.complementar_status == s).sum()) for s in STATUS}
    motivos = df.complementar_motivos.dropna().str.split("|").explode()
    out["motivos"] = {k: int(v) for k, v in motivos.value_counts().items()}
    out["imoveis"] = int(len(df))
    return out
