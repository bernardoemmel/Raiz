"""Rotas do pedido de lote, no contrato com o front (front/compartilhado/pedidos/tipos.ts), mais as do fundador
(PATCH /pedidos/{id}, alertas) e as internas (resposta do dono, ondas, vigia, reservas e o aviso de pagamento).

Cliente: Authorization: Bearer <token da sessão> (entrar sem senha, pelo link no e-mail). Internas: o token da API.
Nada aqui devolve nome, CPF, CNPJ ou contato do dono."""

from __future__ import annotations

import hmac
from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel

from raiz.pedidos import pix
from raiz.pedidos import servico as S
from raiz.pedidos.campos import CamposPedido


class PedidoEntrar(BaseModel):
    email: str


class Confirmar(BaseModel):
    token: str


class Mudanca(BaseModel):
    opcao: Literal["barata", "segura", "compacta"]
    acao: Literal["tirar", "trocar"]
    cod_imovel: str
    por: str | None = None


class Solicitar(BaseModel):
    opcao: Literal["barata", "segura", "compacta"] = "segura"


class Resposta(BaseModel):
    nivel: Literal["contatado", "interessado", "aceite_fase1", "contrato_firme", "recusou", "sem_resposta"]
    canal: str | None = None
    motivo: str | None = None
    versao_termo: str | None = None
    pedido_id: str | None = None


class Converter(BaseModel):
    ha_assinados: float


def _erro(ex: S.ErroPedido) -> HTTPException:
    msg = str(ex)
    return HTTPException(404 if "não encontrad" in msg else 422, {"mensagem": msg})


def roteador_cliente(engine_de: Callable) -> APIRouter:
    r = APIRouter(tags=["pedidos"])

    def cliente(request: Request, authorization: str | None = Header(default=None)) -> int:
        token = (authorization or "").removeprefix("Bearer ").strip()
        cid = S.cliente_da_sessao(engine_de(request), token)
        if cid is None:
            raise HTTPException(401, {"mensagem": "entre de novo: sessão inválida ou vencida"})
        return cid

    @r.post("/entrar")
    def entrar(corpo: PedidoEntrar, request: Request) -> dict:
        try:
            S.pedir_link(engine_de(request), corpo.email, str(request.headers.get("origin") or ""))
        except S.ErroPedido as ex:
            raise _erro(ex) from ex
        return {"enviado": True}

    @r.post("/entrar/confirmar")
    def confirmar(corpo: Confirmar, request: Request) -> dict:
        try:
            return S.confirmar_link(engine_de(request), corpo.token)
        except S.ErroPedido as ex:
            raise HTTPException(401, {"mensagem": str(ex)}) from ex

    @r.get("/pedidos")
    def listar(request: Request, cid: int = Depends(cliente)) -> list[dict]:
        return S.pedidos_do_cliente(engine_de(request), cid)

    @r.post("/pedidos")
    def criar(campos: CamposPedido, request: Request, cid: int = Depends(cliente)) -> dict:
        return S.criar_pedido(engine_de(request), cid, campos)

    @r.get("/pedidos/{pedido_id}")
    def obter(pedido_id: str, request: Request, cid: int = Depends(cliente)) -> dict:
        try:
            return S.obter_pedido(engine_de(request), pedido_id, cid)
        except S.ErroPedido as ex:
            raise _erro(ex) from ex

    def _mudar(pedido_id: str, m: Mudanca, request: Request, cid: int) -> dict:
        try:
            return S.mudar_lote(engine_de(request), pedido_id, cid, m.model_dump())
        except S.ErroPedido as ex:
            raise _erro(ex) from ex

    @r.post("/pedidos/{pedido_id}/lote")
    def lote(pedido_id: str, m: Mudanca, request: Request, cid: int = Depends(cliente)) -> dict:
        return _mudar(pedido_id, m, request, cid)

    @r.patch("/pedidos/{pedido_id}")
    def patch(pedido_id: str, m: Mudanca, request: Request, cid: int = Depends(cliente)) -> dict:
        return _mudar(pedido_id, m, request, cid)

    @r.post("/pedidos/{pedido_id}/solicitar-interesse")
    def solicitar(pedido_id: str, corpo: Solicitar, request: Request, cid: int = Depends(cliente)) -> dict:
        try:
            return S.solicitar_interesse(engine_de(request), pedido_id, cid, corpo.opcao)
        except S.ErroPedido as ex:
            raise _erro(ex) from ex

    @r.get("/pedidos/{pedido_id}/andamento")
    def andamento(pedido_id: str, request: Request, cid: int = Depends(cliente)) -> dict:
        try:
            return S.andamento(engine_de(request), pedido_id, cid)
        except S.ErroPedido as ex:
            raise _erro(ex) from ex

    @r.post("/pedidos/{pedido_id}/reservar")
    def reservar(pedido_id: str, request: Request, cid: int = Depends(cliente)) -> dict:
        try:
            return S.reservar(engine_de(request), pedido_id, cid)
        except S.ErroPedido as ex:
            raise _erro(ex) from ex

    @r.get("/pedidos/{pedido_id}/reserva")
    def reserva(pedido_id: str, request: Request, cid: int = Depends(cliente)) -> dict:
        try:
            return S.cobranca_do_pedido(engine_de(request), pedido_id, cid)
        except S.ErroPedido as ex:
            raise _erro(ex) from ex

    @r.get("/pedidos/{pedido_id}/alertas")
    def alertas(pedido_id: str, request: Request, cid: int = Depends(cliente)) -> list[dict]:
        try:
            return S.obter_pedido(engine_de(request), pedido_id, cid)["alertas"]
        except S.ErroPedido as ex:
            raise _erro(ex) from ex

    @r.get("/notificacoes")
    def notificacoes(request: Request, cid: int = Depends(cliente)) -> list[dict]:
        return S.notificacoes(engine_de(request), cid)

    return r


def roteador_interno(engine_de: Callable) -> APIRouter:
    """Para a equipe e os agentes da Raíz (token da API): resposta do dono, passo das ondas, vigia e reservas."""
    r = APIRouter(tags=["pedidos (interno)"])

    @r.post("/interesse/{cod_imovel}")
    def interesse(cod_imovel: str, corpo: Resposta, request: Request) -> dict:
        try:
            n = S.registrar_resposta(engine_de(request), cod_imovel, corpo.nivel, corpo.canal, corpo.motivo,
                                     corpo.versao_termo, corpo.pedido_id)  # fmt: skip
        except S.ErroPedido as ex:
            raise _erro(ex) from ex
        return {"cod_imovel": cod_imovel, "nivel": n}

    @r.post("/pedidos-avancar")
    def avancar(request: Request) -> dict:
        eng = engine_de(request)
        return {pid: S.avancar(eng, pid) for pid in S.pedidos_abertos(eng)}

    @r.post("/pedidos-vigiar")
    def vigiar(request: Request) -> dict:
        return S.vigiar(engine_de(request))

    @r.post("/reservas/expirar")
    def expirar(request: Request) -> dict:
        return {"expiradas": S.expirar_reservas(engine_de(request))}

    @r.post("/reservas/{reserva_id}/converter")
    def converter(reserva_id: int, corpo: Converter, request: Request) -> dict:
        try:
            return S.converter_reserva(engine_de(request), reserva_id, corpo.ha_assinados)
        except S.ErroPedido as ex:
            raise _erro(ex) from ex

    @r.post("/pagamentos/teste/{externo_id}/pagar")
    def pagar_teste(externo_id: str, request: Request) -> dict:
        if not externo_id.startswith("teste_"):
            raise HTTPException(422, {"mensagem": "só cobrança de teste"})
        try:
            return {"reserva": S.confirmar_pagamento(engine_de(request), externo_id, quem="teste")}
        except S.ErroPedido as ex:
            raise _erro(ex) from ex

    return r


def roteador_webhook(engine_de: Callable) -> APIRouter:
    """Aviso de pagamento da AbacatePay (público, conferido pelo segredo do webhook)."""
    r = APIRouter(tags=["pagamentos"])

    @r.post("/pagamentos/abacatepay")
    async def webhook(request: Request, webhookSecret: str = Query(default="")) -> dict:  # noqa: N803
        esperado = pix.segredo_webhook()
        if not esperado or not hmac.compare_digest(webhookSecret.encode(), esperado.encode()):
            raise HTTPException(401, "segredo inválido")
        corpo = await request.json()
        ident = pix.id_do_webhook(corpo)
        if ident is None:
            return {"ignorado": True}
        try:
            return {"reserva": S.confirmar_pagamento(engine_de(request), ident, quem="abacatepay")}
        except S.ErroPedido:
            return {"ignorado": True}

    return r
