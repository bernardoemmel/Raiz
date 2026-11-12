"""Prospecção: agregado aberto; ficha da terra com sessão, crédito pago e limites no servidor."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from raiz import busca, front_api, imovel_dados, prospeccao_visual
from raiz import prospeccao_acesso as acesso
from raiz.pedidos import servico as pedidos


class Compra(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plano: str = Field(min_length=1, max_length=50)
    chave_idempotencia: str = Field(min_length=8, max_length=100)


class Contato(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codigo_car: str = Field(min_length=3, max_length=80)


class Consulta(busca.FiltrosProspeccao):
    pagina: int = Field(default=1, ge=1, le=200)
    limite: int = Field(default=20, ge=1, le=50)


def _executar(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except acesso.ErroAcesso as exc:
        cabecalhos = {"Retry-After": str(exc.retry_after or 60)} if exc.status == 429 else None
        raise HTTPException(exc.status, str(exc), headers=cabecalhos) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, "O serviço de pagamento está indisponível. Tente novamente.") from exc


def roteador(engine_de: Callable) -> APIRouter:
    r = APIRouter(prefix="/prospeccao", tags=["ficha da fazenda"])

    def privado(response: Response):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Vary"] = "Authorization"

    def limite(request: Request, chave: str, acao: str, quantidade: int, janela: int = 60):
        _executar(acesso.limitar, engine_de(request), chave, acao, quantidade, janela)

    def cliente(request: Request, response: Response, authorization: str | None = Header(default=None)) -> int:
        privado(response)
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Entre na sua conta para consultar fazendas.")
        cid = pedidos.cliente_da_sessao(engine_de(request), authorization[7:].strip())
        if cid is None:
            raise HTTPException(401, "Sua sessão expirou. Entre novamente.")
        limite(request, f"cliente:{cid}", "consultas", 60)
        return cid

    def publico(request: Request):
        # Não confiar em X-Forwarded-For enviado pelo cliente. O proxy deve configurar o ASGI corretamente.
        ip = request.client.host if request.client else "desconhecido"
        chave = "ip:" + hashlib.sha256(ip.encode()).hexdigest()
        limite(request, chave, "agregados", 60)

    def montar(request: Request, car: str) -> dict:
        eng = engine_de(request)
        linhas = front_api.imoveis_do_municipio(eng, cod_imovel=car)
        if not linhas:
            raise HTTPException(404, "Fazenda ainda não disponível na base da Raíz.")
        linha = linhas[0]
        codigo = linha["cod_imovel"]
        return imovel_dados.ficha_prospeccao(linha, front_api.versao(eng, codigo), front_api.do_banco(eng, codigo))

    @r.get("/planos")
    def planos(request: Request, _: None = Depends(publico)):
        return _executar(acesso.planos)

    @r.get("/agregado")
    def agregado(
        request: Request,
        filtros: Annotated[busca.FiltrosProspeccao, Query()],
        _: None = Depends(publico),
    ):
        try:
            return busca.buscar_prospeccao(engine_de(request), filtros, incluir_imoveis=False)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @r.get("/busca")
    def buscar(
        request: Request,
        consulta: Annotated[Consulta, Query()],
        cid: int = Depends(cliente),
    ):
        limite(request, f"cliente:{cid}", "busca", 30)
        filtros = busca.FiltrosProspeccao.model_validate(consulta.model_dump(exclude={"pagina", "limite"}))
        return busca.buscar_prospeccao(
            engine_de(request),
            filtros,
            cliente_id=cid,
            pagina=consulta.pagina,
            limite=consulta.limite,
            incluir_imoveis=True,
        )

    @r.get("/saldo")
    def saldo(request: Request, cid: int = Depends(cliente)):
        return _executar(acesso.saldo, engine_de(request), cid)

    @r.post("/compras")
    def comprar(corpo: Compra, request: Request, cid: int = Depends(cliente)):
        limite(request, f"cliente:{cid}", "compras", 5)
        return _executar(acesso.iniciar_compra, engine_de(request), cid, corpo.plano, corpo.chave_idempotencia)

    @r.get("/compras")
    def compras(request: Request, cid: int = Depends(cliente)):
        return _executar(acesso.listar_compras, engine_de(request), cid)

    @r.get("/compras/{compra_id}")
    def conferir(compra_id: str, request: Request, cid: int = Depends(cliente)):
        limite(request, f"cliente:{cid}", "conferir_pagamento", 15)
        return _executar(acesso.conferir_compra, engine_de(request), cid, compra_id)

    @r.get("/fichas/{car}")
    def ficha(car: str, request: Request, cid: int = Depends(cliente)):
        _executar(acesso.exigir_desbloqueio, engine_de(request), cid, car)
        return montar(request, car)

    @r.get("/fichas/{car}/visual")
    def visual(car: str, request: Request, cid: int = Depends(cliente)):
        _executar(acesso.exigir_desbloqueio, engine_de(request), cid, car)
        return prospeccao_visual.consultar(engine_de(request), car)

    @r.get("/fichas/{car}/visual/satelite")
    def satelite(car: str, request: Request, cid: int = Depends(cliente)):
        _executar(acesso.exigir_desbloqueio, engine_de(request), cid, car)
        return prospeccao_visual.satelite_disponivel(engine_de(request), car)

    @r.get("/fichas/{car}/visual/satelite.webp")
    def imagem_satelite(car: str, request: Request, cid: int = Depends(cliente)):
        _executar(acesso.exigir_desbloqueio, engine_de(request), cid, car)
        _, arquivo = prospeccao_visual.imagem(engine_de(request), car)
        return FileResponse(
            arquivo, media_type="image/webp", headers={"Cache-Control": "private, no-store", "Vary": "Authorization"}
        )

    @r.post("/fichas/{car}/desbloquear")
    def desbloquear(car: str, request: Request, cid: int = Depends(cliente)):
        limite(request, f"cliente:{cid}", "desbloqueios", 100, 86400)
        # Montar antes evita cobrar ficha que falhou. O serviço verifica existência e exclusividade na transação.
        dado = montar(request, car)
        _executar(acesso.desbloquear, engine_de(request), cid, car)
        return dado

    @r.post("/contatos")
    def pedir_contato(corpo: Contato, request: Request, cid: int = Depends(cliente)):
        limite(request, f"cliente:{cid}", "pedidos_contato", 20)
        return _executar(acesso.pedir_contato, engine_de(request), cid, corpo.codigo_car)

    return r
