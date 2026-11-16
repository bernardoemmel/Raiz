"""O processamento real da fila cria um span sem registrar o corpo recebido."""

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from raiz.publica import telemetria
from raiz.publica import trabalhos as T
from testes.test_publica_trabalhos import empresa as empresa
from testes.test_publica_trabalhos import eng as eng

pytestmark = pytest.mark.banco


def test_worker_registra_ferramenta_e_empresa_sem_payload(eng, empresa, monkeypatch):
    provider = TracerProvider()
    exportador = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exportador))
    tracer = provider.get_tracer("teste-worker")
    monkeypatch.setattr(
        T, "chamada", lambda ferramenta, via, cliente: telemetria.chamada(ferramenta, via, cliente, tracer=tracer)
    )
    monkeypatch.setattr(T.S, "base_disponivel", lambda *args: {"fazendas": 2})
    T.submeter(eng, empresa, "consultar_disponibilidade", {}, "worker-otel-1")
    assert T.executar_proximo(eng)["estado"] == "completed"
    spans = exportador.get_finished_spans()
    assert len(spans) == 1
    assert dict(spans[0].attributes) == {
        "raiz.ferramenta": "consultar_disponibilidade",
        "raiz.via": "worker",
        "raiz.cliente_id": empresa,
    }
    assert not spans[0].events
    provider.shutdown()
