"""Spans operacionais com atributos permitidos; nunca corpos, tokens ou dados pessoais."""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.metadata import version
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
METODOS_MCP = frozenset(
    {
        "initialize",
        "server/discover",
        "ping",
        "tools/list",
        "tools/call",
        "resources/list",
        "resources/read",
        "resources/templates/list",
        "prompts/list",
        "prompts/get",
        "completion/complete",
        "notifications/initialized",
        "notifications/cancelled",
        "notifications/progress",
        "notifications/roots/list_changed",
    }
)


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


class TelemetriaMCP:
    """Mede mensagens MCP com enums fechados; não exporta parâmetros, ID JSON-RPC ou exceção."""

    def __init__(self, *, tracer=None):
        self.tracer = _tracer(tracer)

    async def __call__(self, ctx, call_next):
        from mcp.types import CallToolResult

        metodo = ctx.method if ctx.method in METODOS_MCP else "desconhecido"
        atributos = {
            "mcp.method.name": metodo,
            "mcp.protocol.version": "2026-07-28" if ctx.protocol_version == "2026-07-28" else "desconhecida",
        }
        if metodo == "tools/call":
            nome = ctx.params.get("name") if ctx.params else None
            atributos["gen_ai.operation.name"] = "execute_tool"
            atributos["gen_ai.tool.name"] = nome if isinstance(nome, str) and nome in FERRAMENTAS else "desconhecida"
        with self.tracer.start_as_current_span(
            f"raiz.mcp.{metodo}",
            kind=SpanKind.SERVER,
            attributes=atributos,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                resultado = await call_next(ctx)
            except BaseException:
                span.set_status(Status(StatusCode.ERROR))
                raise
            if isinstance(resultado, CallToolResult) and resultado.is_error is True:
                span.set_status(Status(StatusCode.ERROR))
            elif isinstance(resultado, dict) and resultado.get("isError") is True:
                span.set_status(Status(StatusCode.ERROR))
            return resultado


def instalar_telemetria_mcp(mcp, *, tracer=None) -> None:
    """Troca só OTel na lista pública do SDK; preserva RequestStateBoundary e todas as demais proteções.

    O SDK 2.3.0 registra nomes/IDs livres e texto de exceção no middleware padrão.
    Uma atualização exige rever essa integração antes de abrir o servidor.
    """
    if version("mcp") != "2.3.0":
        raise RuntimeError("revise a política de telemetria antes de atualizar o SDK MCP")
    indices = [
        i
        for i, item in enumerate(mcp.middleware)
        if type(item).__name__ == "OpenTelemetryMiddleware" and type(item).__module__ == "mcp.server._otel"
    ]
    if len(indices) != 1:
        raise RuntimeError("middleware de telemetria MCP inesperado; servidor não iniciado")
    mcp.middleware[indices[0]] = TelemetriaMCP(tracer=tracer)


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


@contextmanager
def entrega_webhook(cliente_id: int, tentativa: int, *, tracer=None) -> Iterator:
    """Evento de saída sem URL, segredo, assinatura, payload ou resposta externa."""
    with _tracer(tracer).start_as_current_span(
        "raiz.webhook",
        kind=SpanKind.PRODUCER,
        attributes={"raiz.cliente_id": cliente_id, "raiz.tentativa": tentativa},
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
        # Só traceparent tem formato fechado validado pelo propagador. tracestate/baggage admitem texto livre.
        contexto = {
            k.decode("ascii"): v.decode("ascii", errors="ignore")
            for k, v in scope.get("headers", [])
            if k == b"traceparent"
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
