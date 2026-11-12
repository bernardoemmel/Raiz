"""Aprendizado da vigilância: cada alerta é uma previsão ("aqui houve perda, fogo ou embargo") guardada com a versão da
regra e a confiança do momento; a marcação depois diz se foi verdadeiro ou falso.

Fontes de marcação:
    campo          alguém foi ao lugar
    cliente        o cliente (dono ou desenvolvedor do projeto) confirmou ou desmentiu
    imagem_nova    imagem de satélite posterior (automático: PRODES ou MapBiomas Alerta confirma o DETER; cicatriz de
                   queimada do DETER confirma o foco de calor; ou alguém olhando a imagem)
    fonte_oficial  a própria fonte voltou atrás (termo de embargo cancelado, alerta do MapBiomas rejeitado)

Vale a marcação humana mais recente; a automática só vale quando não há humana. A confiança de cada estrato (fonte e
tipo) é Beta(a + verdadeiros, b + falsos), com a e b de regras.yaml; o acerto por versão da regra (precisão e nota de
Brier) mostra se a regra nova é melhor que a velha.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import unicodedata

import pandas as pd
import shapely

from raiz.vigilancia.privacidade import mascarar
from raiz.vigilancia.regras import Regras

FONTES_MARCACAO = ("campo", "cliente", "imagem_nova", "fonte_oficial")
COLUNAS_MARCACAO = [
    "marcacao_id",
    "alerta_id",
    "verdadeiro",
    "fonte",
    "evidencia",
    "quem",
    "observado_em",
    "registrado_em",
    "regra_versao",
]


def estrato(fonte: str, classe: str | None, tipo: str | None) -> str:
    if fonte == "deter":
        return f"deter_{tipo or 'desmatamento'}"
    if fonte == "firms":
        c = str(classe or "foco_nominal").removeprefix("foco_")
        return f"firms_{c}"
    return fonte


def confianca(regras: Regras, estr: str, contagem: dict[str, tuple[int, int]] | None = None) -> float:
    a, b = regras.prior(estr)
    v, f = (contagem or {}).get(estr, (0, 0))
    return round((a + v) / (a + b + v + f), 4)


def marcacao(
    alerta_id: str,
    verdadeiro: bool,
    fonte: str,
    quem: str,
    evidencia: str = "",
    observado_em: dt.date | None = None,
    regra_versao: str | None = None,
    agora: dt.datetime | None = None,
) -> dict:
    if fonte not in FONTES_MARCACAO:
        raise ValueError(f"fonte da marcação deve ser uma de {', '.join(FONTES_MARCACAO)}")
    agora = agora or dt.datetime.now(dt.UTC)
    quem = str(quem or "").strip().lower() or "nao_informado"
    mid = hashlib.sha1(f"{alerta_id}|{verdadeiro}|{fonte}|{quem}|{agora.isoformat()}".encode()).hexdigest()[:16]
    return {
        "marcacao_id": mid,
        "alerta_id": alerta_id,
        "verdadeiro": bool(verdadeiro),
        "fonte": fonte,
        "evidencia": mascarar(str(evidencia or ""))[:500],
        "quem": mascarar(quem)[:40],  # papel (fundador, cliente, campo, automatico), nunca nome
        "observado_em": (observado_em or agora.date()).isoformat(),
        "registrado_em": agora.isoformat(timespec="seconds"),
        "regra_versao": regra_versao,
    }


def vigentes(marcacoes: pd.DataFrame) -> pd.DataFrame:
    """Uma marcação por alerta: a humana mais recente; sem humana, a automática mais recente."""
    if marcacoes is None or not len(marcacoes):
        return pd.DataFrame(columns=COLUNAS_MARCACAO + ["humana"])
    m = marcacoes.copy()
    m["humana"] = m["quem"] != "automatico"
    m = m.sort_values(["alerta_id", "humana", "registrado_em"])
    return m.drop_duplicates("alerta_id", keep="last")


def contagem(alertas: pd.DataFrame, marcacoes: pd.DataFrame) -> dict[str, tuple[int, int]]:
    """Verdadeiros e falsos por estrato, a partir das marcações vigentes."""
    v = vigentes(marcacoes)
    if not len(v) or alertas is None or not len(alertas):
        return {}
    j = v.merge(alertas[["alerta_id", "estrato"]].drop_duplicates("alerta_id"), on="alerta_id", how="inner")
    out = {}
    for e, grupo in j.groupby("estrato"):
        ver = int(grupo["verdadeiro"].astype(bool).sum())
        out[str(e)] = (ver, int(len(grupo) - ver))
    return out


def acerto(alertas: pd.DataFrame, marcacoes: pd.DataFrame) -> list[dict]:
    """Acerto por fonte, estrato e versão da regra: marcados, verdadeiros, falsos, precisão e nota de Brier (média de
    (confiança - resultado)^2; quanto menor, melhor a confiança prevê o resultado)."""
    v = vigentes(marcacoes)
    if not len(v) or alertas is None or not len(alertas):
        return []
    cols = ["alerta_id", "fonte", "estrato", "regra_versao", "confianca"]
    j = v.drop(columns=["regra_versao", "fonte"], errors="ignore").merge(
        alertas[cols].drop_duplicates("alerta_id"), on="alerta_id"
    )
    fontes_marc = v.set_index("alerta_id")["fonte"]
    j["fonte_marcacao"] = j["alerta_id"].map(fontes_marc)
    out = []
    for (fonte, estr, versao), g in j.groupby(["fonte", "estrato", "regra_versao"], dropna=False):
        y = g["verdadeiro"].astype(bool).astype(float)
        out.append(
            {
                "fonte": fonte,
                "estrato": estr,
                "regra_versao": versao,
                "marcados": int(len(g)),
                "verdadeiros": int(y.sum()),
                "falsos": int(len(g) - y.sum()),
                "precisao": round(float(y.mean()), 4),
                "brier": round(float(((g["confianca"].astype(float) - y) ** 2).mean()), 4),
                "por_fonte_marcacao": {str(k): int(n) for k, n in g["fonte_marcacao"].value_counts().items()},
            }
        )
    return sorted(out, key=lambda d: (d["fonte"], d["estrato"], str(d["regra_versao"])))


# ------------------------------------------------------------------ marcação automática (imagem nova, fonte oficial)


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


def _geo(a: pd.Series):
    g = a.get("geometria")
    return shapely.from_wkb(g) if isinstance(g, bytes | bytearray) else g


def _prodes_ano(d: dt.date) -> int:
    """O ano do PRODES vai de agosto do ano anterior a julho: imagem de 2026-09 cai no PRODES 2027."""
    return d.year + (1 if d.month >= 8 else 0)


def marcar_automatico(
    alertas: pd.DataFrame,
    marcacoes: pd.DataFrame,
    regras: Regras,
    hoje: dt.date,
    prodes_lidos: dict[str, dict[str, int]] | None = None,
    ibama_cancelados: set[str] | None = None,
    mapbiomas_status: dict[str, str] | None = None,
) -> list[dict]:
    """Marcações automáticas novas. Só marca alerta que ainda não tem marcação vigente (humana nunca é trocada)."""
    if alertas is None or not len(alertas):
        return []
    r = regras["marcacao_automatica"]
    ja = set(vigentes(marcacoes)["alerta_id"]) if marcacoes is not None and len(marcacoes) else set()
    agora = dt.datetime.combine(hoje, dt.time(12), tzinfo=dt.UTC)
    novas: list[dict] = []

    def marca(a, verdadeiro, fonte, evidencia):
        novas.append(
            marcacao(a["alerta_id"], verdadeiro, fonte, "automatico", evidencia, hoje, regras.versao, agora=agora)
        )
        ja.add(a["alerta_id"])

    abertos = alertas[~alertas["alerta_id"].isin(ja)]
    if not len(abertos):
        return []

    # 1. fonte oficial: termo do Ibama cancelado; alerta do MapBiomas rejeitado
    for _, a in abertos[abertos["fonte"] == "ibama_embargo"].iterrows():
        if ibama_cancelados and str(a["chave"]) in ibama_cancelados:
            marca(a, False, "fonte_oficial", "termo de embargo cancelado pelo Ibama")
    falso_mb = {_sem_acento(s) for s in regras.fonte("mapbiomas_alerta").get("status_falso", [])}
    for _, a in abertos[abertos["fonte"] == "mapbiomas_alerta"].iterrows():
        st = (mapbiomas_status or {}).get(str(a["chave"]))
        if st and _sem_acento(st) in falso_mb and a["alerta_id"] not in ja:
            marca(a, False, "fonte_oficial", f"MapBiomas Alerta mudou o status para {st}")

    # 2. imagem nova: confirmação de desmatamento e de fogo no mesmo alvo
    confirmam = set(r.get("confirma_desmatamento_por", []))
    por_alvo = {k: g for k, g in alertas.groupby(["alvo_tipo", "alvo_id"])}
    for _, a in abertos.iterrows():
        if a["alerta_id"] in ja or a["fonte"] not in ("deter", "mapbiomas_alerta", "firms"):
            continue
        vizinhos = por_alvo.get((a["alvo_tipo"], a["alvo_id"]))
        if vizinhos is None or len(vizinhos) < 2:
            if a["fonte"] == "deter":
                _talvez_falso_deter(a, None, r, prodes_lidos, marca)
            continue
        g_a = _geo(a)
        if g_a is None or g_a.is_empty:
            continue
        de = a["data_evento"]
        if a["fonte"] in ("deter", "mapbiomas_alerta") and a["tipo"] == "desmatamento":
            outros = vizinhos[
                vizinhos["fonte"].isin(confirmam - {a["fonte"]})
                & (vizinhos["tipo"] == "desmatamento")
                & (vizinhos["alerta_id"] != a["alerta_id"])
            ]
            achou = None
            for _, o in outros.iterrows():
                if de and o["data_evento"] and o["data_evento"] < de - dt.timedelta(days=30):
                    continue  # mancha velha não confirma derrubada nova
                g_o = _geo(o)
                if g_o is None or g_o.is_empty or not g_a.intersects(g_o):
                    continue
                inter = g_a.intersection(g_o)
                ha = _area_ha(inter)
                base = max(_area_ha(g_a), 1e-9)
                if ha >= float(r["min_sobreposicao_ha"]) or ha / base >= float(r["min_fracao"]):
                    achou = o
                    break
            if achou is not None:
                marca(a, True, "imagem_nova", f"{achou['fonte']} {achou['chave']} confirma ({achou['data_evento']})")
            elif a["fonte"] == "deter":
                _talvez_falso_deter(a, vizinhos, r, prodes_lidos, marca)
        elif a["fonte"] == "firms":
            dias = int(r.get("fogo_confirmado_por_cicatriz_dias", 60))
            cic = vizinhos[(vizinhos["fonte"] == "deter") & (vizinhos["classe"] == "cicatriz_de_queimada")]
            for _, o in cic.iterrows():
                if de and o["data_evento"] and not (de <= o["data_evento"] <= de + dt.timedelta(days=dias)):
                    continue
                g_o = _geo(o)
                if g_o is not None and g_a.intersects(g_o):
                    marca(a, True, "imagem_nova", f"cicatriz de queimada do DETER em {o['data_evento']}")
                    break
    return novas


def _talvez_falso_deter(a, vizinhos, r, prodes_lidos, marca) -> None:
    """DETER de desmatamento grande sem nada do PRODES do mesmo ano no mesmo lugar, com esse ano já lido na UF."""
    if a["tipo"] != "desmatamento" or not prodes_lidos or not a["data_evento"]:
        return
    if float(a.get("area_ocorrencia_ha") or 0) < float(r["prodes_area_minima_ha"]):
        return
    ano = _prodes_ano(a["data_evento"])
    uf = a.get("uf")
    lido = any(ano in (c.get(uf) or []) for c in prodes_lidos.values()) if uf else False
    if not lido:
        return
    if vizinhos is not None and len(vizinhos):
        p = vizinhos[(vizinhos["fonte"] == "prodes")]
        g_a = _geo(a)
        for _, o in p.iterrows():
            g_o = _geo(o)
            if g_o is not None and g_a is not None and g_a.intersects(g_o):
                return
    marca(a, False, "imagem_nova", f"PRODES {ano} não mapeou desmatamento neste lugar")


def _area_ha(g) -> float:
    """Área em hectares de geometria em graus (EPSG:4674), pela projeção do motor."""
    import geopandas as gpd

    return float(gpd.GeoSeries([g], crs=4674).to_crs(5880).area.iloc[0] / 1e4)


# ------------------------------------------------------------------ exportação para o aprendizado do back-end


def exportar(alertas: pd.DataFrame, marcacoes: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """Previsões e gabaritos no formato de raiz/aprendizado (aprendizado.previsao e aprendizado.gabarito), para o
    back-end congelar com registrar_lote. Só alertas de imóvel (cod_imovel)."""
    previsoes, gabaritos = [], []
    if alertas is None or not len(alertas):
        return previsoes, gabaritos
    im = alertas[alertas["alvo_tipo"] == "imovel"]
    for _, a in im.iterrows():
        previsoes.append(
            {
                "cod_imovel": a["alvo_id"],
                "alvo": f"vigilancia_{a['tipo']}",
                "valor_num": float(a["confianca"]),
                "valor_texto": a["alerta_id"],
                "data_corte": str(a["visto_em"]),
                "horizonte_dias": 365,
                "modelo": f"vigilancia_{a['estrato']}",
                "modelo_versao": a["regra_versao"],
                "entradas_versao": f"{a['fonte']}:{a['chave']}",
            }
        )
    v = vigentes(marcacoes)
    if len(v):
        j = v.merge(im[["alerta_id", "alvo_id", "tipo"]], on="alerta_id")
        for _, m in j.iterrows():
            gabaritos.append(
                {
                    "cod_imovel": m["alvo_id"],
                    "alvo": f"vigilancia_{m['tipo']}",
                    "valor_num": 1.0 if m["verdadeiro"] else 0.0,
                    "observado_em": m["observado_em"],
                    "fonte": m["fonte"],
                    "referencia": json.dumps({"alerta_id": m["alerta_id"], "marcacao_id": m["marcacao_id"]}),
                }
            )
    return previsoes, gabaritos
