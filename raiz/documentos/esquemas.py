"""Peças para montar o JSON Schema da saída estruturada (todo campo obrigatório; opcional = aceita null)."""

from __future__ import annotations


def txt(desc: str, nulo: bool = True) -> dict:
    return {"type": ["string", "null"] if nulo else "string", "description": desc}


def num(desc: str) -> dict:
    return {"type": ["number", "null"], "description": desc}


def enum(valores: list[str], desc: str, nulo: bool = False) -> dict:
    tipo = ["string", "null"] if nulo else "string"
    return {"type": tipo, "enum": [*valores, *([None] if nulo else [])], "description": desc}


def obj(props: dict) -> dict:
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}
