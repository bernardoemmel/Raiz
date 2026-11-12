"""Rotas do pedido de lote, no contrato com o front (front/compartilhado/pedidos/tipos.ts), mais as do fundador
(PATCH /pedidos/{id}, alertas) e as internas (resposta do dono, ondas, vigia, reservas e o aviso de pagamento).

Cliente: Authorization: Bearer <token da sessão> (entrar sem senha, pelo link no e-mail). Internas: o token da API.
Nada aqui devolve nome, CPF, CNPJ ou contato do dono."""

from __future__ import annotations

import hmac
import os
import uuid
from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from raiz import salvaguardas as SG
from raiz.pedidos import pix
from raiz.pedidos import servico as S


class PedidoEntrar(BaseModel):
    email: str


class Confirmar(BaseModel):
    token: str


class Resposta(BaseModel):
    nivel: Literal["contatado", "interessado", "aceite_fase1", "contrato_firme", "recusou", "sem_resposta"]
    canal: str | None = None
    motivo: str | None = None
    versao_termo: str | None = None
    pedido_id: str | None = None


class Revisar(BaseModel):
    cod_imovel: str
    motivo: Literal["exclusao_automatica", "nota_de_risco", "salvaguarda"]


class ResolucaoHumana(BaseModel):
    revisor_id: uuid.UUID
    decisao: Literal["mantida", "corrigir_dados", "recalcular"]
    evidencia: SG.Evidencia


class Converter(BaseModel):
    ha_assinados: float


def _erro(ex: S.ErroPedido) -> HTTPException:
    msg = str(ex)
    return HTTPException(404 if "não encontrad" in msg else 422, {"mensagem": msg})


def roteador_cliente(engine_de: Callable) -> APIRouter:
    """Login por e-mail e aliases do front para a API paga, que concentra a política de acesso.

    O 307 preserva método, corpo e credencial; só muda o caminho na mesma origem. Não executa
    serviço nem cobrança aqui. Assim o caminho antigo nunca evita liberação, saldo ou limite.
    """
    r = APIRouter(tags=["pedidos"])

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

    def destino(request: Request) -> RedirectResponse:
        caminho = f"/v1{request.url.path}"
        if request.url.query:
            caminho += f"?{request.url.query}"
        return RedirectResponse(caminho, status_code=307, headers={"Cache-Control": "no-store"})

    @r.api_route("/pedidos", methods=["GET", "POST"], include_in_schema=False)
    def pedidos(request: Request) -> RedirectResponse:
        return destino(request)

    @r.api_route("/pedidos/{caminho:path}", methods=["GET", "POST", "PATCH"], include_in_schema=False)
    def pedido(request: Request, caminho: str) -> RedirectResponse:
        return destino(request)

    @r.get("/notificacoes", include_in_schema=False)
    def notificacoes(request: Request) -> RedirectResponse:
        return destino(request)

    return r


def roteador_interno(engine_de: Callable) -> APIRouter:
    """Para a equipe e os agentes da Raíz (token da API): resposta do dono, passo das ondas, vigia e reservas."""
    r = APIRouter(tags=["pedidos (interno)"])

    @r.post("/salvaguardas/programas")
    def programa(corpo: SG.Programa, request: Request) -> dict:
        SG.registrar_programa(engine_de(request), corpo)
        return {"programa_id": corpo.id}

    @r.post("/salvaguardas/cobertura")
    def cobertura(corpo: SG.Cobertura, request: Request) -> dict:
        SG.registrar_cobertura(engine_de(request), corpo)
        return {"uf": corpo.uf, "valida_ate": corpo.valida_ate.isoformat()}

    @r.post("/salvaguardas/imoveis/{cod_imovel}")
    def verificacao(cod_imovel: str, corpo: SG.Verificacao, request: Request) -> dict:
        SG.registrar_verificacao(engine_de(request), cod_imovel, corpo)
        return {"cod_imovel": cod_imovel, "registrada": True}

    @r.post("/salvaguardas/revisoes/{revisao_id}/resolver")
    def resolver(
        revisao_id: int, corpo: ResolucaoHumana, request: Request, x_revisao_humana: str = Header(default="")
    ) -> dict:
        # A credencial do serviço/agente não basta; esta credencial só pertence ao backoffice humano.
        esperado = os.environ.get("RAIZ_REVISAO_HUMANA_TOKEN", "")
        if not esperado or not hmac.compare_digest(x_revisao_humana.encode(), esperado.encode()):
            raise HTTPException(403, "revisão exige autenticação do revisor humano")
        try:
            return SG.resolver_revisao(
                engine_de(request), revisao_id, str(corpo.revisor_id), corpo.decisao, corpo.evidencia
            )
        except S.ErroPedido as ex:
            raise _erro(ex) from ex

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
