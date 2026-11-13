"""Verificação da pilha real, sem modelo e sem produzir pontuação de agente."""

from __future__ import annotations

import asyncio
import json
import logging
import time

import httpx2
from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client

from raiz.publica.avaliacao import carregar_gabarito
from scripts.avaliacao_fixture import FixtureConfig, tentativa


def problema(resultado):
    texto = resultado.content[0].text
    return json.loads(texto[texto.index("{") :])


async def verificar():
    tarefas = {t.id: t for t in carregar_gabarito()[0].tarefas}
    cenarios = (
        "disponibilidade_pa",
        "saldo_insuficiente",
        "limite_empresa",
        "preparar_reserva_humana",
        "repeticao_idempotente",
        "cancelar_pedido_proprio",
    )
    with FixtureConfig.from_env() as config:
        for nome in cenarios:
            with tentativa(tarefas[nome], 1, config) as s:
                async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + s.token}, trust_env=False) as http:
                    async with Client(
                        streamable_http_client(s.mcp_url, http_client=http), mode="2026-07-28", cache=None
                    ) as mcp:
                        assert len((await mcp.list_tools()).tools) == 7
                        if nome in {"disponibilidade_pa", "limite_empresa"}:
                            s.preparar_chamada()
                            r = await mcp.call_tool("consultar_disponibilidade", {"campos": {"onde": {"ufs": ["PA"]}}})
                        elif nome in {"saldo_insuficiente", "repeticao_idempotente"}:
                            r = await mcp.call_tool(
                                "pedir_lote",
                                {
                                    "campos": s.contexto.get("corpo_original", {"onde": {"ufs": ["PA"]}}),
                                    "idempotency_key": s.contexto.get("idempotency_key", "ensaio-sem-saldo"),
                                },
                            )
                        elif nome == "preparar_reserva_humana":
                            r = await mcp.call_tool(
                                "preparar_reserva",
                                {"pedido_id": s.contexto["pedido_id"], "idempotency_key": "ensaio-reserva-humana"},
                            )
                        else:
                            r = await mcp.call_tool(
                                "cancelar", {"pedido_id": s.contexto["pedido_id"], "idempotency_key": "ensaio-cancelar"}
                            )
                        if nome in {"saldo_insuficiente", "limite_empresa"}:
                            assert r.is_error
                            esperado = {
                                "saldo_insuficiente": 402,
                                "limite_empresa": 429,
                                "cancelar_pedido_proprio": 409,
                            }[nome]
                            assert problema(r)["status"] == esperado
                        elif nome == "cancelar_pedido_proprio":
                            assert not r.is_error and r.structured_content["estado"] == "input-required"
                        else:
                            assert not r.is_error
                            pedido = r.structured_content["pedido_id"]
                            # Só no teste da pilha: a campanha exige que o próprio agente peça acompanhamento.
                            for _ in range(80):
                                r = await mcp.call_tool("acompanhar_contato", {"pedido_id": pedido})
                                assert not r.is_error
                                if r.structured_content["estado"] not in {"submitted", "working"}:
                                    break
                                await asyncio.sleep(0.25)
                            assert r.structured_content["estado"] in {"completed", "input-required"}
                            if nome == "preparar_reserva_humana":
                                assert r.structured_content["estado"] == "input-required"
                            if nome == "repeticao_idempotente":
                                assert pedido == s.contexto["pedido_id"]
                                assert len(s.evidencias()["lancamentos"]) == 1
                        efeitos = s.evidencias()
                        assert efeitos["cobrancas"] == efeitos["reservas_ativas"] == efeitos["contatos_externos"] == 0
                        print(nome + ": pilha conferida; sem pontuação de agente", flush=True)


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    inicio = time.monotonic()
    try:
        asyncio.run(verificar())
    except Exception:
        print("Verificação da pilha falhou; nenhum resultado de agente foi produzido.", flush=True)
        raise SystemExit(1) from None
    print(f"Pilha validada em {time.monotonic() - inicio:.1f}s; modelo não executado.")
