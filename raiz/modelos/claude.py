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
from raiz.privacidade import mascarar

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
            except anthropic.RateLimitError as ex:
                return Resposta(None, self.nome, self.provedor, erro=f"limite de uso: {mascarar(str(ex))[:200]}")
            except anthropic.APIStatusError as ex:
                return Resposta(None, self.nome, self.provedor, erro=f"API {ex.status_code}: {mascarar(str(ex))[:200]}")
            except anthropic.APIConnectionError as ex:
                return Resposta(None, self.nome, self.provedor, erro=f"conexão: {mascarar(str(ex))[:200]}")
        u = r.usage
        uso = Uso(
            entrada=u.input_tokens or 0,
            saida=u.output_tokens or 0,
            cache_leitura=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_escrita=getattr(u, "cache_creation_input_tokens", 0) or 0,
        )
        modelo = getattr(r, "model", None) or self.nome
        valor, fonte = custo(uso, modelo, self.provedor)
        base = dict(modelo=modelo, provedor=self.provedor, uso=uso, custo_usd=valor, custo_fonte=fonte, duracao_ms=t.ms)
        if r.stop_reason == "refusal":
            det = getattr(r, "stop_details", None)
            cat = getattr(det, "category", None) if det else None
            return Resposta(None, recusou=True, erro=f"recusa ({cat or 'sem categoria'})", **base)
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
            return Resposta(None, erro=f"fora do esquema: {err}", **base)
        return Resposta(dados, **base)
