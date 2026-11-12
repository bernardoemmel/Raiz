"""Perda em área de projeto, pela regra da Verra (regras.yaml, seção verra).

Todo alerta que cai na área de carbono de um projeto (classes_projeto) depois do início do projeto é candidato a evento
de perda. Alertas do mesmo projeto a até 500 m e 60 dias um do outro formam o mesmo evento (um fogo que anda por
vários dias, o DETER e o MapBiomas Alerta da mesma derrubada). Cada evento recebe um número fixo (URTX_LE1, URTX_LE2,
no formato [ProjectID]_LE[n] do modelo da Verra) e:

- contador de prazo: aviso à Verra por e-mail em 30 dias da descoberta e relatório de perda em 2 anos da descoberta
  (Registration and Issuance Process v4.4, seção 5.3.1). A descoberta é a data mais cedo entre a publicação pela fonte e
  a primeira vez que a Raíz viu o alerta (conservador); o fundador pode informar outra, com justificativa;
- rascunho do relatório de perda no modelo Loss Event Report Template v5.0 e KML da área afetada (relatorio.py);
- aviso ao cliente na ordem fonte, fato, fazenda, prazo, o que fazer (aviso.py), sempre aguardando aprovação.

Situação do evento: suspeita (nenhum alerta confirmado), confirmada (algum alerta marcado verdadeiro), descartada
(todos falsos, ou o fundador descartou: por exemplo, colheita prevista no plano não é evento de perda) e relatada
(relatório entregue).
"""

from __future__ import annotations

import calendar
import datetime as dt
import json
import logging

import geopandas as gpd
import pandas as pd
import shapely

from raiz.vigilancia import aprendizado
from raiz.vigilancia.fontes import data as _data
from raiz.vigilancia.projetos import Projeto
from raiz.vigilancia.regras import Regras

log = logging.getLogger(__name__)

CRS_METROS = 5880
ORDEM_SITUACAO = ["vencido", "urgente", "atencao", "no_prazo", "cumprido", "suspenso", "nao_obrigatorio"]


def somar_anos(d: dt.date, anos: int) -> dt.date:
    """Mesmo dia, N anos depois (29 de fevereiro vira 28)."""
    a = d.year + anos
    return d.replace(year=a, day=min(d.day, calendar.monthrange(a, d.month)[1]))


def situacao_prazo(ate: dt.date, feito: dt.date | None, hoje: dt.date, atencao: int, urgente: int) -> str:
    if feito:
        return "cumprido"
    dias = (ate - hoje).days
    if dias < 0:
        return "vencido"
    if dias <= urgente:
        return "urgente"
    if dias <= atencao:
        return "atencao"
    return "no_prazo"


def _geo_m(wkbs) -> list:
    gs = gpd.GeoSeries([shapely.from_wkb(w) if w is not None else None for w in wkbs], crs=4674)
    return list(gs.to_crs(CRS_METROS))


def agrupar(cand: pd.DataFrame, distancia_m: float, janela_dias: int) -> list[list[int]]:
    """Grupos (posições em `cand`) de alertas próximos no espaço e no tempo (componentes ligados)."""
    n = len(cand)
    pai = list(range(n))

    def raiz(i):
        while pai[i] != i:
            pai[i] = pai[pai[i]]
            i = pai[i]
        return i

    geos = _geo_m(cand["geometria"].tolist())
    datas = [_data(d) for d in cand["data_evento"]]
    validos = [i for i, g in enumerate(geos) if g is not None and not g.is_empty]
    if validos:
        arvore = shapely.STRtree([geos[i] for i in validos])
        for i in validos:
            for kk in arvore.query(geos[i], predicate="dwithin", distance=distancia_m):
                j = validos[int(kk)]
                if j <= i:
                    continue
                di, dj = datas[i], datas[j]
                if di and dj and abs((di - dj).days) > janela_dias:
                    continue
                pai[raiz(i)] = raiz(j)
    grupos: dict[int, list[int]] = {}
    for i in range(n):
        grupos.setdefault(raiz(i), []).append(i)
    return list(grupos.values())


def _ultimo_evento(eventos: pd.DataFrame, alvo_id: str, tipos: tuple[str, ...]) -> dict | None:
    if eventos is None or not len(eventos):
        return None
    e = eventos[(eventos["alvo"] == "perda") & (eventos["alvo_id"] == alvo_id) & eventos["tipo"].isin(tipos)]
    if not len(e):
        return None
    return e.sort_values("registrado_em").iloc[-1].to_dict()


def numerar(
    projeto_id: str, grupos_raiz: list[tuple[list[str], str, dt.date]], registro: pd.DataFrame, hoje: dt.date
) -> tuple[list[int], pd.DataFrame]:
    """Número fixo de cada evento. grupos_raiz: (ids dos alertas, alerta raiz, descoberta). Um número dado nunca é
    reaproveitado; se dois eventos se juntam, vale o menor número."""
    reg = registro[registro["projeto_id"] == projeto_id] if len(registro) else registro
    por_raiz = dict(zip(reg["alerta_raiz"], reg["numero"], strict=False)) if len(reg) else {}
    proximo = int(reg["numero"].max()) + 1 if len(reg) else 1
    numeros: list[int | None] = []
    for ids, _, _ in grupos_raiz:
        achados = [int(por_raiz[i]) for i in ids if i in por_raiz]
        numeros.append(min(achados) if achados else None)
    novos = []
    for k in sorted(range(len(grupos_raiz)), key=lambda k: (grupos_raiz[k][2], grupos_raiz[k][1])):
        if numeros[k] is None:
            numeros[k] = proximo
            novos.append(
                {
                    "projeto_id": projeto_id,
                    "numero": proximo,
                    "alerta_raiz": grupos_raiz[k][1],
                    "criado_em": hoje.isoformat(),
                }
            )
            proximo += 1
    if novos:
        registro = (
            pd.concat([registro, pd.DataFrame(novos)], ignore_index=True) if len(registro) else pd.DataFrame(novos)
        )
    return [int(n) for n in numeros], registro


def calcular(
    projeto: Projeto,
    alertas: pd.DataFrame,
    marcacoes: pd.DataFrame,
    eventos: pd.DataFrame,
    registro: pd.DataFrame,
    regras: Regras,
    hoje: dt.date,
    areas: gpd.GeoDataFrame | None = None,
    alertas_imoveis: pd.DataFrame | None = None,
) -> tuple[list[dict], pd.DataFrame]:
    """Eventos de perda do projeto (mais recente primeiro) e o registro de números atualizado."""
    v = regras.verra
    if alertas is None or not len(alertas):
        return [], registro
    cand = alertas[(alertas["alvo_tipo"] == "projeto") & (alertas["alvo_id"] == projeto.id)]
    cand = cand[
        (cand["papel"] == "projeto") & cand["tipo"].isin(v.get("tipos_perda", ["desmatamento", "degradacao", "fogo"]))
    ]
    if projeto.inicio:
        cand = cand[cand["data_evento"].map(lambda d: _data(d) is None or _data(d) >= projeto.inicio)]
    if not len(cand):
        return [], registro
    cand = cand.reset_index(drop=True)
    vig = aprendizado.vigentes(marcacoes).set_index("alerta_id") if marcacoes is not None else pd.DataFrame()
    grupos = agrupar(cand, float(v["agrupar_distancia_m"]), int(v["agrupar_janela_dias"]))

    def descoberta(r) -> dt.date:
        datas = [d for d in (_data(r["visto_em"]), _data(r["publicado_em"])) if d]
        return min(datas) if datas else hoje

    info = []
    for g in grupos:
        sub = cand.iloc[g]
        desc = [descoberta(r) for _, r in sub.iterrows()]
        ordem = sorted(zip(desc, sub["alerta_id"], strict=True))
        info.append((list(sub["alerta_id"]), ordem[0][1], ordem[0][0]))
    numeros, registro = numerar(projeto.id, info, registro, hoje)

    carbono = areas[areas["papel"] == "projeto"] if areas is not None and len(areas) else None
    perdas = []
    for g, numero, (_, _, desc0) in zip(grupos, numeros, info, strict=True):
        sub = cand.iloc[g].copy()
        sub["marca"] = sub["alerta_id"].map(lambda i: bool(vig.loc[i, "verdadeiro"]) if i in vig.index else None)
        pid = f"{projeto.id}_LE{numero}"
        validos = sub[sub["marca"] != False]  # noqa: E712 (None conta como não marcado)
        geos = _geo_m(validos["geometria"].tolist()) if len(validos) else []
        uniao = shapely.union_all([x for x in geos if x is not None]) if geos else None
        area = float(shapely.area(uniao)) / 1e4 if uniao is not None else 0.0
        classes = _classes(uniao, carbono, validos)
        partes = _partes(uniao)
        # descoberta: a mais cedo do grupo; o fundador pode informar outra
        inf = _ultimo_evento(eventos, pid, ("descoberta_informada",))
        descoberta_em = _data(inf["data"]) if inf and _data(inf["data"]) else desc0
        verra_feita = _ultimo_evento(eventos, pid, ("verra_avisada",))
        rel_feito = _ultimo_evento(eventos, pid, ("relatorio_enviado",))
        desc_ev = _ultimo_evento(eventos, pid, ("perda_descartada", "perda_reaberta"))
        marcas = list(sub["marca"])
        if desc_ev and desc_ev["tipo"] == "perda_descartada":
            estado = "descartada"
        elif marcas and all(m is False for m in marcas):
            estado = "descartada"
        elif rel_feito:
            estado = "relatada"
        elif any(m is True for m in marcas):
            estado = "confirmada"
        else:
            estado = "suspeita"
        conf = (
            1.0
            if any(m is True for m in marcas)
            else 0.0
            if estado == "descartada"
            else 1.0 - _prod(1.0 - float(c) for c in validos["confianca"])
        )
        aviso_ate = descoberta_em + dt.timedelta(days=int(v["aviso_verra_dias"]))
        rel_ate = somar_anos(descoberta_em, int(v["relatorio_anos"]))
        obrigatorio = projeto.get("vcus_emitidos")
        if estado == "descartada":
            sit_aviso = sit_rel = "suspenso"
        else:
            sit_aviso = situacao_prazo(
                aviso_ate,
                _data(verra_feita["data"]) if verra_feita else None,
                hoje,
                int(v["lembrete_aviso_verra_dias"]),
                int(v["lembrete_aviso_verra_dias"]),
            )
            sit_rel = situacao_prazo(
                rel_ate,
                _data(rel_feito["data"]) if rel_feito else None,
                hoje,
                int(v["prazo_atencao_dias"]),
                int(v["prazo_urgente_dias"]),
            )
            if obrigatorio is False and sit_rel != "cumprido":
                sit_rel = "nao_obrigatorio"
        mag = _magnitude(projeto, classes, area, float(v["limiar_evento_pct"]))
        centro = gpd.GeoSeries([uniao.centroid], crs=CRS_METROS).to_crs(4674).iloc[0] if uniao is not None else None
        imoveis = _imoveis_atingidos(sub, alertas_imoveis)
        perdas.append(
            {
                "perda_id": pid,
                "projeto_id": projeto.id,
                "numero": numero,
                "estado": estado,
                "confianca": round(conf, 4),
                "descoberta_em": descoberta_em,
                "descoberta_informada": bool(inf),
                "data_evento_inicio": min((d for d in map(_data, sub["data_evento"]) if d), default=None),
                "data_evento_fim": max((d for d in map(_data, sub["data_evento"]) if d), default=None),
                "area_ha": round(area, 4),
                "classes_ha": classes,
                "partes": partes,
                "centroide": [round(centro.x, 6), round(centro.y, 6)] if centro is not None else None,
                "fontes": sorted(set(sub["fonte"])),
                "tipos": sorted(set(sub["tipo"])),
                "alertas": [
                    {
                        "alerta_id": r["alerta_id"],
                        "fonte": r["fonte"],
                        "classe": r["classe"],
                        "data_evento": _data(r["data_evento"]),
                        "area_projeto_ha": r.get("area_projeto_ha"),
                        "confianca": r["confianca"],
                        "marcacao": r["marca"],
                        "link": r.get("link"),
                    }
                    for _, r in sub.sort_values("data_evento").iterrows()
                ],
                "imoveis": imoveis,
                "magnitude": mag,
                "prazo": {
                    "aviso_verra_ate": aviso_ate,
                    "aviso_verra_dias_restantes": (aviso_ate - hoje).days,
                    "aviso_verra_feito_em": _data(verra_feita["data"]) if verra_feita else None,
                    "aviso_verra_situacao": sit_aviso,
                    "relatorio_ate": rel_ate,
                    "relatorio_dias_restantes": (rel_ate - hoje).days,
                    "relatorio_enviado_em": _data(rel_feito["data"]) if rel_feito else None,
                    "relatorio_situacao": sit_rel,
                    "relatorio_obrigatorio": obrigatorio,
                    "email_verra": v.get("email"),
                    "base": v.get("documento"),
                },
                "geometria": shapely.to_wkb(gpd.GeoSeries([uniao], crs=CRS_METROS).to_crs(4674).iloc[0])
                if uniao is not None
                else None,
                "regra_versao": regras.versao,
            }
        )
    perdas.sort(key=lambda p: (p["descoberta_em"], p["numero"]), reverse=True)
    return perdas, registro


def _prod(it) -> float:
    p = 1.0
    for x in it:
        p *= x
    return p


def _partes(uniao) -> list[dict]:
    """Áreas separadas do evento (a Verra pede o centro de cada uma)."""
    if uniao is None or uniao.is_empty:
        return []
    geoms = list(getattr(uniao, "geoms", [uniao]))
    gs = gpd.GeoSeries(geoms, crs=CRS_METROS)
    centros = gs.centroid.to_crs(4674)
    return [
        {"ha": round(float(g.area) / 1e4, 4), "centro": [round(c.x, 6), round(c.y, 6)]}
        for g, c in zip(geoms, centros, strict=True)
    ]


def _classes(uniao, carbono: gpd.GeoDataFrame | None, sub: pd.DataFrame) -> dict[str, float]:
    if uniao is None or uniao.is_empty:
        return {}
    if carbono is not None and len(carbono):
        out = {}
        for _, c in carbono.iterrows():
            ha = float(shapely.area(shapely.intersection(uniao, c.geometry))) / 1e4
            if ha > 0:
                out[str(c["classe"])] = round(ha, 4)
        if out:
            return out
    # sem as áreas do projeto: maior área por classe entre os alertas (aproximação)
    out: dict[str, float] = {}
    for x in sub["classes_ha"]:
        for k, ha in (json.loads(x) if isinstance(x, str) else (x or {})).items():
            out[k] = max(out.get(k, 0.0), float(ha))
    return out


def _magnitude(projeto: Projeto, classes: dict[str, float], area: float, limiar: float) -> dict:
    estoques = {c: projeto.estoque(c) for c in classes} if classes else {"projeto": projeto.estoque("projeto")}
    falta = []
    if not classes or any(e is None for e in estoques.values()):
        falta.append("estoque_tco2e_ha (por hectare, por classe)")
        perda = None
    else:
        perda = round(sum(classes[c] * estoques[c] for c in classes), 2)
    verificado = projeto.get("verificado_tco2e")
    if verificado in (None, "", 0):
        falta.append("verificado_tco2e (reduções e remoções já verificadas)")
    pct = round(100 * perda / float(verificado), 3) if perda is not None and verificado else None
    return {
        "perda_tco2e": perda,
        "metodo": "conservador: todo o estoque da área afetada perdido (área x estoque por hectare)",
        "verificado_tco2e": float(verificado) if verificado else None,
        "pct": pct,
        "limiar_pct": limiar,
        "evento_de_perda": (pct > limiar) if pct is not None else None,
        "falta": falta,
    }


def _imoveis_atingidos(sub: pd.DataFrame, alertas_imoveis: pd.DataFrame | None) -> list[dict]:
    """Imóveis do CAR tocados pelas mesmas ocorrências (mesma fonte e chave) do evento."""
    if alertas_imoveis is None or not len(alertas_imoveis):
        return []
    chaves = set(zip(sub["fonte"], sub["chave"], strict=True))
    im = alertas_imoveis[
        [(f, c) in chaves for f, c in zip(alertas_imoveis["fonte"], alertas_imoveis["chave"], strict=True)]
    ]
    if not len(im):
        return []
    g = im.groupby("alvo_id").agg(
        area_ha=("area_sobreposta_ha", "sum"), municipio=("municipio", "first"), uf=("uf", "first")
    )
    return [
        {"cod_imovel": k, "area_ha": round(float(r.area_ha), 4), "municipio": r.municipio, "uf": r.uf}
        for k, r in g.sort_values("area_ha", ascending=False).iterrows()
    ]


def situacao_projeto(perdas: list[dict]) -> str:
    abertas = [p for p in perdas if p["estado"] not in ("descartada", "relatada")]
    if not abertas:
        return "sem_perda_aberta"
    sits = [p["prazo"]["relatorio_situacao"] for p in abertas] + [p["prazo"]["aviso_verra_situacao"] for p in abertas]
    if "vencido" in sits:
        return "prazo_vencido"
    if any(p["estado"] == "confirmada" for p in abertas):
        return "perda_confirmada"
    return "perda_suspeita"
