"""Observabilidade sem dados pessoais, inclusive chamadas recusadas."""

import asyncio
from types import SimpleNamespace

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from raiz.publica.telemetria import TelemetriaMiddleware, chamada


@pytest.fixture
def coletor():
    provider = TracerProvider()
    exportador = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exportador))
    yield provider.get_tracer("teste-raiz"), exportador
    provider.shutdown()


def test_span_ferramenta_nao_registra_excecao_ou_atributo_livre(coletor):
    tracer, exportador = coletor
    with pytest.raises(ValueError), chamada("preparar_reserva", "mcp", 12, tracer=tracer):
        raise ValueError("segredo de pessoa jamais pode entrar no span")
    span = exportador.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.ERROR
    assert not span.events
    assert dict(span.attributes) == {"raiz.ferramenta": "preparar_reserva", "raiz.via": "mcp", "raiz.cliente_id": 12}
    assert span.status.description is None


@pytest.mark.parametrize("status", [200, 401, 403, 429, 500])
def test_http_registra_recusas_sem_corpo_cabecalhos_ou_caminho_livre(coletor, status):
    tracer, exportador = coletor

    async def app(scope, receive, send):
        scope["route"] = SimpleNamespace(path="/pedidos/{pedido_id}")
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b"resposta privada"})

    async def receive():
        raise AssertionError("middleware não deve ler o corpo")

    mensagens = []

    async def send(message):
        mensagens.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/pedidos/segredo",
        "query_string": b"token=segredo",
        "headers": [(b"authorization", b"Bearer segredo"), (b"baggage", b"cpf=segredo")],
        "state": {"cliente_id": 42},
    }
    asyncio.run(TelemetriaMiddleware(app, tracer=tracer)(scope, receive, send))
    span = exportador.get_finished_spans()[0]
    assert span.attributes["http.response.status_code"] == status
    assert span.attributes["raiz.acesso_negado"] == (status in {401, 403, 429})
    assert span.attributes["http.route"] == "/pedidos/{pedido_id}"
    assert "segredo" not in repr(dict(span.attributes))
    assert not span.events
    assert len(mensagens) == 2


def test_span_webhook_nao_captura_url_ou_falha_textual(coletor):
    from raiz.publica.telemetria import entrega_webhook

    tracer, exportador = coletor
    with pytest.raises(ValueError), entrega_webhook(18, 2, tracer=tracer):
        raise ValueError("https://segredo.example/credencial")
    span = exportador.get_finished_spans()[0]
    assert span.name == "raiz.webhook"
    assert dict(span.attributes) == {"raiz.cliente_id": 18, "raiz.tentativa": 2}
    assert span.status.status_code == StatusCode.ERROR
    assert not span.events and span.status.description is None
