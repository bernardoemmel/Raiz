"""Agenda persistente da pilha; executa CLIs existentes sem duplicar regra de negócio.

Uma trava de arquivo impede duas agendas no mesmo volume. A marca só é persistida após sucesso: falhas são
repetidas no próximo ciclo, com intervalo de cinco minutos. Reinício não repete um horário concluído.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import fcntl
import json
import os
import signal
import subprocess
import time
from pathlib import Path
from zoneinfo import ZoneInfo

TAREFAS = {
    "alertas": (15, ("operacao", "alertas")),
    "pedidos": (60, ("pedidos", "ciclo")),
    "fichas": (15, ("prospeccao", "atualizar-base")),
    "buscas": (15, ("prospeccao", "verificar-buscas")),
    "calendario": (0, ("calendario", "coletar")),
}
SAUDE = Path("/tmp/raiz-agenda.saude")


def faixa(tarefa: str, agora: dt.datetime) -> str | None:
    """Identifica o horário devido; o calendário alcança a rodada diária após reinício."""
    minutos = TAREFAS[tarefa][0]
    if not minutos:
        return agora.date().isoformat() if (agora.hour, agora.minute) >= (6, 47) else None
    return f"{agora.date().isoformat()}-{(agora.hour * 60 + agora.minute) // minutos}"


def executar(tarefa: str, teste: bool = False) -> bool:
    if teste:
        # Mesmo agendador, sem coleta externa nem canais reais em um cenário descartável.
        return True
    try:
        resultado = subprocess.run(
            ["raiz", *TAREFAS[tarefa][1]],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=1800,
            check=False,
        )
        return resultado.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def rodar(uma: bool = False, pasta: Path = Path("dados/operacao/agenda")) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    estado_path = pasta / "estado.json"
    with (pasta / "agenda.lock").open("w") as trava:
        try:
            fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("já há uma agenda ativa neste volume") from None
        estado = json.loads(estado_path.read_text()) if estado_path.exists() else {}
        fuso = ZoneInfo(os.environ.get("RAIZ_AGENDA_FUSO", "America/Sao_Paulo"))
        teste = os.environ.get("RAIZ_AGENDA_MODO", "producao") == "teste"
        parar = False

        def encerrar(*_):
            nonlocal parar
            parar = True

        signal.signal(signal.SIGTERM, encerrar)
        signal.signal(signal.SIGINT, encerrar)
        ativos: dict[str, tuple[str, concurrent.futures.Future]] = {}
        repetir_apos: dict[str, float] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            while not parar:
                SAUDE.touch()
                for tarefa, (identificador, futuro) in list(ativos.items()):
                    if not futuro.done():
                        continue
                    ok = futuro.result()
                    if ok:
                        estado[tarefa] = identificador
                        temporario = estado_path.with_suffix(".tmp")
                        temporario.write_text(json.dumps(estado, sort_keys=True))
                        temporario.replace(estado_path)
                    else:
                        repetir_apos[tarefa] = time.monotonic() + 300
                    print(json.dumps({"tarefa": tarefa, "sucesso": ok, "modo": "teste" if teste else "producao"}))
                    del ativos[tarefa]
                agora = dt.datetime.now(fuso)
                for tarefa in TAREFAS:
                    identificador = faixa(tarefa, agora)
                    if (
                        identificador
                        and estado.get(tarefa) != identificador
                        and tarefa not in ativos
                        and time.monotonic() >= repetir_apos.get(tarefa, 0)
                    ):
                        ativos[tarefa] = (identificador, pool.submit(executar, tarefa, teste))
                if uma:
                    falhou = False
                    for tarefa, (identificador, futuro) in ativos.items():
                        if futuro.result():
                            estado[tarefa] = identificador
                        else:
                            falhou = True
                    temporario = estado_path.with_suffix(".tmp")
                    temporario.write_text(json.dumps(estado, sort_keys=True))
                    temporario.replace(estado_path)
                    if falhou:
                        raise SystemExit(1)
                    return
                time.sleep(1)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--saude", action="store_true")
    p.add_argument("--uma", action="store_true")
    a = p.parse_args()
    if a.saude:
        raise SystemExit(0 if SAUDE.exists() and time.time() - SAUDE.stat().st_mtime < 90 else 1)
    rodar(a.uma)


if __name__ == "__main__":
    main()
