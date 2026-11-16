"""Executa leitores no servidor, com teto real de memória, CPU, saída e tempo."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path


def executar(args: list[str], entrada: bytes | None, timeout: float, limite: int) -> bytes:
    # O wrapper aplica rlimits antes do exec; evita preexec_fn em workers com threads.
    env = {**os.environ, "OMP_THREAD_LIMIT": "1"}
    with subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("processo_worker.py")), *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    ) as processo:
        try:
            inicio, partes, tamanho, posicao = time.monotonic(), [], 0, 0
            entrada = entrada or b""
            with selectors.DefaultSelector() as seletor:
                for fluxo in (processo.stdin, processo.stdout):
                    os.set_blocking(fluxo.fileno(), False)
                seletor.register(processo.stdout, selectors.EVENT_READ)
                if entrada:
                    seletor.register(processo.stdin, selectors.EVENT_WRITE)
                else:
                    processo.stdin.close()
                while seletor.get_map():
                    restante = timeout - (time.monotonic() - inicio)
                    if restante <= 0:
                        raise ValueError("leitura excedeu o tempo permitido")
                    for chave, _ in seletor.select(min(restante, 0.2)):
                        if chave.fileobj is processo.stdin:
                            try:
                                posicao += os.write(chave.fd, entrada[posicao : posicao + 65536])
                            except BrokenPipeError:
                                posicao = len(entrada)
                            if posicao == len(entrada):
                                seletor.unregister(processo.stdin)
                                processo.stdin.close()
                        else:
                            bloco = os.read(chave.fd, 65536)
                            tamanho += len(bloco)
                            if tamanho > limite:
                                raise ValueError("leitura excedeu o limite de saída")
                            if bloco:
                                partes.append(bloco)
                            else:
                                seletor.unregister(processo.stdout)
                if processo.wait(timeout=max(0.01, timeout - (time.monotonic() - inicio))):
                    raise ValueError("leitor não concluiu dentro dos limites")
            return b"".join(partes)
        finally:
            if processo.poll() is None:
                os.killpg(processo.pid, signal.SIGKILL)
                processo.wait()
