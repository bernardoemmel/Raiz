"""Custo de cada chamada com os preços do genai-prices (MIT). Modelo local custa zero em API (o custo de máquina
entra no orçamento do servidor). Modelo sem preço conhecido fica marcado 'sem_preco' para o backoffice cobrar."""

from __future__ import annotations

import logging
from decimal import Decimal

from genai_prices import Usage, calc_price

from raiz.modelos.base import Uso

log = logging.getLogger(__name__)


def custo(uso: Uso, modelo: str, provedor: str) -> tuple[Decimal | None, str]:
    if provedor == "local":
        return Decimal(0), "local"
    try:
        # o genai-prices conta o cache dentro do total de entrada; a Anthropic informa separado
        total = uso.entrada + uso.cache_leitura + uso.cache_escrita
        u = Usage(input_tokens=total, output_tokens=uso.saida, cache_read_tokens=uso.cache_leitura,
                  cache_write_tokens=uso.cache_escrita)  # fmt: skip
        return Decimal(str(calc_price(u, model_ref=modelo, provider_id=provedor).total_price)), "genai-prices"
    except (LookupError, ValueError) as ex:
        log.warning("sem preço para %s/%s: %s", provedor, modelo, ex)
        return None, "sem_preco"
