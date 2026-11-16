"""Cruzamento das ocorrências com os imóveis do CAR (Release dados) e com as áreas dos projetos.

Um alerta = uma ocorrência da fonte num alvo (imóvel ou projeto). Os focos de calor do FIRMS de uma mesma passagem do
satélite (satélite, data e hora) no mesmo alvo viram um alerta só. O identificador do alerta é estável:
sha1(fonte | chave | alvo_tipo | alvo_id), então ler a mesma ocorrência de novo nunca duplica o alerta.

Nada é descartado por tamanho: sobreposição pequena fica guardada; quando parece só diferença de traçado (borda),
vai com gravidade baixa.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from raiz.vigilancia import aprendizado
from raiz.vigilancia.fontes import so_area, so_area_vetor
from raiz.vigilancia.regras import Regras

log = logging.getLogger(__name__)

CRS_METROS = 5880
COLUNAS_ALERTA = [
    "alerta_id",
    "fonte",
    "chave",
    "classe",
    "tipo",
    "alvo_tipo",
    "alvo_id",
    "uf",
    "cod_municipio_ibge",
    "municipio",
    "data_evento",
    "publicado_em",
    "visto_em",
    "area_ocorrencia_ha",
    "area_sobreposta_ha",
    "alvo_ha",
    "fracao_alvo",
    "fracao_ocorrencia",
    "borda",
    "papel",
    "area_projeto_ha",
    "classes_ha",
    "gravidade",
    "estrato",
    "confianca",
    "regra_versao",
    "novo",
    "link",
    "atributos",
    "lon",
    "lat",
    "geometria",
]


def alerta_id(fonte: str, chave: str, alvo_tipo: str, alvo_id: str) -> str:
    return hashlib.sha1(f"{fonte}|{chave}|{alvo_tipo}|{alvo_id}".encode()).hexdigest()[:16]


def _valido(geo: np.ndarray) -> np.ndarray:
    return so_area_vetor(np.asarray(geo, dtype=object))


def _pares(oc_geo: np.ndarray, alvo_geo: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Índices (ocorrência, alvo) que se tocam e a geometria da interseção (EPSG:5880)."""
    if not len(oc_geo) or not len(alvo_geo):
        return np.array([], int), np.array([], int), np.array([], object)
    arvore = shapely.STRtree(alvo_geo)
    i, j = arvore.query(oc_geo, predicate="intersects")
    if not len(i):
        return i, j, np.array([], object)
    try:
        inter = shapely.intersection(oc_geo[i], alvo_geo[j])
    except shapely.errors.GEOSException:
        inter = np.array([_seguro(a, b) for a, b in zip(oc_geo[i], alvo_geo[j], strict=True)], dtype=object)
    return i, j, inter


def _seguro(a, b):
    try:
        return shapely.intersection(a, b)
    except shapely.errors.GEOSException:
        try:
            return shapely.intersection(so_area(a).buffer(0), so_area(b).buffer(0))
        except (shapely.errors.GEOSException, AttributeError):
            return None


def _caixas_tocam(b_oc: np.ndarray, caixa: list[float]) -> np.ndarray:
    x0, y0, x1, y1 = caixa
    return (b_oc[:, 0] <= x1) & (b_oc[:, 2] >= x0) & (b_oc[:, 1] <= y1) & (b_oc[:, 3] >= y0)


def cruzar_imoveis(oc: gpd.GeoDataFrame, poligonos) -> pd.DataFrame:
    """Pares ocorrência x imóvel. `poligonos` é um Poligonos (ou qualquer objeto com ufs(), indice(uf) e
    imoveis(uf, cod)). Devolve: i_oc, alvo_tipo, alvo_id, uf, cod_municipio_ibge, municipio, alvo_ha, geometry."""
    saida = []
    if not len(oc):
        return pd.DataFrame()
    caixas_oc = oc.geometry.bounds.to_numpy()
    oc_m = _valido(oc.to_crs(CRS_METROS).geometry.values)
    for uf in poligonos.ufs():
        for cod, caixa in poligonos.indice(uf).items():
            sel = np.flatnonzero(_caixas_tocam(caixas_oc, caixa))
            if not len(sel):
                continue
            imv = poligonos.imoveis(uf, cod)
            if not len(imv):
                continue
            i, j, inter = _pares(oc_m[sel], _valido(imv.geometry.values))
            if not len(i):
                continue
            sub = imv.iloc[j]
            saida.append(
                pd.DataFrame(
                    {
                        "i_oc": sel[i],
                        "alvo_tipo": "imovel",
                        "alvo_id": sub["cod_imovel"].to_numpy(),
                        "uf": sub["uf"].to_numpy() if "uf" in sub else uf,
                        "cod_municipio_ibge": cod,
                        "municipio": sub["municipio"].to_numpy() if "municipio" in sub else None,
                        "alvo_ha": sub["alvo_ha"].to_numpy(),
                        "papel": None,
                        "area_projeto_ha": None,
                        "classes_ha": None,
                        "geometry": inter,
                    }
                )
            )
    pares = pd.concat(saida, ignore_index=True) if saida else pd.DataFrame()
    # MapBiomas Alerta já diz quais imóveis do CAR o alerta toca: vale para estados que ainda não estão no Release
    ufs = set(poligonos.ufs())
    extras = []
    for k, r in oc.reset_index(drop=True).iterrows():
        for cod_imovel, ha in (r.get("car_fonte") or {}).items():
            permitidos = getattr(poligonos, "presentes", None)
            if permitidos is not None and cod_imovel not in permitidos:
                continue  # recorte de lotes nunca amplia o universo para CAR citado fora do Brasil processado
            uf = str(cod_imovel)[:2].upper()
            if uf in ufs:
                continue
            cod_mun = str(cod_imovel)[3:10]
            extras.append(
                {
                    "i_oc": k,
                    "alvo_tipo": "imovel",
                    "alvo_id": str(cod_imovel),
                    "uf": uf,
                    "cod_municipio_ibge": int(cod_mun) if cod_mun.isdigit() else None,
                    "municipio": None,
                    "alvo_ha": None,
                    "papel": None,
                    "area_projeto_ha": None,
                    "classes_ha": None,
                    "geometry": oc_m[k],
                    "_area_fonte": ha,
                }
            )
    if extras:
        pares = pd.concat([pares, pd.DataFrame(extras)], ignore_index=True)
    return pares


def cruzar_projetos(oc: gpd.GeoDataFrame, areas: gpd.GeoDataFrame) -> pd.DataFrame:
    """Pares ocorrência x projeto, juntando as classes: área de carbono (papel projeto) separada do entorno.
    Ocorrência só na parte 'fora' (área não disponível) não é alerta do projeto."""
    if not len(oc) or areas is None or not len(areas):
        return pd.DataFrame()
    oc_m = _valido(oc.to_crs(CRS_METROS).geometry.values)
    ar = areas.reset_index(drop=True)
    i, j, inter = _pares(oc_m, _valido(ar.geometry.values))
    if not len(i):
        return pd.DataFrame()
    df = pd.DataFrame(
        {
            "i_oc": i,
            "projeto_id": ar["projeto_id"].to_numpy()[j],
            "classe": ar["classe"].to_numpy()[j],
            "papel": ar["papel"].to_numpy()[j],
            "geometry": inter,
        }
    )
    total_carbono = ar[ar["papel"] == "projeto"].groupby("projeto_id")["ha"].sum().to_dict()
    linhas = []
    for (k, pid), g in df.groupby(["i_oc", "projeto_id"]):
        papeis = set(g["papel"])
        papel = "projeto" if "projeto" in papeis else "entorno" if "entorno" in papeis else None
        if papel is None:
            continue
        classes = {
            str(c): round(float(shapely.area(geo)) / 1e4, 4) for c, geo in zip(g["classe"], g["geometry"], strict=True)
        }
        carbono = shapely.union_all(g.loc[g["papel"] == "projeto", "geometry"].to_numpy())
        entorno = shapely.union_all(g.loc[g["papel"] == "entorno", "geometry"].to_numpy())
        linhas.append(
            {
                "i_oc": k,
                "alvo_tipo": "projeto",
                "alvo_id": str(pid),
                "uf": None,
                "cod_municipio_ibge": None,
                "municipio": None,
                "alvo_ha": float(total_carbono.get(pid, 0.0)) or None,
                "papel": papel,
                "area_projeto_ha": round(float(shapely.area(carbono)) / 1e4, 4) if papel == "projeto" else 0.0,
                "classes_ha": classes,
                "geometry": carbono if papel == "projeto" else entorno,
            }
        )
    return pd.DataFrame(linhas)


def _grupo_firms(chave: str) -> str:
    """sat|data|hora|lat|lon -> sat|data|hora (uma passagem do satélite)."""
    return "|".join(str(chave).split("|")[:3])


def _juntar_firms(pares: pd.DataFrame, oc: gpd.GeoDataFrame) -> pd.DataFrame:
    """Uma linha por passagem do satélite e alvo; atributos com número de focos, FRP máxima e pontos."""
    f = pares[pares["fonte"] == "firms"]
    if not len(f):
        return pares
    resto = pares[pares["fonte"] != "firms"]
    ordem = {"alta": 3, "nominal": 2, "baixa": 1}
    linhas = []
    for (_, _, grupo), g in f.groupby(["alvo_tipo", "alvo_id", "_grupo"]):
        primeiro = g.iloc[0].to_dict()
        ocs = oc.iloc[g["i_oc"].to_numpy()]
        attrs = [a or {} for a in ocs["atributos"]]
        classes = list(ocs["classe"])
        melhor = max(classes, key=lambda c: ordem.get(str(c).removeprefix("foco_"), 0))
        frps = [a.get("frp_mw") for a in attrs if a.get("frp_mw") is not None]
        primeiro.update(
            chave=grupo,
            classe=melhor,
            geometry=shapely.union_all(g["geometry"].to_numpy()),
            area_ocorrencia_ha=float(ocs["area_ha"].fillna(0).sum()),
            atributos={
                "satelite": attrs[0].get("satelite"),
                "hora_utc": attrs[0].get("hora_utc"),
                "focos": int(len(g)),
                "frp_max_mw": max(frps) if frps else None,
                "dia_noite": attrs[0].get("dia_noite"),
                "pontos": [[a.get("lon"), a.get("lat")] for a in attrs[:20]],
            },
        )
        if primeiro.get("classes_ha") is not None:
            soma: dict[str, float] = {}
            for c in g["classes_ha"]:
                for k, v in (c or {}).items():
                    soma[k] = soma.get(k, 0.0) + v
            primeiro["classes_ha"] = soma
            projeto = g[g["papel"] == "projeto"]
            if len(projeto):
                primeiro["papel"] = "projeto"
                primeiro["geometry"] = shapely.union_all(projeto["geometry"].to_numpy())
        linhas.append(primeiro)
    return pd.concat([resto, pd.DataFrame(linhas)], ignore_index=True)


def gravidade(regras: Regras, a: dict) -> str:
    g = regras["gravidade"]
    if a["borda"]:
        return "baixa"
    if a["alvo_tipo"] == "projeto" and a.get("papel") == "projeto":
        return "alta"
    if a["fonte"] == "ibama_embargo":
        return "alta"
    area = a.get("area_sobreposta_ha") or 0.0
    fr = a.get("fracao_alvo") or 0.0
    if area >= g["area_alta_ha"] or fr >= g["fracao_alta"]:
        return "alta"
    if area >= g["area_media_ha"] or fr >= g["fracao_media"] or a["tipo"] == "fogo":
        return "media"
    return "baixa"


def _borda(regras: Regras, a: dict, ponto: bool) -> bool:
    if ponto:
        return False
    g = regras["gravidade"]
    area = a.get("area_sobreposta_ha") or 0.0
    fo = a.get("fracao_ocorrencia")
    fa = a.get("fracao_alvo")
    return (
        area < g["borda_max_ha"]
        and (fo is None or fo < g["borda_max_fracao_alerta"])
        and (fa is None or fa < g["borda_max_fracao_alvo"])
    )


def montar_alertas(
    oc: gpd.GeoDataFrame,
    pares: pd.DataFrame,
    regras: Regras,
    hoje: dt.date,
    contagem: dict[str, tuple[int, int]] | None = None,
) -> pd.DataFrame:
    """Alertas prontos para guardar (colunas COLUNAS_ALERTA; geometria em WKB, EPSG:4674)."""
    if pares is None or not len(pares):
        return pd.DataFrame(columns=COLUNAS_ALERTA)
    oc = oc.reset_index(drop=True)
    p = pares.copy()
    p["fonte"] = oc["fonte"].to_numpy()[p["i_oc"].to_numpy()]
    p["chave"] = oc["chave"].to_numpy()[p["i_oc"].to_numpy()]
    p["_grupo"] = [_grupo_firms(c) if f == "firms" else c for f, c in zip(p["fonte"], p["chave"], strict=True)]
    p = _juntar_firms(p, oc)
    janela = int(regras.get("novo_janela_dias", 30))
    geo_m = gpd.GeoSeries(p["geometry"].to_numpy(), crs=CRS_METROS)
    simples = geo_m.simplify(1.0)
    graus = simples.to_crs(4674)
    pontos = graus.representative_point()
    linhas = []
    for k, (_, r) in enumerate(p.iterrows()):
        o = oc.iloc[int(r["i_oc"])]
        fonte = str(o["fonte"])
        classe = str(r.get("classe") if fonte == "firms" else o["classe"])
        tipo = regras.tipo(fonte, classe)
        g = geo_m.iloc[k]
        ponto = g is not None and g.geom_type in ("Point", "MultiPoint")
        area = float(shapely.area(g)) / 1e4 if g is not None else 0.0
        if r.get("_area_fonte") is not None and r.get("_area_fonte") == r.get("_area_fonte"):
            area = float(r["_area_fonte"])  # alvo fora do Release: vale a área que a fonte mediu no CAR
        area_oc = r.get("area_ocorrencia_ha") if fonte == "firms" else o["area_ha"]
        area_oc = float(area_oc) if area_oc is not None and area_oc == area_oc else None
        alvo_ha = r.get("alvo_ha")
        alvo_ha = float(alvo_ha) if alvo_ha is not None and alvo_ha == alvo_ha else None
        pub = o["publicado_em"] if o["publicado_em"] is not None else None
        a = {
            "alerta_id": alerta_id(fonte, str(r["chave"]), str(r["alvo_tipo"]), str(r["alvo_id"])),
            "fonte": fonte,
            "chave": str(r["chave"]),
            "classe": classe,
            "tipo": tipo,
            "alvo_tipo": r["alvo_tipo"],
            "alvo_id": str(r["alvo_id"]),
            "uf": r.get("uf") if r.get("uf") is not None else o.get("uf"),
            "cod_municipio_ibge": r.get("cod_municipio_ibge")
            if r.get("cod_municipio_ibge") is not None
            else o.get("cod_municipio_ibge"),
            "municipio": r.get("municipio"),
            "data_evento": o["data_evento"],
            "publicado_em": pub,
            "visto_em": hoje,
            "area_ocorrencia_ha": round(area_oc, 4) if area_oc is not None else None,
            "area_sobreposta_ha": round(area, 4),
            "alvo_ha": round(alvo_ha, 4) if alvo_ha else None,
            "fracao_alvo": round(area / alvo_ha, 5) if alvo_ha else None,
            "fracao_ocorrencia": round(area / area_oc, 5) if area_oc else None,
            "papel": r.get("papel"),
            "area_projeto_ha": r.get("area_projeto_ha"),
            "classes_ha": json.dumps(r.get("classes_ha"), ensure_ascii=False) if r.get("classes_ha") else None,
            "link": o.get("link"),
            "atributos": json.dumps(
                r.get("atributos") if fonte == "firms" else (o.get("atributos") or {}), ensure_ascii=False, default=str
            ),
            "lon": round(float(pontos.iloc[k].x), 6) if pontos.iloc[k] is not None else None,
            "lat": round(float(pontos.iloc[k].y), 6) if pontos.iloc[k] is not None else None,
            "geometria": shapely.to_wkb(graus.iloc[k]) if graus.iloc[k] is not None else None,
            "regra_versao": regras.versao,
        }
        a["borda"] = _borda(regras, a, ponto)
        a["estrato"] = aprendizado.estrato(fonte, classe, tipo)
        a["confianca"] = aprendizado.confianca(regras, a["estrato"], contagem)
        a["gravidade"] = gravidade(regras, a)
        ref = pub or o["data_evento"] or hoje
        a["novo"] = bool(ref >= hoje - dt.timedelta(days=janela))
        linhas.append(a)
    df = pd.DataFrame(linhas, columns=COLUNAS_ALERTA)
    return df.drop_duplicates("alerta_id")
