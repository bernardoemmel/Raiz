"""Locust (MIT), apenas destinos locais descartáveis e requisições com nomes estáveis."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

from locust import HttpUser, between, events, task

from testes.carga.contrato import ROTAS_API, conferir_relatorio, exigir_local, retry_after_valido

FASE = os.environ.get("RAIZ_CARGA_FASE", "normal")
CONTAGEM = Counter()
SUCESSOS = Counter()
MAX_MS = 0.0


@events.init.add_listener
def iniciar(environment, **_):
    exigir_local(environment.host or "")


@events.request.add_listener
def medir(response_time, exception, **_):
    global MAX_MS
    CONTAGEM["requisicoes"] += 1
    CONTAGEM["falhas"] += int(exception is not None)
    MAX_MS = max(MAX_MS, response_time)


@events.quitting.add_listener
def finalizar(environment, **_):
    dado = {"fase": FASE, **CONTAGEM, "sucessos": dict(SUCESSOS), "max_ms": MAX_MS}
    dado["erros"] = conferir_relatorio(dado, set(ROTAS_API))
    Path(os.environ["RAIZ_CARGA_RELATORIO"]).write_text(json.dumps(dado, indent=2), encoding="utf-8")
    if dado["erros"]:
        environment.process_exit_code = 1


class APIUsuario(HttpUser):
    wait_time = between(0.03, 0.08)

    def on_start(self):
        exigir_local(self.host)
        self.client.headers["Authorization"] = "Bearer " + os.environ["RAIZ_CARGA_TOKEN"]
        self.posicao = 0

    @task
    def consultar(self):
        # Todos os usuários percorrem todas as rotas; evita cobertura dependente do sorteio.
        caminho = ROTAS_API[self.posicao % len(ROTAS_API)]
        self.posicao += 1
        with self.client.get(caminho, name=caminho, catch_response=True, timeout=4.9) as resposta:
            if resposta.status_code == 429:
                CONTAGEM["limitadas"] += 1
                if not retry_after_valido(resposta.headers.get("Retry-After")):
                    CONTAGEM["retry_after_invalidos"] += 1
                    resposta.failure("429 sem Retry-After válido")
                elif FASE != "limite":
                    resposta.failure("429 abaixo do orçamento configurado")
                else:
                    resposta.success()
                return
            if resposta.status_code != 200:
                resposta.failure("status HTTP inesperado")
                return
            try:
                dado = resposta.json()
                valido = dado.get("ok") is True if caminho == "/saude" else isinstance(dado, list) and bool(dado)
            except (ValueError, AttributeError):
                valido = False
            if not valido:
                resposta.failure("conteúdo não atende ao contrato da API")
                return
            SUCESSOS[caminho] += 1
            resposta.success()
