"""Webhook Pix das consultas: segredo, assinatura, conferência no provedor e débito único.

Contrato oficial: https://docs.abacatepay.com/pages/notificacoes/seguranca
A chave HMAC é pública e prova integridade; a autenticação exige também o segredo
privado do webhook. Os bytes do evento nunca são gravados em logs ou no banco.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from collections.abc import Callable

import httpx
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from raiz import prospeccao_acesso as acesso
from raiz.pedidos import pix

MAX_CORPO = 262_144


def verificar_assinatura(corpo: bytes, segredo: str, assinatura: str) -> bool:
    """Falha fechada: configurações ausentes, assinatura inválida ou segredo errado."""
    esperado = pix.segredo_webhook()
    chave_publica = os.environ.get("RAIZ_ABACATEPAY_WEBHOOK_CHAVE_PUBLICA")
    if not esperado or len(esperado) < 32 or not chave_publica:
        return False
    if not hmac.compare_digest(segredo.encode(), esperado.encode()):
        return False
    calculada = base64.b64encode(hmac.digest(chave_publica.encode(), corpo, hashlib.sha256)).decode()
    return hmac.compare_digest(calculada.encode(), assinatura.encode())


def _conferir(engine, ident: str) -> dict:
    with engine.connect() as con:
        compra = con.execute(
            text("""select id, cliente_id from negocio.prospeccao_compra
                    where externo_id = :id and modo = 'producao'"""),
            {"id": ident},
        ).first()
    if compra is None:
        return {"ignorado": True}
    # Não confiar no estado, preço ou cliente enviados no evento. A cobrança
    # local identifica o cliente; conferir_compra consulta o provedor e trava a carteira.
    atual = acesso.conferir_compra(engine, compra.cliente_id, str(compra.id))
    return {"recebido": True, "creditado": atual["estado"] == "paga"}


def roteador(engine_de: Callable) -> APIRouter:
    r = APIRouter(tags=["pagamentos de consultas"])

    @r.post("/pagamentos/prospeccao/abacatepay")
    async def receber(request: Request) -> dict:
        corpo = bytearray()
        async for parte in request.stream():
            if len(corpo) + len(parte) > MAX_CORPO:
                raise HTTPException(413, "Aviso de pagamento acima do limite.")
            corpo.extend(parte)
        segredo = request.headers.get("X-Webhook-Secret") or request.query_params.get("webhookSecret", "")
        assinatura = request.headers.get("X-Webhook-Signature", "")
        if not verificar_assinatura(bytes(corpo), segredo, assinatura):
            raise HTTPException(401, "Aviso de pagamento não autenticado.")
        try:
            evento = json.loads(corpo)
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(400, "Aviso de pagamento inválido.") from exc
        if not isinstance(evento, dict):
            raise HTTPException(400, "Aviso de pagamento inválido.")
        if not pix.producao_habilitada() or evento.get("devMode") is True:
            return {"ignorado": True, "motivo": "Pagamento em modo de teste."}
        ident = pix.id_do_webhook(evento)
        if ident is None:
            return {"ignorado": True}
        try:
            return await run_in_threadpool(_conferir, engine_de(request), ident)
        except acesso.ErroAcesso as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(502, "Não foi possível conferir o pagamento; tente entregar novamente.") from exc

    return r
