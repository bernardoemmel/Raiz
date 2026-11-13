"""Carga MCP real, acionada somente com servidor local e manifesto completo de casos.

Este arquivo não fornece o MCP do produto. A ausência do servidor, OAuth, inventário
ou casos reprovam o comando; nunca produz aprovação vazia.
"""

from __future__ import annotations

import itertools
import json
import os
import time
from collections import Counter
from pathlib import Path

from gevent import Timeout
from locust import User, between, constant_pacing, events, task

from testes.carga.contrato import conferir_relatorio
from testes.mcp.cliente import ClienteMCP, ErroMCP, LimiteMCP

FASE = os.environ.get("RAIZ_CARGA_FASE", "normal")
CONTAGEM = Counter()
SUCESSOS = Counter()
MAX_MS = 0.0
ERROS = Counter()
USUARIOS = itertools.count()
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
    dado = {
        "fase": FASE,
        **CONTAGEM,
        "sucessos": dict(SUCESSOS),
        "max_ms": MAX_MS,
        "falhas_por_tipo": [
            {"ferramenta": ferramenta, "codigo": codigo, "status": status, "motivo": motivo, "quantidade": quantidade}
            for (ferramenta, codigo, status, motivo), quantidade in sorted(ERROS.items(), key=lambda item: str(item[0]))
        ],
    }
    dado["erros"] = conferir_relatorio(dado, set(CASOS))
    if not CASOS:
        dado["erros"].append("MCP sem inventário real")
    Path(os.environ["RAIZ_CARGA_RELATORIO"]).write_text(json.dumps(dado, indent=2), encoding="utf-8")
    if dado["erros"]:
        environment.process_exit_code = 1
    if BASE:
        BASE.fechar()


class MCPUsuario(User):
    # Seis usuários e oito ferramentas: ~23 fichas/min, abaixo da cota real 30/min.
    # A espera fica fora do cronômetro de resposta. Saturação mantém alta demanda.
    wait_time = constant_pacing(2) if FASE == "normal" else between(0.03, 0.08)

    def on_start(self):
        if BASE is None:
            raise RuntimeError("Servidor MCP não inicializado")
        self.cliente = ClienteMCP(os.environ["RAIZ_MCP_TESTE_URL"], os.environ["RAIZ_MCP_TESTE_TOKEN"])
        # Sessão compartilhada admite chamadas paralelas no Streamable HTTP, IDs globais únicos.
        self.cliente.cabecalhos = dict(BASE.cabecalhos)
        self.cliente.identificadores = BASE.identificadores
        self.cliente.iniciado = True
        self.ferramentas = list(CASOS)
        # Distribui cobertura desde o início, mesmo no ensaio curto de dez segundos.
        self.posicao = next(USUARIOS) % len(self.ferramentas)

    @task
    def ferramenta(self):
        nome = self.ferramentas[self.posicao % len(self.ferramentas)]
        self.posicao += 1
        inicio = time.monotonic()
        erro = None
        concluida = False
        try:
            with Timeout(4.9, ErroMCP("Ferramenta MCP excedeu prazo de 4,9 s", codigo="prazo")):
                self.cliente.chamar(nome, CASOS[nome]["argumentos"])
            SUCESSOS[nome] += 1
            concluida = True
        except LimiteMCP:
            CONTAGEM["limitadas"] += 1
            if FASE != "limite":
                erro = ErroMCP("429 abaixo do orçamento configurado", codigo="limite_inesperado", status=429)
            concluida = True
        except ErroMCP as ex:
            erro = ex
            concluida = True
        except Exception:
            erro = ErroMCP("Falha inesperada no transporte de carga MCP", codigo="erro_inesperado")
            concluida = True
        finally:
            if concluida:
                if erro is not None:
                    d = erro.diagnostico()
                    ERROS[(nome, d["codigo"], d["status"], d["motivo"])] += 1
                self.environment.events.request.fire(
                    request_type="MCP",
                    name=nome,
                    response_time=(time.monotonic() - inicio) * 1000,
                    response_length=0,
                    exception=erro,
                )
            else:
                # Locust encerra greenlets ao terminar o tempo; não houve resposta.
                CONTAGEM["interrompidas"] += 1

    def on_stop(self):
        self.cliente.fechar()
