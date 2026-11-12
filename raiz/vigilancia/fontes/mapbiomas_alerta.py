"""MapBiomas Alerta (API GraphQL v2): alertas de desmatamento validados em imagem de alta resolução.

Precisa de MAPBIOMAS_ALERTA_EMAIL e MAPBIOMAS_ALERTA_SENHA (conta da Plataforma). Sem elas, a fonte é pulada e a
rodada segue com as outras.

Lê pela data de publicação uma janela de 35 dias (releitura que pega troca de status). Antes, pergunta sem login qual
foi a última publicação (lastAlertPublication): se não mudou e a última releitura tem menos de 7 dias, não pede nada.
Cada alerta traz o polígono (geometryWkt) e os imóveis do CAR que ele toca com a área em cada um; o cruzamento da
Raíz usa o polígono, e os códigos da fonte servem para imóveis de estados que ainda não estão no Release dados.

Dados do MapBiomas Alerta (CC BY 4.0): citar "MapBiomas Alerta, plataforma.alerta.mapbiomas.org, acesso em <data>".
"""

from __future__ import annotations

import datetime as dt
import logging
import os

import shapely

from raiz.vigilancia import rede
from raiz.vigilancia.fontes import Contexto, Leitura, data, montar, so_area, vazio
from raiz.vigilancia.fontes.inpe import uf_de

log = logging.getLogger(__name__)

LOGIN = "mutation($e:String!,$s:String!){ signIn(email:$e,password:$s){ token } }"
ULTIMA = "{ lastAlertPublication { publishedAt total } }"
CAMPOS_COMPLETOS = """alertCode areaHa detectedAt publishedAt statusAt statusName sources deforestationClasses
      deforestationSpeed geometryWkt crossedStates imageAcquiredBeforeAt imageAcquiredAfterAt ruralPropertiesCodes
      crossedRuralProperties { code alertAreaInCar }"""
CAMPOS_MINIMOS = "alertCode areaHa detectedAt publishedAt statusName geometryWkt ruralPropertiesCodes"
CONSULTA = """query($s:BaseDate,$e:BaseDate,$p:Int,$l:Int){
  alerts(startDate:$s, endDate:$e, dateType:PublishedAt, page:$p, limit:$l){
    collection{ %s }
    metadata{ totalPages totalCount }
  }
}"""


class SemCredencial(RuntimeError):
    pass


def entrar(url: str) -> str:
    email, senha = os.environ.get("MAPBIOMAS_ALERTA_EMAIL"), os.environ.get("MAPBIOMAS_ALERTA_SENHA")
    if not (email and senha):
        raise SemCredencial("defina MAPBIOMAS_ALERTA_EMAIL e MAPBIOMAS_ALERTA_SENHA (segredos do GitHub Actions)")
    return rede.graphql(url, LOGIN, {"e": email, "s": senha})["signIn"]["token"]


def _pagina(url: str, token: str, campos: str, inicio: dt.date, fim: dt.date, p: int, por: int) -> dict:
    v = {"s": inicio.isoformat(), "e": fim.isoformat(), "p": p, "l": por}
    return rede.graphql(url, CONSULTA % campos, v, token)["alerts"]


def baixar(url: str, token: str, inicio: dt.date, fim: dt.date, por: int = 100) -> list[dict]:
    campos = CAMPOS_COMPLETOS
    try:
        primeira = _pagina(url, token, campos, inicio, fim, 1, por)
    except RuntimeError as ex:
        log.warning("MapBiomas Alerta recusou os campos completos (%s); usando os mínimos", ex)
        campos = CAMPOS_MINIMOS
        primeira = _pagina(url, token, campos, inicio, fim, 1, por)
    itens = list(primeira["collection"])
    for p in range(2, int(primeira["metadata"]["totalPages"]) + 1):
        itens += _pagina(url, token, campos, inicio, fim, p, por)["collection"]
    return itens


def normalizar(itens: list[dict]) -> list[dict]:
    linhas = []
    for a in itens:
        wkt = a.get("geometryWkt")
        if not wkt:
            continue
        try:
            geo = so_area(shapely.from_wkt(wkt))
        except shapely.errors.GEOSException:
            continue
        if geo is None or geo.is_empty:
            continue
        codigo = str(a.get("alertCode"))
        car = {}
        for rp in a.get("crossedRuralProperties") or []:
            if rp.get("code"):
                car[str(rp["code"])] = rp.get("alertAreaInCar")
        for c in a.get("ruralPropertiesCodes") or []:
            car.setdefault(str(c), None)
        estados = a.get("crossedStates") or []
        classes = [str(c).lower() for c in a.get("deforestationClasses") or []]
        linhas.append(
            {
                "fonte": "mapbiomas_alerta",
                "chave": codigo,
                "classe": "_".join(sorted(classes)) or "desmatamento",
                "data_evento": data(a.get("detectedAt")),
                "publicado_em": data(a.get("publishedAt")),
                "area_ha": a.get("areaHa"),
                "uf": uf_de(estados[0]) if estados else None,
                "cod_municipio_ibge": None,
                "link": f"https://plataforma.alerta.mapbiomas.org/alerta/{codigo}",
                "atributos": {
                    "status": a.get("statusName"),
                    "status_em": str(a.get("statusAt") or "") or None,
                    "fontes": a.get("sources"),
                    "velocidade": a.get("deforestationSpeed"),
                    "imagem_antes": str(a.get("imageAcquiredBeforeAt") or "") or None,
                    "imagem_depois": str(a.get("imageAcquiredAfterAt") or "") or None,
                },
                "car_fonte": car or None,
                "geometry": geo,
            }
        )
    return linhas


def ler(ctx: Contexto, estado: dict) -> Leitura:
    regra = ctx.regras.fonte("mapbiomas_alerta")
    url = regra["url"]
    cursor = dict(estado.get("cursor") or {})
    ultima = rede.graphql(url, ULTIMA)["lastAlertPublication"]
    publicada = str(ultima.get("publishedAt") or "")
    releitura = data(cursor.get("releitura_em"))
    if publicada and publicada == cursor.get("ultima_publicacao") and releitura and (ctx.hoje - releitura).days < 7:
        return Leitura("mapbiomas_alerta", vazio(), cursor=cursor, nota=f"sem publicação nova desde {publicada[:10]}")
    token = entrar(url)
    inicio = ctx.hoje - dt.timedelta(days=int(regra.get("janela_dias", 35)))
    itens = baixar(url, token, inicio, ctx.hoje, int(regra.get("por_pagina", 100)))
    oc = montar(normalizar(itens))
    if len(oc):
        oc = oc.drop_duplicates("chave", keep="last")
    cursor.update(ultima_publicacao=publicada, releitura_em=ctx.hoje.isoformat())
    return Leitura(
        "mapbiomas_alerta",
        oc,
        cursor=cursor,
        nota=f"{len(itens)} alertas publicados desde {inicio} (última publicação {publicada[:10]})",
    )
