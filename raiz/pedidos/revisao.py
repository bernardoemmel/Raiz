"""Identidade da revisão efetiva do lote para vincular cálculos derivados."""

from __future__ import annotations

import hashlib
import json


def revisao_lote(pedido_id: str, campos: dict, sugestao: dict, opcoes_disponiveis: list[dict]) -> str | None:
    """Inclui o registro imutável e seu conteúdo; permissões de ficha e geometrias não alteram o cálculo.

    Uma reserva de outra conta que retire uma fazenda também invalida o derivado,
    mesmo antes de a vigia gravar outra sugestão. Sem sugestão persistida não há revisão.
    """
    if sugestao.get("id") is None:
        return None
    entrada = {
        "pedido_id": str(pedido_id),
        "sugestao_id": str(sugestao["id"]),
        "campos": campos,
        "modelo": sugestao.get("premissas_versao"),
        "otimizador": sugestao.get("otimizador_versao"),
        "base": sugestao.get("base"),
        "opcoes": sugestao.get("opcoes"),
        "composicao_disponivel": [
            {"id": o["id"], "itens": [{"cod_imovel": i["cod_imovel"], "papel": i["papel"]} for i in o.get("itens", [])]}
            for o in opcoes_disponiveis
        ],
    }
    bruto = json.dumps(entrada, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(bruto.encode()).hexdigest()
