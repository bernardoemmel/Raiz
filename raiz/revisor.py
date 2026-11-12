"""Revisor de estilo e legibilidade antes de cada mensagem ao dono (E9, passo 2).

Chama o servidor próprio do LanguageTool (infra/languagetool, LGPL-2.1, só como serviço) no nível "picky", com a
regra de legibilidade do português ligada (READABILITY_RULE_DIFFICULT_PT), e fica só com os avisos de estilo
(issueType "style": legibilidade, frase longa, pleonasmo, prolixidade). Ortografia e gramática ficam de fora: o
nome da Raíz e as siglas (CAR, PA) não são erro.

`nota_de_envio(texto)` junta a nota do medidor (raiz/legibilidade.py) com os avisos do LanguageTool; é o que fica
guardado com cada mensagem. Sem RAIZ_LANGUAGETOOL_URL, sai só a nota do medidor. Com o servidor fora do ar, a nota
diz o erro e a mensagem segue para aprovação: quem aprova decide.

O texto vai só para o servidor da própria Raíz, nunca para a API pública do LanguageTool.
"""

from __future__ import annotations

from functools import lru_cache

import httpx

from raiz.config import config
from raiz.legibilidade import medir

REGRAS_LIGADAS = ("READABILITY_RULE_DIFFICULT_PT",)
MAX_AVISOS = 20


def url_padrao() -> str | None:
    return (config().languagetool_url or "").rstrip("/") or None


def revisar(texto: str, url: str | None = None, cliente: httpx.Client | None = None) -> dict | None:
    """Avisos de estilo e legibilidade do LanguageTool para o texto, ou None sem servidor configurado."""
    url = (url or url_padrao() or "").rstrip("/")
    if not url:
        return None
    dados = {
        "language": "pt-BR",
        "level": "picky",
        "enabledRules": ",".join(REGRAS_LIGADAS),
        "text": texto,
    }
    c = cliente or httpx.Client(timeout=15)
    try:
        r = c.post(f"{url}/v2/check", data=dados)
        r.raise_for_status()
        corpo = r.json()
    except (httpx.HTTPError, ValueError) as ex:
        return {"erro": f"LanguageTool fora do ar ou com erro: {type(ex).__name__}"}
    finally:
        if cliente is None:
            c.close()
    avisos = []
    for m in corpo.get("matches", []):
        regra = m.get("rule") or {}
        if regra.get("issueType") != "style":
            continue
        ini, tam = int(m.get("offset", 0)), int(m.get("length", 0))
        avisos.append(
            {
                "regra": regra.get("id"),
                "categoria": (regra.get("category") or {}).get("id"),
                "mensagem": m.get("message", ""),
                "trecho": texto[ini : ini + tam],
                "sugestoes": [x.get("value") for x in (m.get("replacements") or [])[:3]],
            }
        )
    return {
        "versao": (corpo.get("software") or {}).get("version"),
        "avisos": avisos[:MAX_AVISOS],
        "total": len(avisos),
    }


@lru_cache(maxsize=512)
def _revisar_em_cache(texto: str, url: str) -> dict | None:
    return revisar(texto, url)


def nota_de_envio(texto: str, url: str | None = None) -> dict:
    """A nota que fica guardada com a mensagem: o medidor e, com o servidor configurado, o LanguageTool."""
    nota = medir(texto)
    url = url or url_padrao()
    if url:
        lt = _revisar_em_cache(texto, url)
        if lt and "erro" in lt:
            _revisar_em_cache.cache_clear()  # não guarda a falha: a próxima chamada tenta de novo
        nota["languagetool"] = lt
    return nota
