"""Spans operacionais com atributos permitidos; nunca corpos, tokens ou dados pessoais."""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import urlsplit

from opentelemetry import trace
from opentelemetry.propagate import extract
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import SpanKind, Status, StatusCode

FERRAMENTAS = frozenset(
    {
        "consultar_disponibilidade",
        "pedir_lote",
        "comparar_lotes",
        "acompanhar_contato",
        "preparar_reserva",
        "cancelar",
    }
)
_PROVIDER: TracerProvider | None = None
_TRAVA = threading.Lock()


def configurar_telemetria(endpoint: str | None = None) -> TracerProvider:
    """Inicializa uma vez. RAIZ_OTEL_ENDPOINT é URL OTLP/HTTP completa, sem credenciais.

    O processo que encerra o serviço deve chamar provider.shutdown(). Sem endpoint,
    os spans continuam disponíveis ao SDK, mas não há exportação/armazenamento externo.
    """
    global _PROVIDER
    with _TRAVA:
        if _PROVIDER is not None:
            return _PROVIDER
        destino = endpoint if endpoint is not None else os.getenv("RAIZ_OTEL_ENDPOINT", "")
        provider = TracerProvider(resource=Resource({"service.name": "raiz-agentes"}))
        if destino:
            partes = urlsplit(destino)
            if partes.scheme not in {"http", "https"} or not partes.hostname or partes.username or partes.password:
                raise ValueError("endpoint de telemetria inválido")
            if partes.query or partes.fragment:
                raise ValueError("endpoint de telemetria não aceita parâmetros ou fragmento")
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=destino, timeout=3)))
        trace.set_tracer_provider(provider)
        _PROVIDER = provider
        return provider


def _tracer(tracer=None):
    return tracer or trace.get_tracer("raiz.publica", "1")


@contextmanager
def chamada(ferramenta: str, via: str, cliente_id: int | None = None, *, tracer=None) -> Iterator:
    """Somente nome de ferramenta, canal e ID interno da empresa entram no span."""
    nome = ferramenta if ferramenta in FERRAMENTAS else "desconhecida"
    atributos = {"raiz.ferramenta": nome, "raiz.via": via if via in {"api", "mcp", "worker"} else "desconhecida"}
    if isinstance(cliente_id, int) and not isinstance(cliente_id, bool) and cliente_id > 0:
        atributos["raiz.cliente_id"] = cliente_id
    with _tracer(tracer).start_as_current_span(
        f"raiz.ferramenta.{nome}",
        attributes=atributos,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except BaseException:
            span.set_status(Status(StatusCode.ERROR))
            raise


class TelemetriaMiddleware:
    """ASGI puro: mede inclusive 401/403/429 sem consumir corpo nem capturar exceções."""

    def __init__(self, app, *, tracer=None):
        self.app = app
        self.tracer = _tracer(tracer)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Sem baggage nem outros cabeçalhos que possam conter segredos/dados de terceiros.
        contexto = {
            k.decode("ascii"): v.decode("ascii", errors="ignore")
            for k, v in scope.get("headers", [])
            if k in {b"traceparent", b"tracestate"}
        }
        metodo = scope.get("method", "")
        if metodo not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
            metodo = "OUTRO"
        with self.tracer.start_as_current_span(
            "raiz.http",
            context=extract(contexto),
            kind=SpanKind.SERVER,
            attributes={"http.request.method": metodo},
            record_exception=False,
            set_status_on_exception=False,
        ) as span:

            async def enviar(message):
                if message["type"] == "http.response.start":
                    status = int(message["status"])
                    span.set_attribute("http.response.status_code", status)
                    span.set_attribute("raiz.acesso_negado", status in {401, 403, 429})
                    if status >= 500:
                        span.set_status(Status(StatusCode.ERROR))
                await send(message)

            try:
                await self.app(scope, receive, enviar)
            except BaseException:
                span.set_status(Status(StatusCode.ERROR))
                raise
            finally:
                # Template registrado pelo roteador, nunca scope['path'] nem query_string.
                rota = getattr(scope.get("route"), "path", None)
                if isinstance(rota, str) and len(rota) < 256:
                    span.set_attribute("http.route", rota)
                cliente = scope.get("state", {}).get("cliente_id")
                if isinstance(cliente, int) and not isinstance(cliente, bool) and cliente > 0:
                    span.set_attribute("raiz.cliente_id", cliente)
