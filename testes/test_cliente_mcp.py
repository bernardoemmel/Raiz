"""Transporte do ensaio, com HTTP local; não substitui o teste do MCP do produto."""

import contextlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from testes.mcp.cliente import ClienteMCP, ErroMCP, LimiteMCP


@contextlib.contextmanager
def servidor(*, modo="json", status=200, espera="2", erro=False, protocolo="2025-06-18"):
    chamadas = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            dado = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            chamadas.append((dado["method"], self.headers.get("Mcp-Session-Id")))
            if protocolo == "2026-07-28":
                assert self.headers["MCP-Protocol-Version"] == protocolo
                assert self.headers["MCP-Method"] == dado["method"]
                assert dado["params"]["_meta"] == {
                    "io.modelcontextprotocol/protocolVersion": protocolo,
                    "io.modelcontextprotocol/clientCapabilities": {},
                }
                if dado["method"] == "tools/call":
                    assert self.headers["MCP-Name"] == dado["params"]["name"]
                else:
                    assert "MCP-Name" not in self.headers
            if "id" not in dado:
                self.send_response(202)
                self.end_headers()
                return
            resultado = {
                "server/discover": {"supportedVersions": ["2026-07-28"]},
                "initialize": {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {}},
                "tools/list": {"tools": [{"name": "consultar", "inputSchema": {"type": "object"}}]},
                "tools/call": {"content": [{"type": "text", "text": "resultado"}], "isError": erro},
            }[dado["method"]]
            corpo = json.dumps({"jsonrpc": "2.0", "id": dado["id"], "result": resultado}).encode()
            if modo == "sse":
                corpo = b": ping\r\n\r\ndata: " + corpo + b"\r\n\r\n"
            if modo == "id_invalido":
                corpo = b'{"jsonrpc":"2.0","id":999,"result":{}}'
            self.send_response(status)
            self.send_header("Content-Type", "text/event-stream" if modo == "sse" else "application/json")
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Mcp-Session-Id", "sessao-local-descartavel")
            if espera is not None:
                self.send_header("Retry-After", espera)
            self.end_headers()
            self.wfile.write(corpo)

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{http.server_port}/mcp", chamadas
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("modo", ["json", "sse"])
def test_mcp_negocia_sessao_lista_e_chama_pelo_http(modo):
    with servidor(modo=modo) as (url, chamadas):
        cliente = ClienteMCP(url, "token-local-descartavel")
        try:
            cliente.inicializar()
            assert set(cliente.listar_ferramentas()) == {"consultar"}
            assert cliente.chamar("consultar", {})["content"][0]["text"] == "resultado"
        finally:
            cliente.fechar()
    assert [metodo for metodo, _ in chamadas] == ["initialize", "notifications/initialized", "tools/list", "tools/call"]
    assert all(sessao == "sessao-local-descartavel" for _, sessao in chamadas[1:])


@pytest.mark.parametrize("espera", [None, "0", "61", "-1"])
def test_mcp_reprova_429_sem_retry_after_valido(espera):
    with servidor(status=429, espera=espera) as (url, _):
        cliente = ClienteMCP(url, "token-local-descartavel")
        with pytest.raises(ErroMCP, match="429 sem Retry-After"):
            cliente.inicializar()
        cliente.fechar()


def test_mcp_expoe_saturacao_valida_ao_locust():
    with servidor(status=429) as (url, _):
        cliente = ClienteMCP(url, "token-local-descartavel")
        with pytest.raises(LimiteMCP) as erro:
            cliente.inicializar()
        assert erro.value.espera == "2"
        cliente.fechar()


def test_mcp_reprova_resposta_de_outra_chamada():
    with servidor(modo="id_invalido") as (url, _):
        cliente = ClienteMCP(url, "token-local-descartavel")
        with pytest.raises(ErroMCP, match="identificador"):
            cliente.inicializar()
        cliente.fechar()


def test_mcp_nao_conta_erro_de_ferramenta_como_sucesso():
    with servidor(erro=True) as (url, _):
        cliente = ClienteMCP(url, "token-local-descartavel")
        cliente.inicializar()
        with pytest.raises(ErroMCP, match="isError"):
            cliente.chamar("consultar", {})
        cliente.fechar()


def test_mcp_nao_aceita_ensaio_anonimo():
    with pytest.raises(ErroMCP, match="token OAuth"):
        ClienteMCP("http://localhost:8765/mcp", "")


def test_mcp_v2_stateless_descobre_e_envia_metadados_em_todas_as_chamadas(monkeypatch):
    monkeypatch.setenv("RAIZ_MCP_TESTE_PROTOCOLO", "2026-07-28")
    with servidor(protocolo="2026-07-28") as (url, chamadas):
        cliente = ClienteMCP(url, "token-local-descartavel")
        try:
            cliente.inicializar()
            assert set(cliente.listar_ferramentas()) == {"consultar"}
            assert cliente.chamar("consultar", {})["content"]
            assert set(cliente.listar_ferramentas()) == {"consultar"}
        finally:
            cliente.fechar()
    assert [metodo for metodo, _ in chamadas] == ["server/discover", "tools/list", "tools/call", "tools/list"]
