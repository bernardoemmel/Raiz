"""Adaptador de ferramentas da ficha, sem servidor ou transporte MCP próprio.

O host entrega o contexto corporativo autenticado por OAuth, compatível com
``publica.chaves.Acesso``. Sessão do navegador e chave REST não autenticam MCP.
O callback obrigatório do host aplica conta paga, sinal, contrato, limites
corporativos e auditoria; a releitura de ficha adquirida não cria nova tarifa.
O servidor oficial registra consultar_ficha pela ponte /v1; este adaptador
Python permanece disponível para hosts internos, sem transporte alternativo.
``ferramentas`` usa Tool; ``executar`` produz CallToolResult. O host converte
erros ao protocolo público e mantém seu envelope; o serviço só retorna terra.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Engine

from raiz import prospeccao_servico as servico
from raiz.prospeccao_acesso import ErroAcesso


class ContextoCorporativo(Protocol):
    cliente_id: int
    via: str
    escopos: frozenset[str]


class Consultar(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codigo_car: str = Field(min_length=3, max_length=80)


class Comparar(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codigos_car: list[str] = Field(min_length=2, max_length=5)


def ferramentas() -> list[dict]:
    return [
        {
            "name": "consultar_ficha",
            "description": "Consulta dados da terra de um CAR já liberado com crédito pago, com fontes e datas.",
            "inputSchema": Consultar.model_json_schema(),
            "annotations": {"readOnlyHint": True, "openWorldHint": False},
        },
        {
            "name": "comparar_fichas",
            "description": "Compara de duas a cinco fichas já liberadas para a empresa autenticada por OAuth.",
            "inputSchema": Comparar.model_json_schema(),
            "annotations": {"readOnlyHint": True, "openWorldHint": False},
        },
    ]


def executar(
    engine: Engine,
    contexto: ContextoCorporativo,
    nome: str,
    argumentos: dict,
    *,
    autorizar_detalhes: Callable[[Engine, ContextoCorporativo, str, tuple[str, ...]], AbstractContextManager],
) -> dict:
    """Só contexto OAuth do host; não libera ficha nem debita carteira por conta própria.

    ``autorizar_detalhes`` é a barreira corporativa do host, sem nova tarifa
    pela releitura já paga. Nunca fornecer um callback vazio em produção.
    """
    cliente_id = getattr(contexto, "cliente_id", None)
    if type(cliente_id) is not int or cliente_id < 1 or getattr(contexto, "via", None) != "mcp":
        raise ErroAcesso(401, "A ferramenta exige o contexto OAuth corporativo autenticado pelo host MCP.")
    escopos = getattr(contexto, "escopos", None)
    if not isinstance(escopos, (set, frozenset)) or "consultar" not in escopos:
        raise ErroAcesso(403, "A autorização corporativa não permite consultar fichas.")
    servico.limitar_consulta(engine, cliente_id)
    try:
        if nome == "consultar_ficha":
            consulta = Consultar.model_validate(argumentos)
            codigos = (consulta.codigo_car,)
        elif nome == "comparar_fichas":
            consulta = Comparar.model_validate(argumentos)
            codigos = tuple(consulta.codigos_car)
        else:
            raise ErroAcesso(404, "Ferramenta não encontrada.")
    except ValidationError as ex:
        raise ErroAcesso(422, "Argumentos inválidos para a ferramenta.") from ex
    with autorizar_detalhes(engine, contexto, nome, codigos):
        if nome == "consultar_ficha":
            dado = servico.consultar_ficha(engine, cliente_id, codigos[0], canal="mcp")
        else:
            dado = servico.comparar_fichas(engine, cliente_id, list(codigos), canal="mcp")
    return {
        "content": [{"type": "text", "text": json.dumps(dado, ensure_ascii=False, allow_nan=False)}],
        "structuredContent": dado,
        "isError": False,
    }
