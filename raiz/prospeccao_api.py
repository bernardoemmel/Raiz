"""Prospecção: agregado aberto; ficha da terra com sessão, crédito pago e limites no servidor."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from raiz import busca
from raiz import prospeccao_acesso as acesso
from raiz import prospeccao_buscas as buscas_salvas
from raiz import prospeccao_servico as servico


class Compra(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plano: str = Field(min_length=1, max_length=50)
    chave_idempotencia: str = Field(min_length=8, max_length=100)


class Contato(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codigo_car: str = Field(min_length=3, max_length=80)


class Comparacao(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codigos_car: list[str] = Field(min_length=2, max_length=5)


class BuscaSalva(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nome: str = Field(min_length=1, max_length=80)
    filtros: busca.FiltrosProspeccao


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
        return _executar(servico.autenticar, engine_de(request), authorization[7:].strip())

    def publico(request: Request):
        # Não confiar em X-Forwarded-For enviado pelo cliente. O proxy deve configurar o ASGI corretamente.
        ip = request.client.host if request.client else "desconhecido"
        chave = "ip:" + hashlib.sha256(ip.encode()).hexdigest()
        limite(request, chave, "agregados", 60)

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
        return _executar(
            busca.buscar_prospeccao,
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
        return _executar(servico.consultar_ficha, engine_de(request), cid, car)

    @r.post("/fichas/{car}/desbloquear")
    def desbloquear(car: str, request: Request, cid: int = Depends(cliente)):
        return _executar(servico.consultar_ficha, engine_de(request), cid, car, desbloquear=True)

    @r.get("/fichas/{car}/pdf")
    def pdf(car: str, request: Request, cid: int = Depends(cliente)):
        conteudo = _executar(servico.exportar_ficha_pdf, engine_de(request), cid, car)
        return Response(
            conteudo,
            media_type="application/pdf",
            headers={
                "Cache-Control": "private, no-store",
                "Vary": "Authorization",
                "Content-Disposition": 'attachment; filename="ficha-da-terra.pdf"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    @r.post("/comparar")
    def comparar(corpo: Comparacao, request: Request, cid: int = Depends(cliente)):
        return _executar(servico.comparar_fichas, engine_de(request), cid, corpo.codigos_car)

    @r.get("/buscas-salvas")
    def listar_buscas(request: Request, cid: int = Depends(cliente)):
        return _executar(buscas_salvas.listar, engine_de(request), cid)

    @r.post("/buscas-salvas")
    def salvar_busca(corpo: BuscaSalva, request: Request, cid: int = Depends(cliente)):
        return _executar(buscas_salvas.salvar, engine_de(request), cid, corpo.nome, corpo.filtros)

    @r.delete("/buscas-salvas/{busca_id}")
    def excluir_busca(busca_id: str, request: Request, cid: int = Depends(cliente)):
        return _executar(buscas_salvas.excluir, engine_de(request), cid, busca_id)

    @r.get("/avisos")
    def avisos(
        request: Request,
        depois: int = Query(default=0, ge=0),
        limite: int = Query(default=50, ge=1, le=100),
        cid: int = Depends(cliente),
    ):
        return _executar(buscas_salvas.avisos, engine_de(request), cid, depois=depois, limite=limite)

    @r.post("/avisos/{aviso_id}/ler")
    def ler_aviso(aviso_id: int, request: Request, cid: int = Depends(cliente)):
        return _executar(buscas_salvas.ler_aviso, engine_de(request), cid, aviso_id)

    @r.post("/contatos")
    def pedir_contato(corpo: Contato, request: Request, cid: int = Depends(cliente)):
        limite(request, f"cliente:{cid}", "pedidos_contato", 20)
        return _executar(acesso.pedir_contato, engine_de(request), cid, corpo.codigo_car)

    return r
