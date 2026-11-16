"""Caminho da terra por imóvel: a situação da terra deixa de ser corte e vira caminho com risco (ninguém sai do mapa
por falta de matrícula). Regra em raiz/regras/padroes/caminho_terra.yaml, concessões e editais em concessoes.yaml.

Calculado pelo produto, fora do motor, e gravado em terra_<mun>.csv (docs/colunas.md):
  caminho_terra       privada_matricula, posse_em_titulacao, assentamento, publica_concessao,
                      publica_sem_destinacao ou terra_indigena_ou_tradicional
  risco_terra         baixo, medio ou alto, com risco_terra_motivo (a regra escrita e o porquê)
As áreas vêm da sobreposição do CAR com o SIGEF do espelho (natureza e estado da parcela), o Cadastro Nacional de
Florestas Públicas (SFB), as unidades de conservação por categoria (CNUC), terras indígenas e quilombos; sem elas,
das colunas do motor (matricula_ha, sigef_ha, assentamento_ha, ti_ha, quilombo_ha...), dizendo a fonte.
"""

from __future__ import annotations

import hashlib
import math
from functools import lru_cache
from pathlib import Path

import yaml

PADROES = Path(__file__).parent / "regras" / "padroes"
ARQ_REGRA = PADROES / "caminho_terra.yaml"
ARQ_CONCESSOES = PADROES / "concessoes.yaml"
CAMINHOS = (
    "privada_matricula",
    "posse_em_titulacao",
    "assentamento",
    "publica_concessao",
    "publica_sem_destinacao",
    "terra_indigena_ou_tradicional",
)
RISCOS = ("baixo", "medio", "alto")
NOME_RISCO = {"baixo": "baixo", "medio": "médio", "alto": "alto"}


@lru_cache
def _ler(regra: Path, concessoes: Path, _marcas: tuple = ()) -> dict:
    textos = [regra.read_bytes(), concessoes.read_bytes()]
    r = yaml.safe_load(textos[0])
    r["concessoes"] = yaml.safe_load(textos[1])
    r["versao_completa"] = f"{r['versao']}+{hashlib.sha256(b'--'.join(textos)).hexdigest()[:8]}"
    return r


def regra(regra: Path | None = None, concessoes: Path | None = None) -> dict:
    arqs = (Path(regra or ARQ_REGRA), Path(concessoes or ARQ_CONCESSOES))
    return _ler(*arqs, tuple((str(a), a.stat().st_mtime_ns, a.stat().st_size) for a in arqs))


def versao() -> str:
    return regra()["versao_completa"]


def concessao(id_: str | None, r: dict | None = None) -> dict | None:
    if not id_:
        return None
    r = r or regra()
    return next((c for c in r["concessoes"]["concessoes"] if c["id"] == id_), None)


# --- leitura pelo nome ---------------------------------------------------------------------------------------------


def _num(linha: dict, c: str) -> float | None:
    v = linha.get(c)
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _n0(linha: dict, c: str) -> float:
    return _num(linha, c) or 0.0


def _bool(linha: dict, c: str) -> bool:
    v = linha.get(c)
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "sim", "t")
    return bool(v) if v is not None and not (isinstance(v, float) and math.isnan(v)) else False


def entradas(linha: dict) -> dict:
    """Áreas (ha) de cada situação da terra no imóvel. Prefere a sobreposição medida pelo produto (terra_*_ha) e cai
    para as colunas do motor quando ela não existe."""
    ha = _n0(linha, "ha") or _n0(linha, "area")
    medido = _num(linha, "terra_sigef_registrada_ha") is not None
    mat = _num(linha, "terra_sigef_registrada_ha")
    if mat is None:
        mat = _num(linha, "matricula_ha")
        if mat is None:
            mat = (_num(linha, "f_matricula") or 0.0) * ha
    assent = _num(linha, "terra_sigef_assentamento_ha")
    if assent is None:
        assent = _n0(linha, "assentamento_ha")
    posse = _num(linha, "terra_sigef_posse_ha")
    if posse is None:  # do motor: SIGEF que não é matrícula nem assentamento
        posse = max(_n0(linha, "sigef_ha") - mat - assent, 0.0)
    trad = _num(linha, "terra_tradicional_ha")
    if trad is None:
        trad = max(_n0(linha, "ti_ha"), _n0(linha, "ti_funai_ha")) + _n0(linha, "quilombo_ha")
    publica = _num(linha, "terra_publica_ha")
    if publica is None:  # do motor só se sabe da proteção integral (sem a gleba pública)
        publica = _n0(linha, "uc_protecao_integral_ha")
    return {
        "ha": ha,
        "fonte": "sobreposicao" if medido else "motor",
        "matricula": mat,
        "titulacao": _n0(linha, "terra_sigef_titulacao_ha"),
        "posse_sigef": posse,
        "assentamento": assent,
        "assentamento_titulado": _n0(linha, "terra_sigef_assentamento_titulado_ha"),
        "ast": str(linha.get("tipo_imovel") or "").upper() == "AST",
        "publica": min(publica, ha) if ha else publica,
        "tradicional": trad,
        "concessao": linha.get("terra_concessao") or None,
        "concessao_ha": _n0(linha, "terra_concessao_ha"),
        "sigef_total": _n0(linha, "sigef_ha"),
        "conferida": _bool(linha, "matricula_conferida"),
        "uf": str(linha.get("uf") or "").upper(),
    }


def _pct(x: float, ha: float) -> str:
    return f"{100 * x / ha:.0f}%" if ha > 0 else "0%"


def caminho(linha: dict, r: dict | None = None) -> dict:
    """Caminho da terra, risco e o porquê de cada um."""
    r = r or regra()
    L = r["limiares"]
    e = entradas(linha)
    ha = e["ha"]
    fr = (lambda x: x / ha) if ha > 0 else (lambda x: 0.0)
    if e["tradicional"] >= L["tradicional_min_ha"] and fr(e["tradicional"]) >= L["tradicional_min_fracao"]:
        cam = "terra_indigena_ou_tradicional"
        motivo = (
            f"{e['tradicional']:.0f} ha ({_pct(e['tradicional'], ha)}) em terra indígena, quilombo ou reserva "
            "tradicional."
        )
    elif e["concessao"] and fr(e["concessao_ha"]) >= L["fracao_caminho"]:
        cam = "publica_concessao"
        c = concessao(e["concessao"], r) or {}
        nome = c.get("nome", "área pública concedida")
        motivo = f"{_pct(e['concessao_ha'], ha)} dentro de {nome} ({c.get('orgao', '')})."
    elif fr(e["publica"]) >= L["fracao_caminho"]:
        cam = "publica_sem_destinacao"
        motivo = (
            f"{_pct(e['publica'], ha)} sobre gleba pública não destinada ou unidade de conservação de domínio público."
        )
    elif e["ast"] or fr(e["assentamento"]) >= L["fracao_caminho"]:
        cam = "assentamento"
        motivo = (
            "Cadastrado no CAR como lote de assentamento."
            if e["ast"]
            else f"{_pct(e['assentamento'], ha)} sobre parcela de assentamento do INCRA no SIGEF."
        )
    elif fr(e["matricula"]) >= L["fracao_caminho"]:
        cam = "privada_matricula"
        motivo = f"Matrícula achada no SIGEF em {_pct(e['matricula'], ha)} do CAR."
    else:
        cam = "posse_em_titulacao"
        if e["titulacao"] > 0:
            motivo = f"Parcela em titulação no SIGEF em {_pct(e['titulacao'], ha)} do CAR; sem matrícula."
        elif e["posse_sigef"] > 0:
            motivo = f"Posse certificada no SIGEF em {_pct(e['posse_sigef'], ha)} do CAR; sem matrícula."
        else:
            motivo = "Posse declarada no CAR, sem parcela no SIGEF nem matrícula achada."
    risco, porque = _risco(cam, e, r)
    c = r["caminhos"][cam]
    conc = concessao(e["concessao"], r) if cam == "publica_concessao" else None
    return {
        "caminho_terra": cam,
        "caminho_terra_rotulo": c["nome"],
        "caminho_terra_situacao": c["situacao"],
        "caminho_terra_motivo": motivo,
        "caminho_terra_aviso": " ".join(str(c.get("aviso") or "").split()),
        "risco_terra": risco,
        "risco_terra_motivo": porque,
        "profloresta_fase1": bool(c["profloresta_fase1"]),
        "terra_concessao": conc["id"] if conc else None,
        "terra_concessao_situacao": conc["situacao"] if conc else None,
        "terra_concessao_data": conc["data"] if conc else None,
        "terra_concessao_link": conc["link"] if conc else None,
        "terra_fonte": e["fonte"],
        "terra_regra_versao": r["versao_completa"],
    }


def _risco(cam: str, e: dict, r: dict) -> tuple[str, str]:
    L = r["limiares"]
    ha = e["ha"]
    fr = (lambda x: x / ha) if ha > 0 else (lambda x: 0.0)
    if cam in ("terra_indigena_ou_tradicional", "publica_sem_destinacao"):
        return "alto", "Terra que não se origina com particular."
    if cam == "publica_concessao":
        c = concessao(e["concessao"], r) or {}
        if c.get("situacao") == "contratada":
            return "baixo", f"Contrato de concessão assinado em {c.get('data', '')}."
        return "medio", "Concessão ainda em edital: depende do resultado da licitação."
    if cam == "assentamento":
        if e["assentamento_titulado"] > 0 and fr(e["assentamento_titulado"]) >= L["fracao_caminho"]:
            return "medio", "Lote titulado no SIGEF; depende de aval do INCRA."
        return "alto", "Lote sem título no SIGEF; depende de aval do INCRA."
    if cam == "posse_em_titulacao":
        if e["titulacao"] > 0 or e["posse_sigef"] > 0:
            return "medio", "Posse com parcela no SIGEF (certificada ou em titulação), ainda sem matrícula."
        return "alto", "Posse só declarada no CAR, sem parcela no SIGEF."
    # privada com matrícula
    if fr(e["publica"]) >= L["sobreposicao_alerta"] or fr(e["tradicional"]) >= L["sobreposicao_alerta"]:
        return "alto", "Matrícula com sobreposição a terra pública, unidade de conservação ou terra indígena."
    motivos = []
    if not e["conferida"]:
        motivos.append("matrícula ainda não conferida no cartório")
    if fr(e["matricula"]) < L["matricula_firme"]:
        motivos.append(f"matrícula em {_pct(e['matricula'], ha)} do CAR")
    if e["uf"] == "PA" and not e["conferida"]:
        motivos.append("no Pará, conferir cancelamentos (Provimentos CGJ-PA 13/2006 e 02/2010)")
    if ha >= L["sem_sigef_ha"] and e["sigef_total"] < 0.5 * ha:
        motivos.append("101 ha ou mais sem SIGEF certificado")
    if motivos:
        texto = "; ".join(motivos)
        return "medio", texto[:1].upper() + texto[1:] + "."
    return "baixo", "Matrícula conferida no cartório, em 90% ou mais do CAR."


MOTIVO_ETAPA = {
    "privada_matricula": ("titulo", "Matrícula ainda não conferida no cartório"),
    "posse_em_titulacao": ("terra_posse", "Posse em titulação: entra quando o título sair"),
    "assentamento": ("terra_assentamento", "Lote de assentamento: depende de aval do INCRA"),
    "publica_sem_destinacao": ("terra_publica", "Terra pública sem destinação: só candidata a concessão"),
    "terra_indigena_ou_tradicional": (
        "terra_tradicional",
        "Terra indígena ou tradicional: fora da originação comercial",
    ),
}


def do_imovel(linha: dict, r: dict | None = None) -> dict:
    """O caminho já gravado em terra_<mun>.csv (vem na linha) ou, sem ele, calculado das colunas do motor."""
    cam = linha.get("caminho_terra")
    if isinstance(cam, str) and cam in CAMINHOS and linha.get("risco_terra"):
        return linha
    return {**linha, **caminho(linha, r)}


def bloco_ficha(linha: dict, r: dict | None = None) -> dict:
    """Bloco "Caminho da terra" da ficha: caminho, situação (pronta agora, em espera, só mostrar), risco com o
    motivo, aviso do que falta (caminhos 2, 3 e 5) e a base legal. Nunca chama posse de propriedade."""
    r = r or regra()
    d = do_imovel(linha, r)
    cam = d["caminho_terra"]
    c = r["caminhos"][cam]
    return {
        "caminho": cam,
        "nome": c["nome"],
        "situacao": c["situacao"],
        "situacao_nome": r["situacoes"][c["situacao"]],
        "texto": c["texto"],
        "motivo": d.get("caminho_terra_motivo"),
        "risco": d.get("risco_terra"),
        "risco_nome": NOME_RISCO.get(d.get("risco_terra"), d.get("risco_terra")),
        "risco_motivo": d.get("risco_terra_motivo"),
        "aviso": " ".join(str(c.get("aviso") or "").split()) or None,
        "profloresta_fase1": bool(c["profloresta_fase1"]),
        "concessao": concessao(d.get("terra_concessao"), r),
        "base_legal": [{"id": b, "texto": " ".join(r["base_legal"][b].split())} for b in c.get("base", [])],
        "regra_risco": " ".join(r["risco"]["regra"].split()),
        "fonte": d.get("terra_fonte"),
        "versao": d.get("terra_regra_versao") or r["versao_completa"],
    }


def selo_prata(linha: dict) -> bool:
    """Prata só para privada com matrícula conferida ou pública sob concessão."""
    cam = linha.get("caminho_terra")
    if not isinstance(cam, str) or cam not in CAMINHOS:
        cam = caminho(linha)["caminho_terra"]
    return (cam == "privada_matricula" and _bool(linha, "matricula_conferida")) or cam == "publica_concessao"


# --- sobreposições do CAR com as camadas de terra (por município) ------------------------------------------------

SIGEF_CLASSES = (
    "registrada",
    "titulacao",
    "posse",
    "assentamento",
    "assentamento_titulado",
    "gleba_publica",
)


def classes_sigef(sigef) -> dict[str, object]:
    """Parcelas do SIGEF do espelho separadas pela natureza e pelo estado (status, situação informada, envio)."""
    import pandas as pd

    nat = sigef.get("natureza", pd.Series("", index=sigef.index)).fillna("").astype(str)
    sit = sigef.get("situacao_informada", pd.Series("", index=sigef.index)).fillna("").astype(str).str.upper()
    st = sigef.get("status", pd.Series("", index=sigef.index)).fillna("").astype(str).str.upper()
    env = sigef.get("tipo_envio", pd.Series("", index=sigef.index)).fillna("").astype(str).str.lower()
    mat = sigef.get("registro_matricula", pd.Series(None, index=sigef.index)).notna()
    particular = nat.str.lower().eq("particular")
    assent = nat.str.lower().str.startswith("assentamento")
    titulacao = st.eq("TITULACAO") | env.str.contains("titulacao") | sit.eq("TITULADA_NAO_REGISTRADA")
    registrada = particular & (sit.eq("REGISTRADA") | mat | st.eq("REGISTRADA")) & ~titulacao
    return {
        "registrada": sigef[registrada],
        "titulacao": sigef[particular & titulacao],
        "posse": sigef[particular & ~registrada & ~titulacao],
        "assentamento": sigef[assent],
        "assentamento_titulado": sigef[assent & (sit.isin(["REGISTRADA", "TITULADA_NAO_REGISTRADA"]) | mat)],
        "gleba_publica": sigef[nat.str.lower().eq("gleba pública") | nat.str.lower().eq("gleba publica")],
    }


def area_sobreposta(imoveis, camada) -> dict[str, float]:
    """ha de cada imóvel coberto pela camada (união das feições, sem contar duas vezes), em EPSG:5880."""
    import shapely

    if camada is None or len(camada) == 0:
        return {}
    im = imoveis.to_crs(5880)
    partes = camada.to_crs(5880).geometry.explode(index_parts=False)
    partes = shapely.make_valid(partes[~partes.is_empty & partes.notna()].values)
    if len(partes) == 0:
        return {}
    arvore = shapely.STRtree(partes)
    out = {}
    for cod, g in zip(im.cod_imovel.astype(str), im.geometry.values, strict=True):
        if g is None or g.is_empty:
            continue
        idx = arvore.query(g, predicate="intersects")
        if len(idx) == 0:
            continue
        g = shapely.make_valid(g)
        inter = shapely.union_all(shapely.intersection(partes[idx], g))
        a = float(shapely.area(inter)) / 1e4
        if a > 0:
            out[cod] = a
    return out


def arquivo_concessao(c: dict) -> Path | None:
    """Arquivo do polígono exato de uma concessão (baixado uma vez do Release dados para dados/terra_publica/)."""
    import httpx

    from raiz import RAIZ_REPO

    v = c.get("vinculo") or {}
    if not v.get("arquivo"):
        return None
    f = RAIZ_REPO / "dados" / "terra_publica" / "concessoes" / v["arquivo"]
    if not f.exists() and v.get("url"):
        f.parent.mkdir(parents=True, exist_ok=True)
        try:
            r = httpx.get(v["url"], follow_redirects=True, timeout=120)
            r.raise_for_status()
            tmp = f.with_suffix(f.suffix + ".tmp")
            tmp.write_bytes(r.content)
            tmp.replace(f)
        except httpx.HTTPError:
            return None
    return f if f.exists() else None


def poligonos_concessoes(r: dict | None = None):
    """Concessões com polígono exato (ex.: URTX): a união das classes de restauração, uma linha por concessão."""
    import geopandas as gpd
    import pandas as pd
    import shapely

    r = r or regra()
    linhas = []
    for c in r["concessoes"]["concessoes"]:
        f = arquivo_concessao(c)
        if f is None:
            continue
        v = c["vinculo"]
        g = gpd.read_file(f)
        g = g.set_crs(4326) if g.crs is None else g
        if v.get("classes"):
            g = g[g[v.get("campo_classe", "Name")].isin(v["classes"])]
        if len(g):
            u = shapely.union_all(shapely.make_valid(g.to_crs(4674).geometry.values))
            linhas.append({"concessao": c["id"], "geometry": u})
    return gpd.GeoDataFrame(pd.DataFrame(linhas), geometry="geometry", crs=4674) if linhas else None


def camadas_de_terra(caixa, cache_motor: Path | None, cnfp: Path | None, r: dict | None = None) -> dict:
    """Camadas nacionais recortadas na caixa do município: UC por domínio, terra indígena, quilombo, florestas
    públicas não destinadas (CNFP tipo B e C) e as áreas de concessão (UC toda de domínio público com concessão)."""
    import geopandas as gpd
    import pandas as pd

    r = r or regra()
    x0, y0, x1, y1 = caixa
    out: dict[str, object] = {}

    def ultimo(padrao: str) -> Path | None:
        fs = sorted(Path(cache_motor).glob(padrao)) if cache_motor else []
        return fs[-1] if fs else None

    def recorta(f: Path | None):
        if f is None or not f.exists():
            return None
        g = gpd.read_parquet(f)
        g = g.set_crs(4674) if g.crs is None else g.to_crs(4674)
        return g.cx[x0:x1, y0:y1]

    uc = recorta(ultimo("conservationunits_*.parquet"))
    if uc is not None:
        cat = uc["categoria"].fillna("")
        out["uc_publica"] = uc[cat.isin(r["uc"]["dominio_publico"])]
        out["uc_tradicional"] = uc[cat.isin(r["uc"]["tradicional"])]
        conc = []
        for c in r["concessoes"]["concessoes"]:
            nome = (c.get("vinculo") or {}).get("uc")
            if not nome:
                continue
            achadas = uc[uc["nome_uc"].str.upper().eq(nome.upper()) & cat.isin(r["uc"]["dominio_publico"])]
            if len(achadas):  # UC toda de domínio público (Flona): quem está dentro é terra pública concedida
                conc.append(achadas.assign(concessao=c["id"]))
        out["concessoes"] = pd.concat(conc) if conc else None
    exatas = poligonos_concessoes(r)
    if exatas is not None:
        exatas = exatas.cx[x0:x1, y0:y1]
        if len(exatas):
            base = out.get("concessoes")
            out["concessoes"] = exatas if base is None else gpd.GeoDataFrame(
                pd.concat([base[["concessao", "geometry"]], exatas]), crs=4674)  # fmt: skip
    ti = recorta(ultimo("indigenouslands_*.parquet"))
    qu = recorta(ultimo("quilombolalands_*.parquet"))
    trad = [g[["geometry"]] for g in (ti, qu, out.get("uc_tradicional")) if g is not None and len(g)]
    out["tradicional"] = gpd.GeoDataFrame(pd.concat(trad), crs=4674) if trad else None
    if cnfp is not None and Path(cnfp).exists():
        fp = recorta(Path(cnfp))
        if fp is not None and "tipo" in fp:
            out["cnfp_nao_destinada"] = fp[fp["tipo"].astype(str).str.upper().isin(["B", "C", "TIPO B", "TIPO C"])]
    return out


def sobreposicoes(imoveis, sigef, camadas: dict) -> dict[str, dict]:
    """Colunas terra_*_ha por imóvel a partir do SIGEF do espelho e das camadas nacionais."""
    import geopandas as gpd
    import pandas as pd

    cods = imoveis.cod_imovel.astype(str).tolist()
    por = {c: {} for c in cods}

    def grava(nome: str, camada):
        a = area_sobreposta(imoveis, camada)
        for c in cods:
            por[c][nome] = round(a.get(c, 0.0), 4)

    cls = classes_sigef(sigef) if sigef is not None and len(sigef) else {k: None for k in SIGEF_CLASSES}
    for k in ("registrada", "titulacao", "posse", "assentamento", "assentamento_titulado"):
        grava(f"terra_sigef_{k}_ha", cls.get(k))
    fontes_publicas = (cls.get("gleba_publica"), camadas.get("cnfp_nao_destinada"), camadas.get("uc_publica"))
    publicas = [g[["geometry"]].to_crs(4674) for g in fontes_publicas if g is not None and len(g)]
    grava("terra_publica_ha", gpd.GeoDataFrame(pd.concat(publicas), crs=4674) if publicas else None)
    grava("terra_uc_publica_ha", camadas.get("uc_publica"))
    grava("terra_tradicional_ha", camadas.get("tradicional"))
    conc = camadas.get("concessoes")
    if conc is not None and len(conc):
        for cid, g in conc.groupby("concessao"):
            a = area_sobreposta(imoveis, g)
            for c, v in a.items():
                if v > por[c].get("terra_concessao_ha", 0):
                    por[c]["terra_concessao"] = cid
                    por[c]["terra_concessao_ha"] = round(v, 4)
    return por


# --- por município (saida/<UF>/terra_<mun>.csv) ------------------------------------------------------------------


def cnfp_da_uf(uf: str) -> Path | None:
    from raiz import RAIZ_REPO

    f = RAIZ_REPO / "dados" / "terra_publica" / f"cnfp_{uf.upper()}.parquet"
    return f if f.exists() else None


def calcular_municipio(pasta: str | Path, cod: int, cache_motor: Path | None = None, espelho: Path | None = None):
    """terra_<mun>.csv: caminho e risco de TODO imóvel do município (nenhum sai por causa da terra)."""
    import geopandas as gpd
    import pandas as pd

    from raiz.funil import ponte
    from raiz.privacidade import remover_colunas_pessoais

    pasta = Path(pasta)
    uf = pasta.name.upper()
    im, _ = remover_colunas_pessoais(pd.read_csv(pasta / f"imoveis_{cod}.csv", low_memory=False))
    f = pasta / f"filtros_{cod}.csv"
    if f.exists():
        fl = pd.read_csv(f, low_memory=False)
        im = im.merge(fl[[c for c in fl.columns if c == "cod_imovel" or c not in im.columns]], on="cod_imovel",
                      how="left")  # fmt: skip
    im["cod_imovel"] = im.cod_imovel.astype(str)
    from raiz.titulo.regularizacao import arquivo_documentos

    fm = arquivo_documentos(pasta, cod, "matricula")  # matrícula conferida no cartório (raiz/documentos)
    if fm is not None:
        mt = pd.read_csv(fm, usecols=lambda c: c in ("cod_imovel", "matricula_conferida"), dtype={"cod_imovel": str})
        im = im.drop(columns=[c for c in ("matricula_conferida",) if c in im.columns]).merge(mt, on="cod_imovel",
                                                                                             how="left")  # fmt: skip
    por: dict[str, dict] = {}
    geo_f = pasta / f"geo_{cod}.parquet"
    if geo_f.exists():
        geo = gpd.read_parquet(geo_f)[["cod_imovel", "geometry"]]
        geo = geo.set_crs(4674) if geo.crs is None else geo.to_crs(4674)
        sigef = ponte.ler_local(espelho or ponte.espelho_padrao(), "sigef", uf, cod)
        camadas = camadas_de_terra(tuple(geo.total_bounds), cache_motor, cnfp_da_uf(uf))
        por = sobreposicoes(geo, sigef, camadas)
    linhas = []
    for linha in im.to_dict("records"):
        extra = por.get(linha["cod_imovel"], {})
        calc = caminho({**linha, **extra})
        linhas.append({"cod_imovel": linha["cod_imovel"], **calc, **extra})
    return pd.DataFrame(linhas)


def versao_do_arquivo(f: Path) -> str | None:
    import pandas as pd

    if not f.exists():
        return None
    v = pd.read_csv(f, usecols=lambda c: c == "terra_regra_versao", nrows=1)
    return str(v.terra_regra_versao.iloc[0]) if len(v) and "terra_regra_versao" in v else None


def escrever_municipio(pasta: Path, cod: int, cache_motor: Path | None = None) -> dict:
    t = calcular_municipio(pasta, cod, cache_motor)
    f = Path(pasta) / f"terra_{cod}.csv"
    tmp = f.with_suffix(".tmp")
    t.to_csv(tmp, index=False)
    tmp.replace(f)
    return {"imoveis": len(t), **{c: int((t.caminho_terra == c).sum()) for c in CAMINHOS}}


def recalcular(saida: str | Path, ufs: list[str] | None = None, cache_motor: Path | None = None) -> dict:
    from raiz.carga import municipios_na_pasta

    saida = Path(saida)
    atual = versao()
    out = {"refeitos": [], "em_dia": 0, "erros": []}
    for uf in ufs or sorted(p.name for p in saida.iterdir() if p.is_dir() and len(p.name) == 2):
        for cod in municipios_na_pasta(saida / uf):
            if versao_do_arquivo(saida / uf / f"terra_{cod}.csv") == atual:
                out["em_dia"] += 1
                continue
            try:
                escrever_municipio(saida / uf, cod, cache_motor)
                out["refeitos"].append(f"{uf}/{cod}")
            except Exception as e:  # noqa: BLE001
                out["erros"].append(f"{uf}/{cod}: {e}")
    return out


# --- funil do município por caminho ------------------------------------------------------------------------------


def por_caminho(linhas: list[dict], area_col: str = "carbono_ha", r: dict | None = None) -> dict:
    """Barras do funil: imóveis e ha em cada caminho, e o total pronto agora, em espera e só para mostrar.
    Soma exatamente o que entrou (ninguém some por causa da terra)."""
    r = r or regra()
    out = {c: {"imoveis": 0, "ha": 0.0, "nome": r["caminhos"][c]["nome"], "situacao": r["caminhos"][c]["situacao"]}
           for c in CAMINHOS}  # fmt: skip
    sit = {s: {"imoveis": 0, "ha": 0.0, "nome": n} for s, n in r["situacoes"].items()}
    for linha in linhas:
        cam = linha.get("caminho_terra")
        if not isinstance(cam, str) or cam not in CAMINHOS:
            cam = caminho(linha, r)["caminho_terra"]
        a = _n0(linha, area_col)
        out[cam]["imoveis"] += 1
        out[cam]["ha"] += a
        s = r["caminhos"][cam]["situacao"]
        sit[s]["imoveis"] += 1
        sit[s]["ha"] += a
    for d in (*out.values(), *sit.values()):
        d["ha"] = round(d["ha"], 1)
    return {"caminhos": out, "situacoes": sit}
