"""Rastros no Langfuse (instância própria): uma geração por chamada de modelo, com custo, tokens, tarefa e fazenda.

- session_id = código do CAR: o Langfuse soma o custo por fazenda; a tarefa vai nas tags.
- Todo texto passa pela máscara de CPF/CNPJ; pedido marcado como pessoal não manda entrada nem saída.
- Sem chaves do Langfuse configuradas, nada é enviado (os custos continuam em operacao.chamada_modelo).
"""

from __future__ import annotations

import contextlib
import logging
from functools import lru_cache
from typing import Any

from raiz.config import config
from raiz.modelos.base import Pedido, Resposta
from raiz.privacidade import mascarar

log = logging.getLogger(__name__)


def _mascara(*, data: Any, **_: Any) -> Any:
    if isinstance(data, str):
        return mascarar(data)
    if isinstance(data, dict):
        return {k: _mascara(data=v) for k, v in data.items()}
    if isinstance(data, list | tuple):
        return [_mascara(data=v) for v in data]
    return data


@lru_cache
def cliente_langfuse():
    cfg = config()
    if not (cfg.langfuse_public_key and cfg.langfuse_secret_key):
        return None
    from langfuse import Langfuse

    return Langfuse(
        public_key=cfg.langfuse_public_key.get_secret_value(),
        secret_key=cfg.langfuse_secret_key.get_secret_value(),
        host=cfg.langfuse_host,
        mask=_mascara,
    )


@contextlib.contextmanager
def contexto(pedido: Pedido, nome: str, tipo: str = "chain"):
    """Abre um trecho no Langfuse (ex.: a cascata inteira) com a fazenda e a tarefa propagadas para os filhos."""
    lf = cliente_langfuse()
    if lf is None:
        yield None
        return
    from langfuse import propagate_attributes

    meta = {"tarefa": pedido.tarefa}
    if pedido.cod_municipio is not None:
        meta["cod_municipio"] = str(pedido.cod_municipio)
    with propagate_attributes(session_id=pedido.cod_imovel, metadata=meta, tags=[pedido.tarefa]):  # noqa: SIM117
        with lf.start_as_current_observation(name=nome, as_type=tipo) as obs:
            yield obs


@contextlib.contextmanager
def geracao(pedido: Pedido, modelo: str, papel: str):
    lf = cliente_langfuse()
    if lf is None:
        yield None
        return
    entrada = (
        "[dado pessoal: não enviado]" if pedido.pessoal else {"sistema": pedido.sistema, "mensagem": pedido.mensagem}
    )
    with lf.start_as_current_observation(
        name=f"{pedido.tarefa}:{papel}", as_type="generation", model=modelo, input=entrada, metadata={"papel": papel}
    ) as g:
        yield g


def fechar(g, pedido: Pedido, resp: Resposta) -> str | None:
    if g is None:
        return None
    try:
        g.update(
            output="[dado pessoal: não enviado]" if pedido.pessoal else resp.dados,
            model=resp.modelo,
            usage_details={
                "input": resp.uso.entrada,
                "output": resp.uso.saida,
                "cache_read_input_tokens": resp.uso.cache_leitura,
                "cache_creation_input_tokens": resp.uso.cache_escrita,
            },
            cost_details={"total": float(resp.custo_usd)} if resp.custo_usd is not None else None,
            level="ERROR" if resp.erro else ("WARNING" if resp.recusou else "DEFAULT"),
            status_message=resp.erro,
        )
        return cliente_langfuse().get_current_trace_id()
    except Exception as ex:  # noqa: BLE001 - rastro nunca derruba a tarefa
        log.warning("Langfuse falhou: %s", ex)
        return None
