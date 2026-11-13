"""O provedor pode ecoar documento pessoal; falhas e uso ausente não viram métricas falsas."""

import time
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from raiz.documentos.claude import LeitorClaude


@pytest.mark.parametrize(
    "uso", [None, SimpleNamespace(input_tokens=3), SimpleNamespace(input_tokens=-1, output_tokens=2)]
)
def test_uso_ausente_ou_invalido_nao_e_custo_zero(uso):
    r = SimpleNamespace(
        usage=uso,
        model="claude-haiku-5-5",
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text='{"ok":true}')],
    )
    saida = LeitorClaude()._resposta(r, time.perf_counter())
    assert saida.ok and not saida.uso_informado
    assert saida.custo_usd is None


def test_zero_explicito_preserva_uso_informado():
    r = SimpleNamespace(
        usage=SimpleNamespace(input_tokens=0, output_tokens=0),
        model="claude-haiku-5-5",
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text='{"ok":true}')],
    )
    saida = LeitorClaude()._resposta(r, time.perf_counter())
    assert saida.uso_informado and saida.custo_usd == 0


def test_corpo_de_erro_nao_e_persistido_nem_logado(caplog):
    pessoal = "Nome pessoal e trecho privado da certidão"
    resposta = httpx.Response(400, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))

    def falhar(**kw):
        raise anthropic.BadRequestError(pessoal, response=resposta, body={"mensagem": pessoal})

    cliente = SimpleNamespace(messages=SimpleNamespace(stream=falhar))
    r = LeitorClaude(modelo="claude-haiku-5-5", cliente=cliente).ler_texto("pdf privado", "sistema", "pedido", {})
    assert r.erro == "pedido recusado pela API (400)"
    assert pessoal not in caplog.text and pessoal not in str(r)
    assert not r.uso_informado and r.custo_usd is None


def test_categoria_de_recusa_nao_ecoada():
    r = SimpleNamespace(
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        model="claude-haiku-5-5",
        stop_reason="refusal",
        stop_details=SimpleNamespace(category="texto pessoal do PDF"),
    )
    saida = LeitorClaude()._resposta(r, time.perf_counter())
    assert saida.recusou and saida.erro == "recusa do modelo"
    assert saida.uso_informado and saida.custo_usd is not None
