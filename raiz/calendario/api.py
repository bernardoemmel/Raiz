"""GET /eventos e /eventos.ics: apenas calendário público, sem estado privado de projetos."""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from raiz.calendario.banco import consultar
from raiz.calendario.feed import ics
from raiz.calendario.modelos import Evento, filtrar


def filtros(
    tipo: str | None = None,
    estado: str | None = None,
    inicio: dt.date | None = None,
    fim: dt.date | None = None,
    cod_imovel: str | None = None,
) -> dict:
    d = dict(tipo=tipo, estado=estado.upper() if estado else None, inicio=inicio, fim=fim, cod_imovel=cod_imovel)
    try:
        filtrar([], **d)
    except ValueError as ex:
        raise HTTPException(422, str(ex)) from ex
    return d


def roteador(engine_de) -> APIRouter:
    r = APIRouter(tags=["Calendário"])

    @r.get("/eventos")
    def eventos(
        request: Request,
        parametros: Annotated[dict, Depends(filtros)],
        limite: int = Query(100, ge=1, le=1000),
        deslocamento: int = Query(0, ge=0),
    ):
        with engine_de(request).connect() as con:
            return consultar(con, limite=limite, deslocamento=deslocamento, **parametros)

    @r.get("/eventos.ics")
    def calendario(request: Request, parametros: Annotated[dict, Depends(filtros)]):
        with engine_de(request).connect() as con:
            resultado = consultar(con, limite=20000, **parametros)
        if resultado["total"] > 20000:
            raise HTTPException(422, "muitos eventos; restrinja o período ou o tipo do calendário")
        return Response(
            ics([Evento.model_validate(e) for e in resultado["eventos"]]),
            media_type="text/calendar",
            headers={"Content-Disposition": 'attachment; filename="calendario-raiz.ics"'},
        )

    return r
