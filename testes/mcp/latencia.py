"""Medição serial de todas as ferramentas do MCP real, com prazo de parede estrito."""

from __future__ import annotations

import json
import signal
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from testes.mcp.cliente import ClienteMCP, ErroMCP


@contextmanager
def prazo_real(segundos: float = 5):
    """Interrompe inclusive uma conexão que entrega bytes sem encerrar o corpo.

    Este ensaio roda no Linux do CI, na thread principal. Um read-timeout HTTP
    sozinho é reiniciado quando chega outro byte e não limita o tempo total.
    """
    if not hasattr(signal, "setitimer") or threading.current_thread() is not threading.main_thread():
        raise ErroMCP("O ensaio estrito de latência exige Linux/POSIX e a thread principal")

    def expirou(_sinal, _quadro):
        raise ErroMCP("Ferramenta MCP não concluiu em menos de 5 segundos")

    anterior = signal.getsignal(signal.SIGALRM)
    temporizador = signal.getitimer(signal.ITIMER_REAL)
    if temporizador[0]:
        raise ErroMCP("Há outro temporizador ativo; execute o ensaio em processo separado")
    signal.signal(signal.SIGALRM, expirou)
    signal.setitimer(signal.ITIMER_REAL, segundos)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, anterior)


def carregar_manifesto(caminho: Path) -> dict[str, dict]:
    try:
        casos = json.loads(caminho.read_text(encoding="utf-8"))["ferramentas"]
        if not isinstance(casos, dict) or not casos:
            raise ValueError
        for nome, caso in casos.items():
            if not isinstance(nome, str) or not nome or not isinstance(caso, dict):
                raise ValueError
            if not isinstance(caso.get("argumentos"), dict):
                raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        raise ErroMCP("Manifesto de casos ausente, vazio ou inválido") from None
    return casos


def medir_latencia(cliente: ClienteMCP, casos: dict[str, dict]) -> dict:
    with prazo_real():
        cliente.inicializar()
    with prazo_real():
        inventario = cliente.listar_ferramentas()
    if not casos or set(inventario) != set(casos):
        raise ErroMCP("O manifesto deve cobrir exatamente todas as ferramentas publicadas")
    medicoes = []
    # Ordem explícita do manifesto preserva dependências, como criar antes de consultar.
    for nome, caso in casos.items():
        inicio = time.monotonic()
        with prazo_real():
            cliente.chamar(nome, caso["argumentos"])
        segundos = time.monotonic() - inicio
        if segundos >= 5:
            raise ErroMCP("Ferramenta MCP demorou 5 segundos ou mais")
        medicoes.append({"ferramenta": nome, "segundos": round(segundos, 6)})
    return {"integracao_mcp": True, "limite_segundos_exclusivo": 5, "medicoes": medicoes}
