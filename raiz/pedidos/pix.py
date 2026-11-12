"""Cobrança Pix da reserva do grupo pela AbacatePay (https://docs.abacatepay.com), com modo de teste sem chave.

- Com RAIZ_ABACATEPAY_CHAVE (só por variável de ambiente): cria o QR Code Pix na API (`POST /v1/pixQrCode/create`),
  confere o pagamento (`GET /v1/pixQrCode/check`) e recebe o aviso de pagamento no webhook (evento `billing.paid`,
  com o segredo RAIZ_ABACATEPAY_WEBHOOK_SEGREDO). Chave de desenvolvimento da AbacatePay também simula o pagamento
  (`POST /v1/pixQrCode/simulate-payment`). Conferir os nomes na documentação vigente antes de ligar em produção.
- Sem chave: modo de teste local. O "copia e cola" é marcado como teste (não é código de banco e não paga nada) e o
  pagamento se simula pela API interna (`POST /pagamentos/teste/{id}/pagar`) ou pela CLI.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import os
import secrets
from dataclasses import dataclass

API = "https://api.abacatepay.com/v1"


@dataclass
class Cobranca:
    externo_id: str
    modo: str  # teste | producao
    valor_rs: float
    copia_e_cola: str
    expira_em: dt.datetime
    estado: str = "pendente"


def chave() -> str | None:
    return os.environ.get("RAIZ_ABACATEPAY_CHAVE") or None


def segredo_webhook() -> str | None:
    return os.environ.get("RAIZ_ABACATEPAY_WEBHOOK_SEGREDO") or None


def criar(
    valor_rs: float, descricao: str, validade_s: int, cliente=None, chave_idempotencia: str | None = None
) -> Cobranca:
    """Cria a cobrança Pix. Sem chave, uma cobrança de teste local."""
    if not math.isfinite(valor_rs) or valor_rs <= 0 or validade_s <= 0:
        raise ValueError("valor e validade do Pix devem ser positivos e finitos")
    agora = dt.datetime.now(dt.UTC)
    k = chave()
    if not k:
        ident = "teste_" + (
            hashlib.sha256(chave_idempotencia.encode()).hexdigest()[:16] if chave_idempotencia else secrets.token_hex(8)
        )
        return Cobranca(ident, "teste", round(valor_rs, 2), f"RAIZ-TESTE-PIX-{ident}-NAO-E-CODIGO-DE-BANCO",
                        agora + dt.timedelta(seconds=validade_s))  # fmt: skip
    import httpx

    cabecalhos = {"Authorization": f"Bearer {k}"}
    # v1 não documenta essa garantia. Só enviar o cabeçalho após confirmar suporte na integração contratada.
    if chave_idempotencia and os.environ.get("RAIZ_ABACATEPAY_IDEMPOTENCIA_SUPORTADA") == "1":
        cabecalhos["Idempotency-Key"] = chave_idempotencia
    dados = {"amount": int(round(valor_rs * 100)), "expiresIn": int(validade_s), "description": descricao[:37]}
    if cliente is None:
        with httpx.Client(timeout=3.0) as cli:
            r = cli.post(f"{API}/pixQrCode/create", headers=cabecalhos, json=dados)
    else:
        r = cliente.post(f"{API}/pixQrCode/create", headers=cabecalhos, json=dados)
    r.raise_for_status()
    d = r.json().get("data") or {}
    exp = d.get("expiresAt")
    expira = dt.datetime.fromisoformat(exp.replace("Z", "+00:00")) if exp else agora + dt.timedelta(seconds=validade_s)
    return Cobranca(str(d["id"]), "teste" if d.get("devMode") else "producao", round(valor_rs, 2),
                    d.get("brCode") or "", expira)  # fmt: skip


def conferir(externo_id: str, cliente=None) -> str:
    """Estado da cobrança na AbacatePay: pendente, paga ou expirada (cobrança de teste local: pendente)."""
    k = chave()
    if not k or externo_id.startswith("teste_"):
        return "pendente"
    import httpx

    cli = cliente or httpx.Client(timeout=3.0)
    r = cli.get(f"{API}/pixQrCode/check", params={"id": externo_id}, headers={"Authorization": f"Bearer {k}"})
    r.raise_for_status()
    st = str((r.json().get("data") or {}).get("status") or "").upper()
    return {"PAID": "paga", "EXPIRED": "expirada", "CANCELLED": "cancelada"}.get(st, "pendente")


def id_do_webhook(corpo: dict) -> str | None:
    """O id da cobrança paga num aviso da AbacatePay (evento billing.paid), ou None se não for pagamento."""
    if str(corpo.get("event") or "") != "billing.paid":
        return None
    d = corpo.get("data") or {}
    for caminho in (("pixQrCode", "id"), ("billing", "id"), ("id",)):
        x = d
        for k in caminho:
            x = x.get(k) if isinstance(x, dict) else None
        if x:
            return str(x)
    return None


def qr_svg(copia_e_cola: str) -> str:
    """QR SVG gerado localmente com qrcode; o código nunca é enviado a serviço externo de imagens."""
    import io

    import qrcode
    from qrcode.image.svg import SvgPathImage

    if not isinstance(copia_e_cola, str) or not copia_e_cola or len(copia_e_cola) > 4096:
        raise ValueError("código Pix inválido para gerar QR")
    imagem = qrcode.make(copia_e_cola, image_factory=SvgPathImage)
    saida = io.BytesIO()
    imagem.save(saida)
    return saida.getvalue().decode("utf-8")
