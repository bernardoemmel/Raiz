"""Cliente Streamable HTTP para ensaios locais; falha fechada se não há servidor MCP.

Não implementa ferramentas nem executa instruções recebidas: somente JSON-RPC, inventário
real e chamadas explicitamente autorizadas pelo manifesto do teste.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import time
from typing import Any

import requests

from testes.carga.contrato import exigir_local, retry_after_valido


class ErroMCP(RuntimeError):
    """Mensagem estável: não inclui texto/credencial devolvido pelo servidor."""

    def __init__(
        self, mensagem: str, *, codigo: str = "mcp_invalido", status: int | None = None, motivo: str = "outro"
    ):
        super().__init__(mensagem)
        self.codigo = codigo if codigo in CODIGOS_DIAGNOSTICO else "mcp_invalido"
        self.status = status if type(status) is int and 100 <= status <= 599 else None
        self.motivo = motivo if motivo in MOTIVOS_DIAGNOSTICO else "outro"

    def diagnostico(self) -> dict:
        return {"codigo": self.codigo, "status": self.status, "motivo": self.motivo}


CODIGOS_DIAGNOSTICO = {
    "mcp_invalido",
    "http_inesperado",
    "jsonrpc_invalido",
    "ferramenta_reprovada",
    "prazo",
    "transporte",
    "retry_after_invalido",
    "limite_inesperado",
    "erro_inesperado",
}
MOTIVOS_DIAGNOSTICO = {
    "outro",
    "ficha_indisponivel",
    "idempotencia_conflito",
    "cancelamento_ocupado",
    "falha_interna",
    "limite",
    "limite_indisponivel",
    "prazo_excedido",
    "sem_credencial",
    "escopo_insuficiente",
}


def _problema_ferramenta(resultado: dict) -> dict:
    """Projeta apenas status e motivo de lista fechada; nunca retorna texto remoto."""
    for bloco in (resultado.get("content") or [])[:16]:
        texto = bloco.get("text") if isinstance(bloco, dict) else None
        if not isinstance(texto, str) or len(texto) > 16384:
            continue
        # O SDK pode prefixar "Error executing tool ..." ao Problem Details.
        inicio = texto.find("{")
        if inicio < 0:
            continue
        try:
            dado, _ = json.JSONDecoder().raw_decode(texto[inicio:])
        except ValueError:
            continue
        if not isinstance(dado, dict):
            continue
        prefixo = "https://github.com/bernardoemmel/Raiz/blob/main/docs/agentes-ia.md#erro-"
        tipo = dado.get("type")
        motivo = tipo.removeprefix(prefixo) if isinstance(tipo, str) and tipo.startswith(prefixo) else "outro"
        status = dado.get("status")
        return {
            "status": status if type(status) is int and 100 <= status <= 599 else None,
            "motivo": motivo if motivo in MOTIVOS_DIAGNOSTICO else "outro",
        }
    return {}


class LimiteMCP(ErroMCP):
    def __init__(self, espera: str | None):
        self.espera = espera
        super().__init__("MCP respondeu 429")


def decodificar(resposta, identificador: int, inicio: float | None = None) -> dict:
    """Consome só até a resposta SSE: o servidor pode manter o stream aberto."""
    inicio = inicio or time.monotonic()
    sse = resposta.headers.get("Content-Type", "").split(";")[0] == "text/event-stream"
    corpo = bytearray()
    linha = bytearray()
    evento: list[str] = []
    dado = None
    for bloco in resposta.iter_content(chunk_size=1):
        if time.monotonic() - inicio >= 5:
            raise ErroMCP("MCP demorou 5 segundos ou mais")
        corpo.extend(bloco)
        if len(corpo) > 8 * 1024 * 1024:
            raise ErroMCP("MCP excedeu limite de resposta do ensaio")
        if not sse:
            continue
        linha.extend(bloco)
        if not linha.endswith(b"\n"):
            continue
        texto = linha.decode("utf-8").rstrip("\r\n")
        linha.clear()
        if texto.startswith("data:"):
            evento.append(texto[5:].lstrip())
        elif not texto and evento:
            candidato = json.loads("\n".join(evento))
            evento.clear()
            if isinstance(candidato, dict) and candidato.get("id") == identificador:
                dado = candidato
                break
    if not sse:
        dado = json.loads(corpo)
    if not isinstance(dado, dict) or dado.get("jsonrpc") != "2.0" or dado.get("id") != identificador:
        raise ErroMCP("MCP respondeu identificador ou versão inválidos")
    if "error" in dado or not isinstance(dado.get("result"), dict):
        raise ErroMCP("MCP devolveu erro JSON-RPC ou resultado inválido", codigo="jsonrpc_invalido")
    return dado["result"]


class ClienteMCP:
    def __init__(self, url: str, token: str, sessao: requests.Session | None = None):
        exigir_local(url)
        if not token:
            raise ErroMCP("MCP de teste precisa de token OAuth descartável explícito")
        self.url = url
        self.sessao = sessao or requests.Session()
        self.cabecalhos = {"Authorization": "Bearer " + token, "Accept": "application/json, text/event-stream"}
        self.identificadores = itertools.count(1)
        self.iniciado = False
        self.protocolo = os.environ.get("RAIZ_MCP_TESTE_PROTOCOLO", "2025-06-18")
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", self.protocolo):
            raise ErroMCP("Versão de protocolo MCP inválida")

    def _enviar(self, metodo: str, params: dict, notificar: bool = False) -> dict:
        identificador = next(self.identificadores)
        cabecalhos = dict(self.cabecalhos)
        if self.protocolo == "2026-07-28":
            # MCP v2 stateless: versão/capabilities acompanham cada requisição.
            params = {
                **params,
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": self.protocolo,
                    "io.modelcontextprotocol/clientCapabilities": {},
                },
            }
            cabecalhos.update({"MCP-Protocol-Version": self.protocolo, "MCP-Method": metodo})
            if metodo == "tools/call":
                cabecalhos["MCP-Name"] = params["name"]
        corpo: dict[str, Any] = {"jsonrpc": "2.0", "method": metodo, "params": params}
        if not notificar:
            corpo["id"] = identificador
        inicio = time.monotonic()
        resposta = None
        try:
            resposta = self.sessao.post(
                self.url, json=corpo, headers=cabecalhos, timeout=4.9, allow_redirects=False, stream=True
            )
            if time.monotonic() - inicio >= 5:
                raise ErroMCP("MCP demorou 5 segundos ou mais", codigo="prazo")
            if resposta.status_code == 429:
                espera = resposta.headers.get("Retry-After")
                if not retry_after_valido(espera):
                    raise ErroMCP("MCP respondeu 429 sem Retry-After válido", codigo="retry_after_invalido", status=429)
                raise LimiteMCP(espera)
            if notificar:
                if resposta.status_code not in {200, 202, 204}:
                    raise ErroMCP("MCP recusou notificação initialized")
                return {}
            if resposta.status_code != 200:
                raise ErroMCP(
                    "MCP respondeu status HTTP inesperado", codigo="http_inesperado", status=resposta.status_code
                )
            if sessao := resposta.headers.get("Mcp-Session-Id"):
                self.cabecalhos["Mcp-Session-Id"] = sessao
            return decodificar(resposta, identificador, inicio)
        except (requests.RequestException, ValueError):
            raise ErroMCP("MCP não concluiu a chamada HTTP/JSON válida em menos de 5 s", codigo="transporte") from None
        finally:
            if resposta is not None:
                resposta.close()

    def inicializar(self) -> None:
        if self.protocolo == "2026-07-28":
            dado = self._enviar("server/discover", {})
            if self.protocolo not in dado.get("supportedVersions", []):
                raise ErroMCP("MCP não oferece a versão solicitada pelo ensaio")
            self.iniciado = True
            return
        dado = self._enviar(
            "initialize",
            {
                "protocolVersion": self.protocolo,
                "capabilities": {},
                "clientInfo": {"name": "raiz-qualidade", "version": "1"},
            },
        )
        if dado.get("protocolVersion") != self.protocolo:
            raise ErroMCP("MCP negociou versão não suportada pelo ensaio")
        self.cabecalhos["MCP-Protocol-Version"] = dado["protocolVersion"]
        self._enviar("notifications/initialized", {}, notificar=True)
        self.iniciado = True

    def listar_ferramentas(self) -> dict[str, dict]:
        if not self.iniciado:
            raise ErroMCP("Inicialize a sessão MCP antes de listar ferramentas")
        ferramentas = {}
        cursor = None
        cursores = set()
        for _ in range(100):
            dado = self._enviar("tools/list", {"cursor": cursor} if cursor else {})
            if not isinstance(dado.get("tools"), list):
                raise ErroMCP("MCP não devolveu inventário de ferramentas")
            for ferramenta in dado["tools"]:
                nome = ferramenta.get("name") if isinstance(ferramenta, dict) else None
                if not isinstance(nome, str) or not nome or nome in ferramentas:
                    raise ErroMCP("MCP devolveu nome inválido ou duplicado de ferramenta")
                ferramentas[nome] = ferramenta
            cursor = dado.get("nextCursor")
            if not cursor:
                if not ferramentas:
                    raise ErroMCP("MCP sem ferramentas: não há cobertura para aprovar")
                return ferramentas
            if not isinstance(cursor, str) or cursor in cursores:
                raise ErroMCP("MCP devolveu cursor inválido ou repetido")
            cursores.add(cursor)
        raise ErroMCP("MCP excedeu limite de paginação do inventário")

    def chamar(self, nome: str, argumentos: dict) -> dict:
        if not self.iniciado:
            raise ErroMCP("Inicialize a sessão MCP antes de chamar ferramentas")
        resultado = self._enviar("tools/call", {"name": nome, "arguments": argumentos})
        if resultado.get("isError"):
            raise ErroMCP(
                "Ferramenta MCP devolveu isError", codigo="ferramenta_reprovada", **_problema_ferramenta(resultado)
            )
        if not isinstance(resultado.get("content"), list):
            raise ErroMCP("Ferramenta MCP não devolveu content")
        return resultado

    def fechar(self) -> None:
        self.sessao.close()
