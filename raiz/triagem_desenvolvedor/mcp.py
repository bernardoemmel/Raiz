"""Ferramenta do MCP e função do endpoint da API, prontas para quando o servidor subir.

Mesmo formato de raiz/prospeccao/mcp.py: `ferramentas()` descreve a ferramenta `triar_fazendas` e `executar` produz o
CallToolResult. O host MCP (raiz/publica/servidor_mcp.py) ainda NÃO a registra: quem decide escopo, preço e limite por
empresa é o fundador (a triagem usa os dados completos de cada fazenda). O host entrega o contexto OAuth e o callback
`autorizar`, que aplica conta paga, escopo e auditoria; nunca passar um callback vazio em produção.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Engine

from raiz import triagem_desenvolvedor as T
from raiz.triagem_desenvolvedor import dados as D
from raiz.triagem_desenvolvedor import entrada as E

MAXIMO_MCP = 200  # a resposta do MCP vai inteira para o agente: lista curta; o arquivo grande vai pelo Actions


class TriarFazendas(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codigos_car: list[str] = Field(min_length=1, max_length=MAXIMO_MCP)


def ferramentas() -> list[dict]:
    return [
        {
            "name": "triar_fazendas",
            "description": "Ranking de fazendas (códigos do CAR) para um desenvolvedor de restauração: nota de 0 a "
            "100, "
            "crédito líquido P50 por ha, custo por crédito, TIR, caminho e risco da terra, embargo, TI/UC, "
            "desmatamento e alerta recentes, sobreposição com projetos e o motivo de cada nota. Sem dado de pessoas.",
            "inputSchema": TriarFazendas.model_json_schema(),
            "annotations": {"readOnlyHint": True, "openWorldHint": False},
        }
    ]


def triar_codigos(codigos: list[str], *, engine: Engine | None = None, pasta=None) -> dict:
    """A função única: usada pelo endpoint, pela ferramenta do MCP e pela CLI. Códigos inválidos viram contagem."""
    validos, invalidos = [], 0
    for c in codigos:
        n = E.normalizar(c)
        if n is None:
            invalidos += 1
        elif n not in validos:
            validos.append(n)
    if len(validos) > E.LIMITE:
        raise ValueError(f"lista com mais de {E.LIMITE} códigos: divida em partes")
    linhas = T.triar(validos, D.linhas(validos, pasta=pasta, engine=engine)) if validos else []
    return {"linhas": linhas, "resumo": T.resumo(linhas), "codigos_invalidos": invalidos}


def executar(
    engine: Engine,
    contexto,
    nome: str,
    argumentos: dict,
    *,
    autorizar: Callable[[Engine, object, str, tuple[str, ...]], AbstractContextManager],
) -> dict:
    if nome != "triar_fazendas":
        raise LookupError("Ferramenta não encontrada.")
    if getattr(contexto, "via", None) != "mcp" or type(getattr(contexto, "cliente_id", None)) is not int:
        raise PermissionError("A ferramenta exige o contexto OAuth corporativo autenticado pelo host MCP.")
    try:
        pedido = TriarFazendas.model_validate(argumentos)
    except ValidationError as ex:
        raise ValueError("Argumentos inválidos para a ferramenta.") from ex
    with autorizar(engine, contexto, nome, tuple(pedido.codigos_car)):
        dado = triar_codigos(pedido.codigos_car, engine=engine)
    return {
        "content": [{"type": "text", "text": json.dumps(dado, ensure_ascii=False, allow_nan=False, default=str)}],
        "structuredContent": json.loads(json.dumps(dado, allow_nan=False, default=str)),
        "isError": False,
    }
