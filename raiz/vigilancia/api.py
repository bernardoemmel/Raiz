"""Rotas da vigilância (FastAPI). O back-end inclui com o mesmo token das outras rotas:

    from raiz.vigilancia import api as vigilancia_api
    app.include_router(vigilancia_api.roteador(), dependencies=seguro)

Enquanto o back-end não inclui, `python -m raiz.vigilancia servir` sobe só estas rotas (servidor.py), com o mesmo
token (RAIZ_API_TOKEN).

    GET  /vigilancia/imovel/{cod_imovel}                       situação e alertas do imóvel
                                                               (?desde=&fonte=&limite=&geo=)
    GET  /vigilancia/projeto/{id}                              eventos de perda com prazos, avisos e alertas do projeto
    GET  /vigilancia/projeto/{id}/perdas/{perda_id}/relatorio  rascunho do relatório de perda (?idioma=pt|en), Markdown
    GET  /vigilancia/projeto/{id}/perdas/{perda_id}/kml        KML da área afetada
    POST /vigilancia/projeto/{id}/perdas/{perda_id}/eventos    {tipo, data, quem, nota}: verra_avisada,
                                                               relatorio_enviado, descoberta_informada,
                                                               perda_descartada, perda_reaberta, nota
    GET  /vigilancia/avisos                                    avisos ao cliente (?estado=aguardando_aprovacao)
    POST /vigilancia/avisos/{aviso_id}/eventos                 {tipo: aviso_aprovado|aviso_enviado|aviso_descartado}
    POST /vigilancia/alertas/{alerta_id}/marcacao              {verdadeiro, fonte: campo|cliente|imagem_nova|
                                                               fonte_oficial, quem, evidencia, observado_em}
    GET  /vigilancia/acerto                                    acerto por fonte, estrato e versão da regra
    GET  /vigilancia/saude                                     última rodada e situação de cada fonte
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from raiz.vigilancia.servico import Vigilancia


class Marcacao(BaseModel):
    verdadeiro: bool
    fonte: str
    quem: str
    evidencia: str = ""
    observado_em: dt.date | None = None


class Evento(BaseModel):
    tipo: str
    quem: str
    data: dt.date | None = None
    nota: str = ""


def _json(dado, status: int = 200) -> Response:
    return Response(
        json.dumps(dado, ensure_ascii=False, separators=(",", ":"), default=str),
        status_code=status,
        media_type="application/json",
    )


def normalizar_cod(cod: str) -> str:
    """Código do CAR com ou sem os pontos do recibo, em qualquer caixa (PA-1507300-F293.CD17... vira
    PA-1507300-F293CD17...)."""
    c = re.sub(r"\s+", "", cod).upper()
    partes = c.split("-", 2)
    if len(partes) == 3:
        partes[2] = partes[2].replace(".", "")
        return "-".join(partes)
    return c


_UNICO: Vigilancia | None = None


def _padrao() -> Vigilancia:
    global _UNICO
    if _UNICO is None:
        _UNICO = Vigilancia()
    return _UNICO


def roteador(servico: Callable[[], Vigilancia] | None = None, prefixo: str = "/vigilancia") -> APIRouter:
    s = servico or _padrao
    r = APIRouter(prefix=prefixo, tags=["vigilância"])

    @r.get("/imovel/{cod_imovel}")
    def imovel(
        cod_imovel: str,
        desde: dt.date | None = None,
        fonte: str | None = None,
        limite: int = Query(200, ge=1, le=5000),
        geo: bool = False,
    ):
        d = s().imovel(normalizar_cod(cod_imovel), desde=desde, fonte=fonte, limite=limite, geo=geo)
        if d is None:
            raise HTTPException(404, "imóvel sem polígono no Release dados e sem alerta")
        return _json(d)

    @r.get("/projeto/{projeto_id}")
    def projeto(projeto_id: str, geo: bool = False, limite: int = Query(200, ge=1, le=5000)):
        d = s().projeto(projeto_id, geo=geo, limite=limite)
        if d is None:
            raise HTTPException(404, "projeto não cadastrado")
        return _json(d)

    @r.get("/projeto/{projeto_id}/perdas/{perda_id}/relatorio")
    def relatorio(projeto_id: str, perda_id: str, idioma: str = Query("pt", pattern="^(pt|en)$")):
        t = s().relatorio(projeto_id, perda_id, idioma)
        if t is None:
            raise HTTPException(404, "evento de perda não encontrado")
        return Response(t, media_type="text/markdown; charset=utf-8")

    @r.get("/projeto/{projeto_id}/perdas/{perda_id}/kml")
    def kml(projeto_id: str, perda_id: str):
        t = s().kml(projeto_id, perda_id)
        if t is None:
            raise HTTPException(404, "evento de perda não encontrado")
        return Response(
            t,
            media_type="application/vnd.google-earth.kml+xml",
            headers={"Content-Disposition": f'attachment; filename="{perda_id}.kml"'},
        )

    @r.get("/projeto/{projeto_id}/perdas/{perda_id}/aviso-verra")
    def aviso_verra(projeto_id: str, perda_id: str):
        d = s().aviso_verra(projeto_id, perda_id)
        if d is None:
            raise HTTPException(404, "evento de perda não encontrado")
        return _json(d)

    @r.get("/projeto/{projeto_id}/perdas/{perda_id}/aviso-verra.eml")
    def aviso_verra_eml(projeto_id: str, perda_id: str):
        from raiz.vigilancia.aviso_verra import eml

        d = s().aviso_verra(projeto_id, perda_id)
        if d is None:
            raise HTTPException(404, "evento de perda não encontrado")
        if not d["pode_exportar"]:
            raise HTTPException(409, "evento encerrado ou aviso já registrado: exportação bloqueada")
        return Response(
            eml(d),
            media_type="message/rfc822",
            headers={"Content-Disposition": 'attachment; filename="aviso-verra.eml"'},
        )

    @r.post("/projeto/{projeto_id}/perdas/{perda_id}/eventos")
    def evento_perda(projeto_id: str, perda_id: str, corpo: Evento):
        if not perda_id.startswith(f"{projeto_id}_LE"):
            raise HTTPException(404, "evento de perda não é deste projeto")
        try:
            return _json(s().evento("perda", perda_id, corpo.tipo, corpo.data, corpo.quem, corpo.nota), 201)
        except ValueError as ex:
            raise HTTPException(422, str(ex)) from ex

    @r.get("/avisos")
    def avisos(estado: str | None = None):
        return _json(s().avisos(estado))

    @r.post("/avisos/{aviso_id}/eventos")
    def evento_aviso(aviso_id: str, corpo: Evento):
        try:
            return _json(s().evento("aviso", aviso_id, corpo.tipo, corpo.data, corpo.quem, corpo.nota), 201)
        except ValueError as ex:
            raise HTTPException(422, str(ex)) from ex

    @r.post("/alertas/{alerta_id}/marcacao")
    def marcar(alerta_id: str, corpo: Marcacao):
        try:
            m = s().marcar(alerta_id, corpo.verdadeiro, corpo.fonte, corpo.quem, corpo.evidencia, corpo.observado_em)
        except KeyError as ex:
            raise HTTPException(404, "alerta não encontrado") from ex
        except ValueError as ex:
            raise HTTPException(422, str(ex)) from ex
        return _json(m, 201)

    @r.get("/acerto")
    def acerto():
        return _json(s().acerto())

    @r.get("/saude")
    def saude():
        return _json(s().saude())

    return r
