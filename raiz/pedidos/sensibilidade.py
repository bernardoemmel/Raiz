"""Grade privada do motor, sem interpolar o resumo central nem inventar cenários ausentes.

O produtor do cálculo entrega <pedido UUID>.json na pasta RAIZ_SENSIBILIDADE_DIRETORIO do servidor.
Esse arquivo nunca integra o site estático. A API confere autorização e propriedade antes desta leitura.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictBool, ValidationError, model_validator


class ParametrosSensibilidade(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preco_credito_usd: Annotated[FiniteFloat, Field(gt=0, le=1000)]
    reserva_reversao: Annotated[FiniteFloat, Field(ge=0.2, le=0.9)]
    taxa_desconto: Annotated[FiniteFloat, Field(ge=0, le=0.5)]
    pessimista: StrictBool


class Faixa(BaseModel):
    model_config = ConfigDict(extra="forbid")
    p10: Annotated[FiniteFloat, Field(ge=0)]
    p50: Annotated[FiniteFloat, Field(ge=0)]
    p90: Annotated[FiniteFloat, Field(ge=0)]

    @model_validator(mode="after")
    def ordenada(self):
        if not self.p10 <= self.p50 <= self.p90:
            raise ValueError("quantis de crédito fora de ordem")
        return self


class Opcao(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Literal["barata", "segura", "compacta"]
    creditos: Faixa
    hectares: Annotated[FiniteFloat, Field(ge=0)]
    fazendas: Annotated[int, Field(ge=0, strict=True)]
    vpl_usd: FiniteFloat | None
    tir_projeto: Annotated[FiniteFloat, Field(gt=-1)] | None
    alcanca_meta: StrictBool


class Cenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parametros: ParametrosSensibilidade
    opcoes: list[Opcao]

    @model_validator(mode="after")
    def tres_opcoes(self):
        if len(self.opcoes) != 3 or {o.id for o in self.opcoes} != {"barata", "segura", "compacta"}:
            raise ValueError("cada cenário exige as três opções completas")
        return self


class GradeSensibilidade(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pedido_id: uuid.UUID
    modelo_versao: Annotated[str, Field(min_length=1)]
    revisao_lote: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    atualizado_em: dt.datetime
    fonte: Annotated[str, Field(min_length=1)]
    aviso: Annotated[str, Field(min_length=1)]
    cenarios: list[Cenario]

    @model_validator(mode="after")
    def sem_ambiguidade(self):
        if self.atualizado_em.tzinfo is None:
            raise ValueError("a data de publicação precisa de fuso horário")
        parametros = [json.dumps(c.parametros.model_dump(), sort_keys=True) for c in self.cenarios]
        if len(parametros) != len(set(parametros)):
            raise ValueError("premissas duplicadas na grade")
        return self


def consultar(pedido: dict, parametros: ParametrosSensibilidade) -> dict:
    """Só lê grade do pedido e da mesma versão. Falha fechada; nunca devolve JSON bruto do arquivo."""
    resposta = {
        "estado": "indisponivel",
        "exemplo": False,
        "parametros": parametros.model_dump(),
        "fonte": "Lote e números, Release privado",
        "atualizado_em": None,
        "modelo_versao": None,
        "revisao_lote": pedido.get("revisao_lote"),
        "opcoes": [],
        "aviso": "A grade de sensibilidade dos três lotes ainda não está disponível. "
        "O cenário central do Pará não foi recalculado. São necessárias saídas do motor para estas premissas.",
    }
    pasta = os.environ.get("RAIZ_SENSIBILIDADE_DIRETORIO")
    if not pasta:
        return resposta
    try:
        pedido_id = uuid.UUID(str(pedido["id"]))
        arquivo = Path(pasta) / f"{pedido_id}.json"
        grade = GradeSensibilidade.model_validate_json(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, ValidationError):
        return resposta
    if (
        grade.pedido_id != pedido_id
        or grade.modelo_versao != pedido.get("versao_modelo")
        or grade.revisao_lote != pedido.get("revisao_lote")
    ):
        return resposta
    cenario = next((c for c in grade.cenarios if c.parametros == parametros), None)
    if cenario is None:
        return {
            **resposta,
            "modelo_versao": grade.modelo_versao,
            "atualizado_em": grade.atualizado_em.isoformat(),
            "aviso": "O motor ainda não publicou estas premissas em conjunto. "
            "A tela não interpola cenários nem recalcula o resumo central.",
        }
    return {
        **resposta,
        "estado": "disponivel",
        "fonte": grade.fonte,
        "modelo_versao": grade.modelo_versao,
        "atualizado_em": grade.atualizado_em.isoformat(),
        "aviso": grade.aviso,
        "opcoes": [o.model_dump() for o in cenario.opcoes],
    }
