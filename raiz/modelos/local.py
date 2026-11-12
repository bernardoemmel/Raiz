"""Modelo local no llama.cpp (llama-server, MIT): Qwen3-4B-Instruct-2507 (Apache-2.0), roda em CPU.

O JSON sai por gramática: o servidor converte o JSON Schema do pedido numa gramática GBNF e só deixa o modelo gerar
texto que cabe nela (response_format json_schema). Temperatura 0 para o voto ser reprodutível.
Subir o servidor: ver infra/docker-compose.yml (serviço llama).
"""

from __future__ import annotations

import json

import httpx

from raiz.config import config
from raiz.modelos.base import Cronometro, Pedido, Resposta, Uso, valida_esquema
from raiz.modelos.custo import custo


class LlamaCpp:
    provedor = "local"

    def __init__(
        self,
        url: str | None = None,
        modelo: str | None = None,
        cliente: httpx.Client | None = None,
        timeout: float = 180.0,
    ):
        self.url = (url or config().llama_url).rstrip("/")
        self.nome = modelo or config().modelo_local
        self._cliente = cliente or httpx.Client(timeout=timeout)

    def corpo(self, pedido: Pedido) -> dict:
        return {
            "model": self.nome,
            "messages": [{"role": "system", "content": pedido.sistema}, {"role": "user", "content": pedido.mensagem}],
            "max_tokens": pedido.max_tokens,
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "saida", "strict": True, "schema": pedido.esquema},
            },
        }

    def responder_json(self, pedido: Pedido) -> Resposta:
        with Cronometro() as t:
            try:
                r = self._cliente.post(f"{self.url}/v1/chat/completions", json=self.corpo(pedido))
                r.raise_for_status()
                j = r.json()
            except (httpx.HTTPError, ValueError) as ex:
                return Resposta(None, self.nome, self.provedor, erro=f"llama.cpp: {str(ex)[:200]}")
        u = j.get("usage") or {}
        uso = Uso(entrada=u.get("prompt_tokens", 0), saida=u.get("completion_tokens", 0))
        valor, fonte = custo(uso, self.nome, self.provedor)
        base = dict(
            modelo=self.nome, provedor=self.provedor, uso=uso, custo_usd=valor, custo_fonte=fonte, duracao_ms=t.ms
        )
        try:
            escolha = j["choices"][0]
            if escolha.get("finish_reason") == "length":
                return Resposta(None, erro="resposta cortada (max_tokens)", **base)
            dados = json.loads(escolha["message"]["content"])
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as ex:
            return Resposta(None, erro=f"resposta ilegível: {ex}", **base)
        if err := valida_esquema(dados, pedido.esquema):
            return Resposta(None, erro=f"fora do esquema: {err}", **base)
        return Resposta(dados, **base)
