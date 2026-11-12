"""INPE TerraBrasilis: DETER (alertas quase diários, Amazônia e Cerrado) e PRODES (desmatamento anual).

DETER: lê pela data da imagem (view_date) uma janela de 45 dias (90 na primeira leitura), em páginas, nas camadas de
regras.yaml. O identificador do DETER (gid) muda quando o mês fecha (_curr vira _hist), então a chave é composta:
camada, classe, data da imagem e a geometria arredondada (centro e área).

PRODES: a rodada diária só pergunta qual o último ano publicado em cada camada. Quando sai ano novo (outubro a
dezembro), baixa o ano inteiro nos estados vigiados. O PRODES confirma ou desmente o DETER (marcação automática).
"""

from __future__ import annotations

import datetime as dt
import json
import logging

import geopandas as gpd

from raiz.vigilancia import rede
from raiz.vigilancia.fontes import Contexto, Leitura, data, montar, so_area_vetor, vazio

log = logging.getLogger(__name__)

CRS_METROS = 5880


def _wfs(url: str, camada: str, filtro: str | None, por_pagina: int, ordem: str, maximo: int = 400_000) -> list[dict]:
    feicoes, inicio = [], 0
    while True:
        p = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": camada,
            "outputFormat": "application/json",
            "count": por_pagina,
            "startIndex": inicio,
            "sortBy": ordem,
        }
        if filtro:
            p["CQL_FILTER"] = filtro
        d = json.loads(rede.pedir("GET", url, params=p, timeout=600).content)
        lote = d.get("features") or []
        feicoes += lote
        if len(lote) < por_pagina or len(feicoes) >= maximo:
            return feicoes
        inicio += por_pagina


def _gdf(feicoes: list[dict]) -> gpd.GeoDataFrame:
    if not feicoes:
        return gpd.GeoDataFrame(geometry=[], crs=4674)
    g = gpd.GeoDataFrame.from_features(feicoes, crs=4674)
    g["geometry"] = so_area_vetor(g.geometry.values)
    return g[g.geometry.notna() & ~g.geometry.is_empty]


def _area_ha(g: gpd.GeoDataFrame):
    return (g.to_crs(CRS_METROS).area / 1e4).round(4)


# ---------------------------------------------------------------- DETER


def chave_deter(camada: str, classe: str, view_date, centro, area_ha: float) -> str:
    return f"{camada}|{classe}|{view_date}|{centro.x:.4f}|{centro.y:.4f}|{area_ha:.2f}"


def normalizar_deter(g: gpd.GeoDataFrame, camada: str) -> list[dict]:
    if not len(g):
        return []
    areas = _area_ha(g)
    centros = g.geometry.representative_point()
    linhas = []
    for (_, r), a, c in zip(g.iterrows(), areas, centros, strict=True):
        classe = str(r.get("classname") or "").strip().lower()
        vd = data(r.get("view_date"))
        attrs = {
            k: r.get(k)
            for k in ("gid", "satellite", "sensor", "path_row", "uc", "publish_month", "municipality")
            if k in r and r.get(k) is not None
        }
        attrs["camada"] = camada
        mun = r.get("mun_geocod")
        linhas.append(
            {
                "fonte": "deter",
                "chave": chave_deter(camada, classe, vd, c, float(a)),
                "classe": classe,
                "data_evento": vd,
                "publicado_em": data(r.get("created_date")),  # o DETER Amazônia não diz quando publicou
                "area_ha": float(a),
                "uf": r.get("uf"),
                "cod_municipio_ibge": int(mun) if mun not in (None, "") and str(mun).isdigit() else None,
                "link": "https://terrabrasilis.dpi.inpe.br/app/map/alerts",
                "atributos": {k: (str(v) if not isinstance(v, int | float) else v) for k, v in attrs.items()},
                "car_fonte": None,
                "geometry": r.geometry,
            }
        )
    return linhas


def ler_deter(ctx: Contexto, estado: dict) -> Leitura:
    regra = ctx.regras.fonte("deter")
    dias = regra.get("janela_dias", 45) if estado.get("ultima_leitura") else regra.get("primeira_janela_dias", 90)
    desde = ctx.hoje - dt.timedelta(days=int(dias))
    linhas, notas = [], []
    for camada in regra["camadas"]:
        feicoes = _wfs(regra["url"], camada, f"view_date >= '{desde.isoformat()}'", int(regra["por_pagina"]), "gid")
        linhas += normalizar_deter(_gdf(feicoes), camada)
        notas.append(f"{camada}: {len(feicoes)}")
    oc = montar(linhas).drop_duplicates("chave") if linhas else vazio()
    return Leitura("deter", oc, cursor={"desde": desde.isoformat()}, nota=", ".join(notas))


# ---------------------------------------------------------------- PRODES

ESTADOS = {
    "AC": "ACRE",
    "AL": "ALAGOAS",
    "AP": "AMAPÁ",
    "AM": "AMAZONAS",
    "BA": "BAHIA",
    "CE": "CEARÁ",
    "DF": "DISTRITO FEDERAL",
    "ES": "ESPÍRITO SANTO",
    "GO": "GOIÁS",
    "MA": "MARANHÃO",
    "MT": "MATO GROSSO",
    "MS": "MATO GROSSO DO SUL",
    "MG": "MINAS GERAIS",
    "PA": "PARÁ",
    "PB": "PARAÍBA",
    "PR": "PARANÁ",
    "PE": "PERNAMBUCO",
    "PI": "PIAUÍ",
    "RJ": "RIO DE JANEIRO",
    "RN": "RIO GRANDE DO NORTE",
    "RS": "RIO GRANDE DO SUL",
    "RO": "RONDÔNIA",
    "RR": "RORAIMA",
    "SC": "SANTA CATARINA",
    "SP": "SÃO PAULO",
    "SE": "SERGIPE",
    "TO": "TOCANTINS",
}


def _sem_acento(s: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


_UF_DO_NOME = {_sem_acento(n): uf for uf, n in ESTADOS.items()}


def uf_de(valor) -> str | None:
    """Sigla da UF a partir da sigla ou do nome do estado (com ou sem acento, qualquer caixa)."""
    if valor is None:
        return None
    s = _sem_acento(str(valor).strip().upper())
    return s if s in ESTADOS else _UF_DO_NOME.get(s)


def _valores_uf(ufs: list[str], por_nome: bool) -> list[str]:
    if not por_nome:
        return list(ufs)
    out = []
    for uf in ufs:
        n = ESTADOS.get(uf)
        if n:
            out += [n] if n == _sem_acento(n) else [n, _sem_acento(n)]
    return out


def ultimo_ano(url: str, camada: str, campo_ano: str) -> tuple[int | None, str | None]:
    feicoes = _wfs(url, camada, None, 1, f"{campo_ano} D", maximo=1)
    if not feicoes:
        return None, None
    p = feicoes[0]["properties"]
    return int(p[campo_ano]), str(p.get("pub_date") or "")


def normalizar_prodes(g: gpd.GeoDataFrame, camada: str, campo_uf: str) -> list[dict]:
    if not len(g):
        return []
    if "main_class" in g:
        g = g[g["main_class"].astype(str).str.upper().isin(["DESMATAMENTO", "DEFORESTATION"])]
    areas = _area_ha(g)
    linhas = []
    for (_, r), a in zip(g.iterrows(), areas, strict=True):
        ident = r.get("uuid") or r.get("fid") or r.name
        attrs = {
            k: (str(r.get(k)) if r.get(k) is not None else None)
            for k in ("class_name", "sub_class", "image_date", "satellite", "sensor", "pub_date", "year", "source")
            if k in r
        }
        attrs["camada"] = camada
        linhas.append(
            {
                "fonte": "prodes",
                "chave": f"{camada}|{ident}",
                "classe": "desmatamento",
                "data_evento": data(r.get("image_date")) or (dt.date(int(r["year"]), 7, 31) if r.get("year") else None),
                "publicado_em": data(r.get("pub_date")),
                "area_ha": float(a),
                "uf": uf_de(r.get(campo_uf)),
                "cod_municipio_ibge": None,
                "link": "https://terrabrasilis.dpi.inpe.br/app/map/deforestation",
                "atributos": attrs,
                "car_fonte": None,
                "geometry": r.geometry,
            }
        )
    return linhas


def ler_prodes(ctx: Contexto, estado: dict) -> Leitura:
    regra = ctx.regras.fonte("prodes")
    cursor = dict(estado.get("cursor") or {})
    # camada -> {uf: [anos lidos]} (só o ano mais novo de cada camada é lido; anos anteriores não ficam lidos)
    anos_lidos = {k: {u: list(a) for u, a in v.items()} for k, v in (cursor.get("anos_lidos") or {}).items()}
    linhas, notas = [], []
    for camada, c in regra["camadas"].items():
        ano, pub = ultimo_ano(regra["url"], camada, c["campo_ano"])
        if ano is None:
            notas.append(f"{camada}: vazio")
            continue
        lidos = anos_lidos.setdefault(camada, {})
        faltam = [uf for uf in ctx.ufs if ano not in lidos.get(uf, [])]
        if not faltam:
            notas.append(f"{camada}: {ano} já lido")
            continue
        valores = _valores_uf(faltam, bool(c.get("uf_por_nome")))
        if not valores:
            continue
        ufs = ",".join("'" + v.replace("'", "''") + "'" for v in valores)
        filtro = f"{c['campo_ano']} = {ano} AND {c['campo_uf']} IN ({ufs})"
        feicoes = _wfs(regra["url"], camada, filtro, int(regra["por_pagina"]), "fid")
        linhas += normalizar_prodes(_gdf(feicoes), camada, c["campo_uf"])
        for uf in faltam:
            lidos[uf] = sorted({*lidos.get(uf, []), ano})
        notas.append(f"{camada}: {ano} ({pub}), {len(feicoes)} polígonos em {len(faltam)} UF")
    cursor["anos_lidos"] = anos_lidos
    oc = montar(linhas).drop_duplicates("chave") if linhas else vazio()
    return Leitura("prodes", oc, cursor=cursor, nota="; ".join(notas))
