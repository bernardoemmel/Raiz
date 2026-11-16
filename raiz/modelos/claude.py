"""Claude pela API da Anthropic, com saída estruturada (output_config.format) para devolver sempre o JSON do esquema.

- Sonnet 5.5 (conversa e documento) e Haiku 5.5 (triagem), escolhidos em raiz/config.py.
- Nos modelos que aceitam, a reserva do lado do servidor fica ligada (fallbacks="default"): se o classificador de
  segurança recusar, a própria API refaz o pedido num modelo de reserva. O Haiku 5.5 não tem essa reserva; recusa
  vira desacordo na cascata.
- Cache de prompt automático (cache_control no topo): nas tarefas em lote o prompt de sistema se repete.
"""

from __future__ import annotations

import json

import anthropic

from raiz.config import config
from raiz.modelos.base import Cronometro, Pedido, Resposta, Uso, valida_esquema
from raiz.modelos.custo import custo

# modelos com reserva do lado do servidor (beta server-side-fallback-2026-07-01, modo "default")
COM_RESERVA = {"claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-2", "claude-fable-5-1"}
BETA_RESERVA = "server-side-fallback-2026-07-01"

ESFORCO_PADRAO = {"claude-haiku-5-5": "low", "claude-sonnet-5-5": "medium"}


def cliente_padrao() -> anthropic.Anthropic:
    chave = config().anthropic_api_key
    # sem chave na configuração, o SDK procura sozinho (ANTHROPIC_API_KEY, perfil do `ant auth login`...)
    return anthropic.Anthropic(api_key=chave.get_secret_value()) if chave else anthropic.Anthropic()


class Claude:
    provedor = "anthropic"

    def __init__(
        self, modelo: str, esforco: str | None = None, cliente: anthropic.Anthropic | None = None, reserva: bool = True
    ):
        self.nome = modelo
        self.esforco = esforco or ESFORCO_PADRAO.get(modelo, "medium")
        self._cliente = cliente
        self.reserva = reserva and modelo in COM_RESERVA

    @property
    def cliente(self) -> anthropic.Anthropic:
        if self._cliente is None:
            self._cliente = cliente_padrao()
        return self._cliente

    def _parametros(self, pedido: Pedido) -> dict:
        return dict(
            model=self.nome,
            max_tokens=pedido.max_tokens,
            system=pedido.sistema,
            messages=[{"role": "user", "content": pedido.mensagem}],
            output_config={
                "format": {"type": "json_schema", "schema": pedido.esquema},
                "effort": pedido.esforco or self.esforco,
            },
            cache_control={"type": "ephemeral"},
        )

    def responder_json(self, pedido: Pedido) -> Resposta:
        with Cronometro() as t:
            try:
                if self.reserva:
                    r = self.cliente.beta.messages.create(
                        **self._parametros(pedido), betas=[BETA_RESERVA], fallbacks="default"
                    )
                else:
                    r = self.cliente.messages.create(**self._parametros(pedido))
            except anthropic.RateLimitError:
                return Resposta(
                    None, self.nome, self.provedor, erro="limite de uso da Anthropic (429)", uso_informado=False
                )
            except anthropic.APIStatusError as ex:
                return Resposta(
                    None, self.nome, self.provedor, erro=f"API Anthropic: HTTP {ex.status_code}", uso_informado=False
                )
            except TypeError as ex:  # o SDK levanta TypeError quando não acha credencial nenhuma
                if "authentication" not in str(ex).lower():
                    raise
                return Resposta(
                    None,
                    self.nome,
                    self.provedor,
                    erro="sem credencial da Anthropic: defina ANTHROPIC_API_KEY",
                    uso_informado=False,
                )
            except anthropic.APIConnectionError:
                return Resposta(
                    None, self.nome, self.provedor, erro="falha de conexão com a Anthropic", uso_informado=False
                )
        u = getattr(r, "usage", None)
        informado = u is not None and all(
            isinstance(getattr(u, campo, None), int)
            and not isinstance(getattr(u, campo), bool)
            and getattr(u, campo) >= 0
            for campo in ("input_tokens", "output_tokens")
        )
        uso = Uso(
            entrada=getattr(u, "input_tokens", 0) if informado else 0,
            saida=getattr(u, "output_tokens", 0) if informado else 0,
            cache_leitura=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_escrita=getattr(u, "cache_creation_input_tokens", 0) or 0,
        )
        modelo = getattr(r, "model", None) or self.nome
        valor, fonte = custo(uso, modelo, self.provedor) if informado else (None, "sem_uso")
        base = dict(
            modelo=modelo,
            provedor=self.provedor,
            uso=uso,
            custo_usd=valor,
            custo_fonte=fonte,
            duracao_ms=t.ms,
            uso_informado=informado,
        )
        if r.stop_reason == "refusal":
            return Resposta(None, recusou=True, erro="recusa do modelo", **base)
        if r.stop_reason == "max_tokens":
            return Resposta(None, erro="resposta cortada (max_tokens)", **base)
        texto = next((b.text for b in r.content if getattr(b, "type", None) == "text"), None)
        try:
            dados = json.loads(texto) if texto else None
        except json.JSONDecodeError:
            return Resposta(None, erro="JSON inválido", **base)
        if dados is None:
            return Resposta(None, erro="sem texto na resposta", **base)
        if err := valida_esquema(dados, pedido.esquema):
            return Resposta(None, erro="fora do esquema" if pedido.pessoal else f"fora do esquema: {err}", **base)
        return Resposta(dados, **base)
