"""Confiança de uma resposta do modelo local a partir dos logprobs (E7 passo 10).

O llama-server devolve, com logprobs=true, a probabilidade de cada token gerado (choices[0].logprobs.content, no
formato da OpenAI). A probabilidade é o softmax dos logits antes da gramática, então mostra o que o modelo queria
escrever, não só o que a gramática deixou.

A confiança é a menor probabilidade entre os tokens que escrevem os valores dos campos (onde o modelo decide:
"aceita" ou "recusa", true ou false). Os tokens da moldura do JSON ({, aspas, nomes dos campos) ficam de fora.
Não é uma probabilidade calibrada: o corte de cada tarefa sai do teste próprio em português (raiz/modelos/avaliacao).
"""

from __future__ import annotations

import json
import math
import re

_LITERAL = re.compile(rb"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?|true|false|null")
_TEXTO = re.compile(rb'"((?:[^"\\]|\\.)*)"')


def _bytes_do_token(t: dict) -> bytes:
    b = t.get("bytes")
    if isinstance(b, list) and b:
        return bytes(b)
    return str(t.get("token", "")).encode()


def spans_dos_valores(texto: bytes, dados: dict) -> list[tuple[int, int]]:
    """Trechos (em bytes) do JSON onde estão os valores dos campos de topo de `dados`."""
    out = []
    for chave in dados:
        m = re.search(re.escape(json.dumps(chave, ensure_ascii=False).encode()) + rb"\s*:\s*", texto)
        if not m:
            continue
        resto = texto[m.end() :]
        if resto.startswith(b'"'):
            s = _TEXTO.match(resto)
            if s:
                ini, fim = (s.start(1), s.end(1)) if s.end(1) > s.start(1) else (s.start(), s.end())
                out.append((m.end() + ini, m.end() + fim))
            continue
        s = _LITERAL.match(resto)
        if s:
            out.append((m.end() + s.start(), m.end() + s.end()))
    return out


def confianca(tokens: list[dict] | None, dados: dict | None) -> float | None:
    """Menor probabilidade entre os tokens dos valores; sem logprobs ou sem valores achados, None."""
    if not tokens or not dados:
        return None
    pedacos = [_bytes_do_token(t) for t in tokens]
    texto = b"".join(pedacos)
    spans = spans_dos_valores(texto, dados)
    if not spans:
        return None
    ps, pos = [], 0
    for t, b in zip(tokens, pedacos, strict=True):
        ini, fim = pos, pos + len(b)
        pos = fim
        if fim > ini and any(ini < f and fim > i for i, f in spans):
            lp = t.get("logprob")
            if isinstance(lp, int | float):
                ps.append(math.exp(min(float(lp), 0.0)))
    return round(min(ps), 6) if ps else None
