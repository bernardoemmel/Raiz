"""Cobrança Pix pela AbacatePay, com teste local como padrão mesmo quando há chave.

- Só com RAIZ_PIX_MODO=producao e RAIZ_ABACATEPAY_CHAVE: cria o QR Code Pix na API (`POST /v1/pixQrCode/create`),
  confere o pagamento (`GET /v1/pixQrCode/check`) e recebe o aviso de pagamento no webhook (evento `billing.paid`,
  com o segredo RAIZ_ABACATEPAY_WEBHOOK_SEGREDO). Chave de desenvolvimento da AbacatePay também simula o pagamento
  (`POST /v1/pixQrCode/simulate-payment`). Conferir os nomes na documentação vigente antes de ligar em produção.
- Sem a ativação explícita: teste local. O "copia e cola" é marcado como teste (não é código de banco e não paga nada).
  O pagamento se simula pela API interna (`POST /pagamentos/teste/{id}/pagar`) ou pela CLI.
"""

from __future__ import annotations

import datetime as dt
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


def modo() -> str:
    """Um segredo configurado nunca ativa vendas sozinho; valores desconhecidos fecham em teste."""
    return "producao" if os.environ.get("RAIZ_PIX_MODO") == "producao" else "teste"


def producao_habilitada() -> bool:
    return modo() == "producao" and bool(chave())


def segredo_webhook() -> str | None:
    return os.environ.get("RAIZ_ABACATEPAY_WEBHOOK_SEGREDO") or None


def criar(valor_rs: float, descricao: str, validade_s: int, cliente=None) -> Cobranca:
    """Cria a cobrança Pix. Sem ativação explícita, uma cobrança de teste local."""
    agora = dt.datetime.now(dt.UTC)
    k = chave()
    if not producao_habilitada():
        ident = f"teste_{secrets.token_hex(8)}"
        return Cobranca(ident, "teste", round(valor_rs, 2), f"RAIZ-TESTE-PIX-{ident}-NAO-E-CODIGO-DE-BANCO",
                        agora + dt.timedelta(seconds=validade_s))  # fmt: skip
    import httpx

    cli = cliente or httpx.Client(timeout=30)
    r = cli.post(f"{API}/pixQrCode/create", headers={"Authorization": f"Bearer {k}"},
                 json={"amount": int(round(valor_rs * 100)), "expiresIn": int(validade_s),
                       "description": descricao[:37]})  # fmt: skip
    r.raise_for_status()
    d = r.json().get("data") or {}
    exp = d.get("expiresAt")
    expira = dt.datetime.fromisoformat(exp.replace("Z", "+00:00")) if exp else agora + dt.timedelta(seconds=validade_s)
    # Sem o booleano explícito, não presumir que a cobrança é de produção.
    return Cobranca(str(d["id"]), "producao" if d.get("devMode") is False else "teste", round(valor_rs, 2),
                    d.get("brCode") or "", expira)  # fmt: skip


def conferir(externo_id: str, cliente=None) -> str:
    """Estado da cobrança na AbacatePay: pendente, paga ou expirada (cobrança de teste local: pendente)."""
    k = chave()
    if not producao_habilitada() or externo_id.startswith("teste_"):
        return "pendente"
    import httpx

    cli = cliente or httpx.Client(timeout=30)
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
