"""Modelo simulado por regras, sem servidor nem chave (E7 passo 10).

Serve para rodar o teste próprio e a calibração de ponta a ponta onde não há llama.cpp nem chave da Anthropic, e como
linha de base: um modelo de verdade tem de passar dele. Responde só as tarefas do aceite, com uma confiança grosseira
(quantas regras bateram). Não vai para produção: a cascata usa o Qwen, o Haiku e o Sonnet.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

from raiz.modelos.base import Pedido, Resposta

_ACEITA = (
    r"\binteress",
    r"\bquero\b",
    r"\baceito\b",
    r"^sim\b",
    r"\bsim,",
    r"\btopo\b",
    r"\bbora\b",
    r"\bfechado\b",
    r"pode (mandar|seguir|marcar|contar)",
    r"\bconcordou\b",
    r"\bquero (seguir|participar)",
)
_RECUSA = (
    r"\bnao (tenho|quero|posso|vou|me manda)",
    r"^nao\b",
    r"\bdispenso\b",
    r"\bto fora\b",
    r"\bprefiro nao\b",
    r"nao e pra mim",
    r"\bmas nao\b",
    r"tirar meu numero",
    r"\bnao vamos\b",
)
_NUMEROS = {"doze": 12, "vinte": 20, "trinta": 30, "quarenta": 40, "sessenta": 60, "quatro": 4}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c)).strip()


def _bate(padroes, t: str) -> int:
    return sum(1 for p in padroes if re.search(p, t))


def intencao(texto: str) -> tuple[str, float]:
    t = _norm(texto)
    if not re.search(r"[a-z]", t) or (t.startswith("[") and t.endswith("]")):
        return "outro", 0.9
    if "?" in t:
        return "duvida", 0.85
    a, r = _bate(_ACEITA, t), _bate(_RECUSA, t)
    if r and not a:
        return "recusa", min(0.6 + 0.15 * r, 0.95)
    if a and not r:
        return "aceita", min(0.6 + 0.15 * a, 0.95)
    if a and r:
        return ("recusa" if r >= a else "aceita"), 0.35
    return "outro", 0.5


def _valores(t: str) -> set[float]:
    vals = {float(x.replace(".", "").replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", t)}
    vals |= {float(v) for k, v in _NUMEROS.items() if re.search(rf"\b{k}\b", t)}
    if re.search(r"\bquatro (hectares? )?e meio\b", t):
        vals.add(4.5)
    if "tres decadas" in t:
        vals.add(30.0)
    return vals


def explicacao(sistema: str, texto: str) -> tuple[dict, float]:
    t, s = _norm(texto), _norm(sistema)
    area = float(re.search(r"area de ([\d.]+) hectares", s).group(1))
    prazo = float(re.search(r"prazo de (\d+) anos", s).group(1))
    vals = _valores(t)
    perto = any(abs(v - area) <= max(0.6, 0.1 * area) for v in vals)
    out = {
        "entendeu_area": perto and bool(re.search(r"\bha\b|hectare", t)),
        "entendeu_prazo": prazo in vals and bool(re.search(r"\bano|decada", t)),
        "entendeu_pagamento": bool(re.search(r"\bpag|receb|ganho|dinheiro|por cento|%", t))
        and not re.search(r"uma vez so|fixo|por mes", t),
        "desistiu": bool(re.search(r"desist|nao quero mais|nao vou (fazer|entrar)|nao tenho mais interesse", t)),
    }
    certeza = 0.9 if (sum(out.values()) in (0, 4) or out["desistiu"]) else 0.6
    return out, certeza


class Simulado:
    provedor = "simulado"

    def __init__(self, nome: str = "simulado-regras-1"):
        self.nome = nome

    def responder_json(self, pedido: Pedido) -> Resposta:
        base = dict(modelo=self.nome, provedor=self.provedor, custo_usd=Decimal(0), custo_fonte="local")
        if pedido.tarefa == "aceite.intencao":
            rotulo, c = intencao(pedido.mensagem)
            return Resposta({"intencao": rotulo}, confianca=c, **base)
        if pedido.tarefa == "aceite.explicacao":
            dados, c = explicacao(pedido.sistema, pedido.mensagem)
            return Resposta(dados, confianca=c, **base)
        return Resposta(None, erro=f"o simulado não tem regra para {pedido.tarefa}", **base)
