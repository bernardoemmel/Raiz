"""Restrições nacionais de cada CAR do município (tarefa "restricoes" do executor, folha do grafo).

Entrada: geo_<mun>.parquet (CAR de imóvel rural do funil), imoveis_<mun>.csv (área), o CAR completo do município
(todos os tipos: imóvel rural IRU, assentamento AST e povos e comunidades tradicionais PCT; raiz/coleta/car_nacional.py)
e as camadas da coleta (raiz/restricoes/coleta.py, em RAIZ_RESTRICOES_DIR ou cache/restricoes).
Saída: restricoes_<mun>.csv, uma linha por imóvel (colunas em docs/colunas.md e COLUNAS abaixo):
  restricao_nacional   exclusao (sai do lote) | ressalva (fica marcado) | livre | nao_verificado
  restricao_motivos    códigos separados por "|" (raiz/regras/padroes/restricoes_nacionais.yaml, seção motivos)
  restricoes_nao_verificadas  fontes que não cobriram o imóvel (ex.: car_temas enquanto a base do SICAR não abre)
  e as medidas de cada fonte (ha de sobreposição, contagens, até 3 processos ou autos).
Regras:
  "livre" só quando todas as fontes essenciais cobriram o imóvel e nada cruzou: ausência de dado nunca vira livre.
  Sobreposição conta quando passa de limiar_ha ou de limiar_fracao do imóvel (imóvel pequeno conta pela fração);
  abaixo de tolerancia_ha é ruído de contorno. Nunca descarta imóvel por tamanho.
Sem nome, CPF ou CNPJ: a Lista Suja chega aqui só como vínculo geográfico (o auto ou embargo do infrator listado).
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
import numpy as np
import pandas as pd
import shapely
import yaml

from raiz.restricoes.coleta import NOMES

REGRA = Path(__file__).parents[1] / "regras" / "padroes" / "restricoes_nacionais.yaml"
CRS_AREA = 5880
COLUNAS = [
    "cod_imovel",
    "restricao_nacional",
    "restricao_motivos",
    "restricoes_nao_verificadas",
    "car_status",
    "car_pct_ha",
    "car_ast_ha",
    "car_sobreposto_ha",
    "car_sobreposto_n",
    "rl_declarada_ha",
    "app_declarada_ha",
    "rl_app_alheia_ha",
    "mineracao_lavra_ha",
    "mineracao_pesquisa_ha",
    "mineracao_processos",
    "ibama_autos_n",
    "ibama_autos_flora_recente_n",
    "ibama_auto_ultimo_ano",
    "ibama_autos_ids",
    "lista_suja_vinculo",
    "lista_suja_municipio_rurais",
    "restricoes_versao",
]
STATUS = ("exclusao", "ressalva", "livre", "nao_verificado")
FONTES = ("sicar_car", "car_temas", "sigmine", "ibama_autos", "lista_suja")
log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def regra() -> dict:
    return yaml.safe_load(REGRA.read_text(encoding="utf-8"))


def pasta_camadas() -> Path:
    if os.environ.get("RAIZ_RESTRICOES_DIR"):
        return Path(os.environ["RAIZ_RESTRICOES_DIR"])
    from raiz.funil.rodar import dir_trabalho

    return dir_trabalho() / "cache" / "restricoes"


def assinatura(pasta: Path | None = None) -> str | None:
    """Muda quando a coleta muda (o executor usa para refazer só esta tarefa)."""
    pasta = Path(pasta) if pasta else pasta_camadas()
    m = pasta / NOMES["cobertura"]
    if not m.exists():
        return None
    h = hashlib.sha256(m.read_bytes())
    for f in sorted(pasta.glob("restricoes_*")):
        if f.name != NOMES["cobertura"]:
            h.update(f.name.encode() + str(f.stat().st_size).encode())
    return h.hexdigest()[:16]


def versao() -> str:
    return f"{regra()['versao']}+{hashlib.sha256(REGRA.read_bytes()).hexdigest()[:8]}"


# --- camadas -----------------------------------------------------------------------------------------------------


class Camadas:
    """As camadas da coleta já lidas (uma vez por processo; a tarefa roda muitos municípios)."""

    def __init__(self, pasta: Path | None = None):
        self.pasta = Path(pasta) if pasta else pasta_camadas()
        m = self.pasta / NOMES["cobertura"]
        self.cobertura = json.loads(m.read_text(encoding="utf-8")).get("fontes", {}) if m.exists() else {}
        self.sigmine = self._geo("sigmine")
        self.autos = self._geo("ibama_autos")
        self.vinculos = self._geo("lista_suja_vinculos")
        f = self.pasta / NOMES["lista_suja_municipios"]
        self.lista_mun = pd.read_csv(f) if f.exists() else None

    def _geo(self, nome):
        f = self.pasta / NOMES[nome]
        if not f.exists():
            return None
        g = gpd.read_parquet(f)
        return (g.set_crs(4674) if g.crs is None else g).to_crs(CRS_AREA)

    def car_temas(self, uf: str):
        f = self.pasta / f"restricoes_car_temas_{uf}.parquet"
        if not f.exists():
            return None
        g = gpd.read_parquet(f)
        return (g.set_crs(4674) if g.crs is None else g).to_crs(CRS_AREA)

    def coberta(self, fonte: str, uf: str) -> bool:
        c = self.cobertura.get(fonte) or {}
        if fonte == "sigmine":
            return c.get("estado") in ("consultado", "parcial") and uf in (c.get("ufs") or [])
        if fonte == "lista_suja":
            return c.get("estado") == "consultado" and self.vinculos is not None
        if fonte == "ibama_autos":
            return c.get("estado") == "consultado" and self.autos is not None
        return c.get("estado") == "consultado"


def car_completo(uf: str, cod: int):
    """CAR de todos os tipos no município (o funil guarda só o imóvel rural). None quando o CAR nacional falha."""
    from raiz.coleta import car_nacional
    from raiz.funil.rodar import dir_trabalho

    try:
        return car_nacional.municipio(uf, int(cod), dir_trabalho() / "cache")
    except Exception as ex:  # noqa: BLE001 - sem CAR completo a parte do SICAR fica não verificada
        log.warning("CAR completo de %s indisponível (%s)", cod, type(ex).__name__)
        return None


# --- medidas -----------------------------------------------------------------------------------------------------


def _uniao_por_imovel(base: gpd.GeoDataFrame, camada, excluir_mesmo_cod: str | None = None) -> pd.Series:
    """ha da união das partes da camada dentro de cada imóvel (sobreposição dentro da camada conta uma vez)."""
    out = pd.Series(0.0, index=base.cod_imovel.values)
    if camada is None or not len(camada) or not len(base):
        return out
    ib, ic = camada.sindex.query(base.geometry.values, predicate="intersects")
    if excluir_mesmo_cod:
        outro = camada[excluir_mesmo_cod].astype(str).values[ic] != base.cod_imovel.astype(str).values[ib]
        ib, ic = ib[outro], ic[outro]
    if not len(ib):
        return out
    pol = np.array([g.geom_type in ("Polygon", "MultiPolygon") for g in camada.geometry.values])
    sel = pol[ic]
    ib, ic = ib[sel], ic[sel]
    partes = shapely.intersection(base.geometry.values[ib], camada.geometry.values[ic])
    t = pd.DataFrame({"i": ib, "g": partes})
    for i, grupo in t.groupby("i"):
        out.iloc[i] = shapely.union_all(grupo.g.values).area / 1e4
    return out


def _cruzados(base: gpd.GeoDataFrame, camada, tolerancia_ha: float) -> dict[int, list[int]]:
    """Para cada imóvel (posição), os objetos da camada dentro dele: ponto dentro ou polígono com mais que a
    tolerância."""
    if camada is None or not len(camada) or not len(base):
        return {}
    ib, ic = camada.sindex.query(base.geometry.values, predicate="intersects")
    if not len(ib):
        return {}
    g = camada.geometry.values[ic]
    ponto = np.array([x.geom_type in ("Point", "MultiPoint") for x in g])
    area = np.zeros(len(ib))
    if (~ponto).any():
        area[~ponto] = shapely.area(shapely.intersection(base.geometry.values[ib[~ponto]], g[~ponto])) / 1e4
    ok = ponto | (area >= tolerancia_ha)
    out: dict[int, list[int]] = {}
    for i, c in zip(ib[ok], ic[ok], strict=True):
        out.setdefault(int(i), []).append(int(c))
    return out


def _tipo(car, tipo):
    t = car[car.tipo_imovel.astype(str).str.upper() == tipo]
    return t if len(t) else None


def _ativos(car):
    if car is None:
        return None
    car = car.to_crs(CRS_AREA)
    if "status_imovel" in car.columns:
        car = car[car.status_imovel.astype(str).str.upper() != "CA"]
    car = car[car.geometry.notna() & ~car.geometry.is_empty].copy()
    car["geometry"] = shapely.make_valid(car.geometry.values)
    return car.reset_index(drop=True)


def _sobreposicao_car(base, car, tol):
    """ha e quantos outros CAR de imóvel rural se sobrepõem a cada imóvel."""
    iru = _tipo(car, "IRU")
    ha = _uniao_por_imovel(base, iru, excluir_mesmo_cod="cod_imovel")
    n = pd.Series(0, index=base.cod_imovel.values)
    if iru is not None:
        ib, ic = iru.sindex.query(base.geometry.values, predicate="intersects")
        outro = iru.cod_imovel.astype(str).values[ic] != base.cod_imovel.astype(str).values[ib]
        ib, ic = ib[outro], ic[outro]
        if len(ib):
            a = shapely.area(shapely.intersection(base.geometry.values[ib], iru.geometry.values[ic])) / 1e4
            cont = pd.Series(a >= tol).groupby(ib).sum()
            n.iloc[cont.index.values] = cont.values
    return ha, n


# --- classificação -----------------------------------------------------------------------------------------------


def _passa(x, ha, r) -> bool:
    return x is not None and x > 0 and (x >= r["limiar_ha"] or (bool(ha) and x / ha >= r["limiar_fracao"]))


def classificar(m: dict, ha: float | None, verificadas: set[str], r: dict | None = None) -> tuple[str, list[str]]:
    """(status, motivos) de um imóvel a partir das medidas. Exclusão vem antes de ressalva; os motivos ficam todos."""
    r = r or regra()
    tol = r["tolerancia_ha"]
    exc, res = [], []
    if m.get("lista_suja_vinculo"):
        exc.append("lista_suja")
    elif (m.get("lista_suja_borda_ha") or 0) >= tol:
        res.append("lista_suja_borda")
    lavra = m.get("mineracao_lavra_ha")
    if _passa(lavra, ha, r):
        exc.append("mineracao_lavra")
    elif (lavra or 0) >= tol:
        res.append("mineracao_lavra_borda")
    if (m.get("mineracao_pesquisa_ha") or 0) >= tol:
        res.append("mineracao_pesquisa")
    pct = m.get("car_pct_ha")
    if _passa(pct, ha, r):
        exc.append("territorio_tradicional")
    elif (pct or 0) >= tol:
        res.append("territorio_tradicional_borda")
    if _passa(m.get("car_ast_ha"), ha, r):
        res.append("assentamento_sobreposto")
    if _passa(m.get("car_sobreposto_ha"), ha, r):
        res.append("car_sobreposto")
    if _passa(m.get("rl_app_alheia_ha"), ha, r):
        res.append("rl_app_alheia")
    if m.get("car_status") in ("SU", "CA"):
        res.append("car_suspenso")
    elif m.get("car_status") == "PE":
        res.append("car_pendente")
    if m.get("ibama_autos_flora_recente_n"):
        res.append("ibama_auto_flora_recente")
    elif m.get("ibama_autos_n"):
        res.append("ibama_auto")
    if exc:
        return "exclusao", exc + res
    if res:
        return "ressalva", res
    if set(r["fontes_essenciais"]) <= verificadas:
        return "livre", []
    return "nao_verificado", []


def calcular_municipio(pasta: str | Path, cod: int, camadas: Camadas | None = None, car=None, hoje: str | None = None):
    """DataFrame com COLUNAS para o município. `car` = CAR completo (todos os tipos); None busca no CAR nacional."""
    pasta = Path(pasta)
    r = regra()
    tol = r["tolerancia_ha"]
    hoje = hoje or dt.date.today().isoformat()
    camadas = camadas or Camadas()
    base = gpd.read_parquet(pasta / f"geo_{cod}.parquet")[["cod_imovel", "geometry"]]
    base = (base.set_crs(4674) if base.crs is None else base).to_crs(CRS_AREA)
    base = base[base.geometry.notna()].reset_index(drop=True)
    base["geometry"] = shapely.make_valid(base.geometry.values)
    base["cod_imovel"] = base.cod_imovel.astype(str)
    uf = base.cod_imovel.iloc[0].split("-")[0] if len(base) else ""
    ha = {}
    f = pasta / f"imoveis_{cod}.csv"
    if f.exists():
        im = pd.read_csv(f, usecols=lambda c: c in ("cod_imovel", "ha"), dtype={"cod_imovel": str})
        ha = dict(zip(im.cod_imovel, im.ha, strict=True)) if "ha" in im.columns else {}
    for c in base.cod_imovel:
        if c not in ha or pd.isna(ha[c]):
            ha[c] = float(base.loc[base.cod_imovel == c].geometry.area.iloc[0] / 1e4)

    verificadas = {f for f in ("sigmine", "ibama_autos", "lista_suja") if camadas.coberta(f, uf)}
    medidas = {c: {} for c in base.cod_imovel}

    # SICAR: situação do cadastro, povos e comunidades tradicionais, assentamentos e sobreposição entre CARs
    car = car_completo(uf, cod) if car is None else car
    if car is not None and "status_imovel" in car.columns:
        situacao = dict(zip(car.cod_imovel.astype(str), car.status_imovel.astype(str).str.upper(), strict=False))
        for c in base.cod_imovel:
            if c in situacao:
                medidas[c]["car_status"] = situacao[c]
    car = _ativos(car)
    if car is not None and "tipo_imovel" in car.columns:
        verificadas.add("sicar_car")
        pct = _uniao_por_imovel(base, _tipo(car, "PCT"))
        ast = _uniao_por_imovel(base, _tipo(car, "AST"))
        sob_ha, sob_n = _sobreposicao_car(base, car, tol)
        for c in base.cod_imovel:
            medidas[c].update(car_pct_ha=round(pct[c], 4), car_ast_ha=round(ast[c], 4),
                              car_sobreposto_ha=round(sob_ha[c], 4), car_sobreposto_n=int(sob_n[c]))  # fmt: skip

    # RL e APP declaradas no CAR (quando a base de downloads do SICAR chegar)
    temas = camadas.car_temas(uf)
    if temas is not None:
        verificadas.add("car_temas")
        alheia = _uniao_por_imovel(base, temas, excluir_mesmo_cod="cod_imovel")
        proprias = temas[temas.cod_imovel.astype(str).isin(set(base.cod_imovel))]
        for c in base.cod_imovel:
            p = proprias[proprias.cod_imovel.astype(str) == c]
            rl = p[p.tema == "reserva_legal"].geometry
            app = p[p.tema == "app"].geometry
            medidas[c].update(
                rl_app_alheia_ha=round(alheia[c], 4),
                rl_declarada_ha=round(shapely.union_all(rl.values).area / 1e4, 4) if len(rl) else 0.0,
                app_declarada_ha=round(shapely.union_all(app.values).area / 1e4, 4) if len(app) else 0.0,
            )

    # SIGMINE
    if "sigmine" in verificadas:
        sg = camadas.sigmine
        lavra_fases = {x.upper() for x in r["mineracao"]["lavra"]}
        inativas = {x.upper() for x in r["mineracao"]["inativas"]}
        sg = sg[~sg.fase.fillna("").str.upper().isin(inativas)] if sg is not None else None
        lav = sg[sg.fase.fillna("").str.upper().isin(lavra_fases)] if sg is not None else None
        pes = sg[~sg.fase.fillna("").str.upper().isin(lavra_fases)] if sg is not None else None
        h_lav, h_pes = _uniao_por_imovel(base, lav), _uniao_por_imovel(base, pes)
        quais = _cruzados(base, sg, tol)
        for i, c in enumerate(base.cod_imovel):
            procs = [] if sg is None else list(dict.fromkeys(str(sg.processo.iloc[j]) for j in quais.get(i, [])))[:3]
            medidas[c].update(mineracao_lavra_ha=round(h_lav[c], 4), mineracao_pesquisa_ha=round(h_pes[c], 4),
                              mineracao_processos="|".join(procs) or None)  # fmt: skip

    # Autos de infração do Ibama (os de infrator da Lista Suja contam lá, não aqui)
    if "ibama_autos" in verificadas:
        au = camadas.autos
        au = au[~au.lista_suja.fillna(False).astype(bool)] if au is not None else None
        quais = _cruzados(base, au, tol)
        recente = int(hoje[:4]) - r["ibama_autos"]["flora_recente_anos"]
        for i, c in enumerate(base.cod_imovel):
            s = au.iloc[quais.get(i, [])] if au is not None else None
            n = 0 if s is None else len(s)
            flora = 0 if s is None else int(((s.tipo_infracao == "Flora") & (s.ano.astype(float) >= recente)).sum())
            medidas[c].update(
                ibama_autos_n=n,
                ibama_autos_flora_recente_n=flora,
                ibama_auto_ultimo_ano=int(s.ano.max()) if n else None,
                ibama_autos_ids=(
                    "|".join(s.sort_values("ano", ascending=False).auto_id.astype(str).head(3)) if n else None
                ),  # fmt: skip
            )

    # Lista Suja: vínculo geográfico (auto ou embargo do infrator listado dentro do imóvel)
    if "lista_suja" in verificadas:
        v = camadas.vinculos
        dentro = _cruzados(base, v, 0.0)
        area = _uniao_por_imovel(base, v)
        for i, c in enumerate(base.cod_imovel):
            objs = v.iloc[dentro.get(i, [])] if v is not None and len(v) else None
            ponto = objs is not None and objs.geometry.geom_type.isin(["Point", "MultiPoint"]).any()
            medidas[c].update(lista_suja_vinculo=bool(ponto or _passa(area[c], ha[c], r)),
                              lista_suja_borda_ha=area[c])  # fmt: skip
    rurais = None
    if camadas.lista_mun is not None and camadas.cobertura.get("lista_suja", {}).get("estado") in (
        "consultado",
        "parcial",
    ):
        lm = camadas.lista_mun
        rurais = int(lm.loc[lm.cod_ibge.astype(int) == int(cod), "rurais"].sum())

    linhas = []
    for c in base.cod_imovel:
        m = medidas[c]
        status, motivos = classificar(m, ha.get(c), verificadas, r)
        linha = {k: m.get(k) for k in COLUNAS if k in m}
        linha.update(
            cod_imovel=c,
            restricao_nacional=status,
            restricao_motivos="|".join(motivos) or None,
            restricoes_nao_verificadas="|".join(f for f in FONTES if f not in verificadas) or None,
            lista_suja_municipio_rurais=rurais,
        )
        linhas.append(linha)
    df = pd.DataFrame(linhas, columns=COLUNAS)
    df["restricoes_versao"] = f"{versao()}+{assinatura(camadas.pasta) or 'sem_coleta'}"
    return df[COLUNAS]


def escrever_municipio(pasta: str | Path, cod: int, **kw) -> pd.DataFrame:
    df = calcular_municipio(pasta, cod, **kw)
    df.to_csv(Path(pasta) / f"restricoes_{cod}.csv", index=False)
    return df


def resumo(df: pd.DataFrame) -> dict:
    """Agregado do município (é o que pode ir a público): contagem por status e por motivo."""
    out = {s: int((df.restricao_nacional == s).sum()) for s in STATUS}
    motivos = df.restricao_motivos.dropna().str.split("|").explode()
    out["motivos"] = {k: int(v) for k, v in motivos.value_counts().items()}
    out["imoveis"] = int(len(df))
    return out
