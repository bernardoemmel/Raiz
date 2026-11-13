"""Interface única dos modelos de linguagem: todo modelo recebe um Pedido (com esquema JSON) e devolve uma Resposta
com os dados já validados pelo esquema, o uso de tokens e o custo. Quem chama não sabe se foi o Claude ou o Qwen."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol


@dataclass(frozen=True)
class Pedido:
    tarefa: str  # nome estável da tarefa (ex.: "aceite.classificar_resposta"): agrupa custo e acerto
    sistema: str
    mensagem: str
    esquema: dict  # JSON Schema da saída (objeto, com required e additionalProperties false)
    cod_imovel: str | None = None
    cod_municipio: int | None = None
    max_tokens: int = 2048
    esforco: str | None = None  # low | medium | high (Claude); ignorado no modelo local
    pessoal: bool = False  # a entrada ou a saída tem dado pessoal: não guardar respostas em claro
    ferramentas: int = 0  # chamadas de ferramenta que a tarefa faz; com alguma, a tarefa não vai ao modelo local


@dataclass
class Uso:
    entrada: int = 0  # tokens de entrada sem cache
    saida: int = 0
    cache_leitura: int = 0
    cache_escrita: int = 0


@dataclass
class Resposta:
    dados: dict | None
    modelo: str  # o modelo que respondeu de fato (pode ser o de reserva, se houve fallback)
    provedor: str
    uso: Uso = field(default_factory=Uso)
    custo_usd: Decimal | None = None
    custo_fonte: str = "sem_preco"  # genai-prices | local | sem_preco
    duracao_ms: int = 0
    recusou: bool = False
    erro: str | None = None
    confianca: float | None = None  # 0 a 1, dos logprobs do modelo local (o Claude não devolve logprobs)
    uso_informado: bool = True  # false quando a API não devolveu uso: zero tokens não é medição

    @property
    def ok(self) -> bool:
        return self.dados is not None and not self.recusou and self.erro is None


class Modelo(Protocol):
    nome: str
    provedor: str

    def responder_json(self, pedido: Pedido) -> Resposta: ...


class Cronometro:
    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *a):
        self.ms = int((time.perf_counter() - self.t0) * 1000)


def valida_esquema(dados: Any, esquema: dict) -> str | None:
    """Conferência mínima do JSON contra o esquema (tipos de topo, required, enum). Devolve o erro ou None.
    O Claude com saída estruturada e o llama.cpp com gramática já garantem o formato; isto pega o resto."""
    if esquema.get("type") == "object":
        if not isinstance(dados, dict):
            return "não é objeto"
        for k in esquema.get("required", []):
            if k not in dados:
                return f"falta {k}"
        props = esquema.get("properties", {})
        if esquema.get("additionalProperties") is False:
            extras = set(dados) - set(props)
            if extras:
                return f"campos a mais: {sorted(extras)}"
        tipos = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}
        for k, sub in props.items():
            if k not in dados or dados[k] is None:
                continue
            t = sub.get("type")
            if isinstance(t, str) and t in tipos and not isinstance(dados[k], tipos[t]):
                return f"{k} não é {t}"
            if "enum" in sub and dados[k] not in sub["enum"]:
                return f"{k} fora da lista: {dados[k]!r}"
    return None
