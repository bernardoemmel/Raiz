"""Carga MCP real, acionada somente com servidor local e manifesto completo de casos.

Este arquivo não fornece o MCP do produto. A ausência do servidor, OAuth, inventário
ou casos reprovam o comando; nunca produz aprovação vazia.
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from pathlib import Path

from gevent import Timeout
from locust import User, between, events, task

from testes.carga.contrato import conferir_relatorio
from testes.mcp.cliente import ClienteMCP, ErroMCP, LimiteMCP

FASE = os.environ.get("RAIZ_CARGA_FASE", "normal")
CONTAGEM = Counter()
SUCESSOS = Counter()
MAX_MS = 0.0
CASOS: dict[str, dict] = {}
BASE: ClienteMCP | None = None


@events.init.add_listener
def preparar(environment, **_):
    global BASE, CASOS
    try:
        CASOS = json.loads(Path(os.environ["RAIZ_MCP_TESTE_CASOS"]).read_text())["ferramentas"]
        if not isinstance(CASOS, dict) or not CASOS:
            raise ValueError("manifesto sem ferramentas")
        if any(not isinstance(caso.get("argumentos"), dict) for caso in CASOS.values()):
            raise ValueError("manifesto sem argumentos explícitos")
        BASE = ClienteMCP(os.environ["RAIZ_MCP_TESTE_URL"], os.environ["RAIZ_MCP_TESTE_TOKEN"])
        BASE.inicializar()
        if set(BASE.listar_ferramentas()) != set(CASOS):
            raise ValueError("manifesto não cobre exatamente o inventário real")
    except (OSError, KeyError, TypeError, ValueError, ErroMCP) as ex:
        # Locust captura exceções ordinárias de listeners; SystemExit evita seguir sem cobertura.
        raise SystemExit("Carga MCP bloqueada: servidor OAuth local e manifesto completo são obrigatórios") from ex


@events.request.add_listener
def medir(response_time, exception, **_):
    global MAX_MS
    CONTAGEM["requisicoes"] += 1
    CONTAGEM["falhas"] += int(exception is not None)
    MAX_MS = max(MAX_MS, response_time)


@events.quitting.add_listener
def finalizar(environment, **_):
    dado = {"fase": FASE, **CONTAGEM, "sucessos": dict(SUCESSOS), "max_ms": MAX_MS}
    dado["erros"] = conferir_relatorio(dado, set(CASOS))
    if not CASOS:
        dado["erros"].append("MCP sem inventário real")
    Path(os.environ["RAIZ_CARGA_RELATORIO"]).write_text(json.dumps(dado, indent=2), encoding="utf-8")
    if dado["erros"]:
        environment.process_exit_code = 1
    if BASE:
        BASE.fechar()


class MCPUsuario(User):
    wait_time = between(0.03, 0.08)

    def on_start(self):
        if BASE is None:
            raise RuntimeError("Servidor MCP não inicializado")
        self.cliente = ClienteMCP(os.environ["RAIZ_MCP_TESTE_URL"], os.environ["RAIZ_MCP_TESTE_TOKEN"])
        # Sessão compartilhada admite chamadas paralelas no Streamable HTTP, IDs globais únicos.
        self.cliente.cabecalhos = dict(BASE.cabecalhos)
        self.cliente.identificadores = BASE.identificadores
        self.cliente.iniciado = True
        self.ferramentas = list(CASOS)
        self.posicao = 0

    @task
    def ferramenta(self):
        nome = self.ferramentas[self.posicao % len(self.ferramentas)]
        self.posicao += 1
        inicio = time.monotonic()
        erro = None
        try:
            with Timeout(4.9, ErroMCP("Ferramenta MCP excedeu prazo de 4,9 s")):
                self.cliente.chamar(nome, CASOS[nome]["argumentos"])
            SUCESSOS[nome] += 1
        except LimiteMCP:
            CONTAGEM["limitadas"] += 1
            if FASE != "limite":
                erro = ErroMCP("429 abaixo do orçamento configurado")
        except ErroMCP as ex:
            erro = ex
        finally:
            self.environment.events.request.fire(
                request_type="MCP",
                name=nome,
                response_time=(time.monotonic() - inicio) * 1000,
                response_length=0,
                exception=erro,
            )

    def on_stop(self):
        self.cliente.fechar()
