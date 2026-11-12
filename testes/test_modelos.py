"""Interface de modelos. Nada aqui chama a API de verdade: o SDK da Anthropic e o llama.cpp falam com transportes
HTTP falsos, o que confere o corpo exato que seria enviado."""

import json
from decimal import Decimal

import anthropic
import httpx
import httpx2
import pytest
from sqlalchemy import create_engine, text

from raiz.modelos import Claude, LlamaCpp, Pedido, chamar
from raiz.modelos.base import valida_esquema
from raiz.modelos.custo import custo

ESQUEMA = {
    "type": "object",
    "properties": {
        "intencao": {"type": "string", "enum": ["aceita", "recusa", "duvida"]},
        "confianca": {"type": "number"},
    },
    "required": ["intencao", "confianca"],
    "additionalProperties": False,
}
PEDIDO = Pedido("aceite.classificar", "Classifique a resposta do dono.", "Pode sim, aceito.", ESQUEMA,
                cod_imovel="PA-1504950-X", cod_municipio=1504950)  # fmt: skip


def _resposta_anthropic(modelo, dados=None, stop="end_turn", categoria=None):
    corpo = {
        "id": "msg_1", "type": "message", "role": "assistant", "model": modelo, "stop_reason": stop,
        "stop_sequence": None,
        "content": [{"type": "text", "text": json.dumps(dados)}] if dados is not None else [],
        "usage": {"input_tokens": 120, "output_tokens": 20, "cache_read_input_tokens": 0,
                  "cache_creation_input_tokens": 0},
    }  # fmt: skip
    if stop == "refusal":
        corpo["stop_details"] = {"type": "refusal", "category": categoria, "explanation": "x"}
    return corpo


def _cliente(responder):
    enviados = []

    def handler(req):
        enviados.append((req.url.path, req.headers, json.loads(req.content)))
        return httpx2.Response(200, json=responder(json.loads(req.content)))

    c = anthropic.Anthropic(api_key="teste", http_client=anthropic.DefaultHttpxClient(
        transport=httpx2.MockTransport(handler)), max_retries=0)  # fmt: skip
    return c, enviados


def test_sonnet_usa_saida_estruturada_e_reserva():
    c, enviados = _cliente(lambda b: _resposta_anthropic(b["model"], {"intencao": "aceita", "confianca": 0.9}))
    r = Claude("claude-sonnet-5-5", cliente=c).responder_json(PEDIDO)
    assert r.ok and r.dados["intencao"] == "aceita"
    _, headers, corpo = enviados[0]
    assert corpo["output_config"]["format"] == {"type": "json_schema", "schema": ESQUEMA}
    assert corpo["output_config"]["effort"] == "medium"
    assert corpo["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in headers["anthropic-beta"]
    assert r.custo_fonte == "genai-prices" and r.custo_usd == Decimal("120") * 2 / 10**6 + Decimal("20") * 10 / 10**6


def test_haiku_sem_reserva_e_esforco_baixo():
    c, enviados = _cliente(lambda b: _resposta_anthropic(b["model"], {"intencao": "duvida", "confianca": 0.4}))
    r = Claude("claude-haiku-5-5", cliente=c).responder_json(PEDIDO)
    assert r.ok
    _, headers, corpo = enviados[0]
    assert "fallbacks" not in corpo and "server-side-fallback" not in headers.get("anthropic-beta", "")
    assert corpo["output_config"]["effort"] == "low"


def test_recusa_e_fora_do_esquema():
    c, _ = _cliente(lambda b: _resposta_anthropic(b["model"], stop="refusal", categoria="general_harms"))
    r = Claude("claude-haiku-5-5", cliente=c).responder_json(PEDIDO)
    assert r.recusou and not r.ok and "general_harms" in r.erro
    c, _ = _cliente(lambda b: _resposta_anthropic(b["model"], {"intencao": "talvez", "confianca": 1}))
    r = Claude("claude-haiku-5-5", cliente=c).responder_json(PEDIDO)
    assert not r.ok and "fora da lista" in r.erro


def test_custo_pelo_modelo_que_respondeu():
    # com reserva, a resposta pode vir de outro modelo: o custo é o dele
    c, _ = _cliente(lambda b: _resposta_anthropic("claude-sonnet-5", {"intencao": "aceita", "confianca": 1.0}))
    r = Claude("claude-sonnet-5-5", cliente=c).responder_json(PEDIDO)
    assert r.modelo == "claude-sonnet-5" and r.custo_usd is not None


def test_llama_cpp_pede_gramatica_json():
    enviados = []

    def handler(req):
        enviados.append(json.loads(req.content))
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"intencao": "aceita", "confianca": 0.8}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 90, "completion_tokens": 12}})  # fmt: skip

    m = LlamaCpp("http://llama:8080", "qwen3-4b-instruct-2507", httpx.Client(transport=httpx.MockTransport(handler)))
    r = m.responder_json(PEDIDO)
    assert r.ok and r.custo_usd == 0 and r.custo_fonte == "local" and r.uso.entrada == 90
    rf = enviados[0]["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["schema"] == ESQUEMA
    assert enviados[0]["temperature"] == 0


def test_llama_cpp_fora_do_ar():
    def handler(req):
        raise httpx.ConnectError("recusado")

    r = LlamaCpp("http://llama:8080", "q", httpx.Client(transport=httpx.MockTransport(handler))).responder_json(PEDIDO)
    assert not r.ok and "llama.cpp" in r.erro


def test_valida_esquema():
    assert valida_esquema({"intencao": "aceita", "confianca": 1}, ESQUEMA) is None
    assert "falta" in valida_esquema({"intencao": "aceita"}, ESQUEMA)
    assert "a mais" in valida_esquema({"intencao": "aceita", "confianca": 1, "x": 1}, ESQUEMA)


def test_custo_sem_preco():
    from raiz.modelos.base import Uso

    assert custo(Uso(10, 10), "modelo-que-nao-existe", "anthropic") == (None, "sem_preco")


@pytest.mark.banco
def test_chamar_grava_custo_por_fazenda(banco_url):
    c, _ = _cliente(lambda b: _resposta_anthropic(b["model"], {"intencao": "aceita", "confianca": 0.9}))
    eng = create_engine(banco_url)
    with eng.begin() as con:
        con.execute(text("truncate operacao.chamada_modelo"))
        chamar(Claude("claude-haiku-5-5", cliente=c), PEDIDO, papel="B", con=con)
        r = con.execute(text("select * from operacao.chamada_modelo")).one()
        assert (r.tarefa, r.cod_imovel, r.papel, r.ok, r.tokens_entrada) == ("aceite.classificar", "PA-1504950-X", "B",
                                                                             True, 120)  # fmt: skip
        assert r.custo_usd > 0 and r.custo_fonte == "genai-prices"
    eng.dispose()


def test_rastro_mascara_e_esconde_pessoal(monkeypatch):
    from raiz.modelos import rastro
    from testes.test_privacidade import CPF, fmt_cpf

    assert CPF not in json.dumps(rastro._mascara(data={"m": [f"cpf {fmt_cpf(CPF)}"]}))

    registros = []

    class Obs:
        def __init__(self, **kw):
            registros.append(("abre", kw))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def update(self, **kw):
            registros.append(("fecha", kw))

    class LF:
        def start_as_current_observation(self, **kw):
            return Obs(**kw)

        def get_current_trace_id(self):
            return "trace-1"

    monkeypatch.setattr(rastro, "cliente_langfuse", lambda: LF())
    c, _ = _cliente(lambda b: _resposta_anthropic(b["model"], {"intencao": "aceita", "confianca": 0.9}))
    pessoal = Pedido("aceite.conversa", "s", "meu telefone é ...", ESQUEMA, cod_imovel="PA-X", pessoal=True)
    chamar(Claude("claude-haiku-5-5", cliente=c), pessoal, papel="A")
    abre, fecha = registros[0][1], registros[1][1]
    assert abre["as_type"] == "generation" and "não enviado" in abre["input"]
    assert "não enviado" in fecha["output"] and fecha["usage_details"]["input"] == 120
    assert fecha["cost_details"]["total"] > 0
