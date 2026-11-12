"""O SDK real não exporta campos MCP livres nem exceções para OpenTelemetry."""

import contextlib
import json
from types import SimpleNamespace

import anyio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.server import MCPServer
from opentelemetry.trace import StatusCode

from raiz.publica import telemetria as O
from raiz.publica.servidor_mcp import ApiRaiz, app_http
from testes.test_publica_oauth import assinador, verificador  # noqa: F401
from testes.test_publica_telemetria import coletor  # noqa: F401


def test_substituicao_preserva_protecao_request_state_e_falha_fechada_em_sdk_novo(coletor, monkeypatch):  # noqa: F811
    tracer, _ = coletor
    mcp = MCPServer("teste")
    anteriores = list(mcp.middleware)
    assert any(type(item).__name__ == "RequestStateBoundary" for item in anteriores)
    O.instalar_telemetria_mcp(mcp, tracer=tracer)
    for antes, depois in zip(anteriores, mcp.middleware, strict=True):
        if type(antes).__name__ == "OpenTelemetryMiddleware":
            assert isinstance(depois, O.TelemetriaMCP)
        else:
            assert antes is depois
    monkeypatch.setattr(O, "version", lambda nome: "2.4.0")
    with pytest.raises(RuntimeError, match="revise a política"):
        O.instalar_telemetria_mcp(MCPServer("nao-inicia"))


def test_metodo_e_protocolo_livres_viram_enum_sem_reescrever_contexto(coletor):  # noqa: F811
    tracer, exportador = coletor
    ctx = SimpleNamespace(method="metodo-nao-autorizado", protocol_version="versao-nao-autorizada", params={})

    async def proximo(recebido):
        assert recebido is ctx
        return {}

    anyio.run(O.TelemetriaMCP(tracer=tracer), ctx, proximo)
    span = exportador.get_finished_spans()[0]
    assert span.name == "raiz.mcp.desconhecido"
    assert dict(span.attributes) == {"mcp.method.name": "desconhecido", "mcp.protocol.version": "desconhecida"}


def test_http_propaga_so_traceparent_sem_tracestate_ou_baggage(coletor):  # noqa: F811
    tracer, exportador = coletor

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def enviar(mensagem):
        pass

    scope = {
        "type": "http",
        "method": "GET",
        "headers": [
            (b"traceparent", b"00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"),
            (b"tracestate", b"vendor=texto-privado-de-terceiro"),
            (b"baggage", b"owner=texto-privado-de-terceiro"),
        ],
    }
    anyio.run(O.TelemetriaMiddleware(app, tracer=tracer), scope, None, enviar)
    span = exportador.get_finished_spans()[0]
    assert span.context.trace_id == int("0123456789abcdef0123456789abcdef", 16)
    assert not span.context.trace_state and "texto-privado" not in span.to_json()


def test_http_sdk_nao_exporta_nome_request_id_token_nem_texto_de_excecao(
    coletor,  # noqa: F811
    assinador,  # noqa: F811
    monkeypatch,
):
    from mcp.shared import _otel

    tracer, exportador = coletor
    # Captura também spans do SDK para detectar se o middleware inseguro ficar ativo por engano.
    monkeypatch.setattr(_otel, "_tracer", tracer)
    monkeypatch.setattr(O, "_tracer", lambda escolhido=None: escolhido or tracer)
    assinar, _ = assinador
    token = assinar()
    mcp, http = app_http(
        ApiRaiz(app=FastAPI()), hosts="api.raiz.example", verificador=verificador(assinador, monkeypatch)
    )
    segredo_nome = "ferramenta_nao_autorizada_00000000000"
    segredo_id = "request-id-nao-autorizado"
    segredo_excecao = "texto privado da excecao 00000000000"

    async def falha_controlada(ctx, proximo):
        if ctx.params and ctx.params.get("name") == "consultar_disponibilidade":
            raise RuntimeError(segredo_excecao)
        return await proximo(ctx)

    mcp.middleware.append(falha_controlada)

    @contextlib.asynccontextmanager
    async def vida(app):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(lifespan=vida)
    app.mount("/mcp", http)
    with TestClient(app, base_url="https://api.raiz.example") as cl:
        for nome in (segredo_nome, "consultar_disponibilidade"):
            r = cl.post(
                "/mcp/",
                headers={
                    "Authorization": f"Bearer {token}",
                    "MCP-Protocol-Version": "2026-07-28",
                    "MCP-Method": "tools/call",
                    "MCP-Name": nome,
                    "Accept": "application/json, text/event-stream",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": segredo_id,
                    "method": "tools/call",
                    "params": {
                        "name": nome,
                        "arguments": {"campos": {}, "idempotency_key": "consulta-telemetria"},
                        "_meta": {
                            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                            "io.modelcontextprotocol/clientCapabilities": {},
                            "baggage": token,
                        },
                    },
                },
            )
            assert r.status_code == 200
            assert "error" in r.json() or r.json().get("result", {}).get("isError")
    spans = exportador.get_finished_spans()
    assert len(spans) == 2
    serializados = json.dumps([json.loads(s.to_json()) for s in spans])
    for segredo in (segredo_nome, segredo_id, token, segredo_excecao):
        assert segredo not in serializados
    assert {s.attributes["gen_ai.tool.name"] for s in spans} == {"desconhecida", "consultar_disponibilidade"}
    for span in spans:
        assert span.status.status_code == StatusCode.ERROR
        assert not span.events and span.status.description is None
        assert span.attributes["gen_ai.operation.name"] == "execute_tool"
        assert span.attributes["mcp.protocol.version"] == "2026-07-28"
