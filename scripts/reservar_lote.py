"""Reserva capacidade do Lote na mesma fila CAS do motor, antes de qualquer cálculo.

As cotas cobrem toda a rodada: preparo, matriz, checkpoints e publicação. Um
rerun parcial sem cotas falha antes dos dados; a reexecução completa reserva de novo.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

MOTOR = Path(__file__).resolve().parents[1] / "motor"
sys.path.insert(0, str(MOTOR))
import fila_processamento as F  # noqa: E402
import rodar_estado as O  # noqa: E402

PREFIXO = "lote-pa-vaga-"


class SemVagaGlobal(RuntimeError):
    """Admissão consultada com sucesso, mas as quinze cotas estão ocupadas."""


def contexto() -> tuple[str, int]:
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_JOB") not in {
        "preparar",
        "calcular",
        "publicar",
    }:
        raise RuntimeError("reserva do Lote exige o job autorizado no Actions")
    ref = os.environ.get("GITHUB_WORKFLOW_REF", "").split("@", 1)[0].rsplit("/", 1)[-1]
    if ref not in F.WORKFLOWS_LOTE:
        raise RuntimeError("workflow do Lote não confirmado")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    tentativa = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    if not run_id.isdigit() or not tentativa.isdigit() or int(tentativa) < 1:
        raise RuntimeError("rodada e tentativa do Actions não confirmadas")
    return run_id, int(tentativa)


def cotas(estado: dict, run_id: str) -> list[dict]:
    reservas = [r for r in estado["reservas"] if r["run_id"] == run_id and r["unidade"].startswith(PREFIXO)]
    if len({r["unidade"] for r in reservas}) != len(reservas) or any(
        not re.fullmatch(r"lote-pa-vaga-(?:[0-9]|1[0-4])", r["unidade"])
        or r["pedido"].get("escopo") != "rodada"
        or r["pedido"].get("repetir") is not False
        for r in reservas
    ):
        raise RuntimeError("cotas do Lote inválidas; nenhum cálculo autorizado")
    return reservas


def reservar(maximo: int, aguardar_minutos: float = 0) -> int:
    run_id, _ = contexto()
    if os.environ["GITHUB_JOB"] != "preparar" or not 1 <= maximo <= F.TETO or not 0 <= aguardar_minutos <= 180:
        raise ValueError("a reserva inicial exige o preparo e limite entre 1 e 15")
    _, estado = F.Repositorio().ler()
    reservas = cotas(estado, run_id)
    prazo = time.monotonic() + aguardar_minutos * 60
    while not reservas:
        F.reservar(
            candidatos=[f"{PREFIXO}{i}" for i in range(maximo)],
            pedidos=[],
            refazer=(),
            e_unidade=O._e_unidade,
            limite=F.TETO,
            max_novos=maximo,
            consumir_fila=False,
            repetir=False,
            reserva_rodada=True,
        )
        _, estado = F.Repositorio().ler()
        reservas = cotas(estado, run_id)
        if not reservas:
            restante = prazo - time.monotonic()
            if restante <= 0:
                break
            print("Fila global cheia; aguardando término natural, sem cancelar workflows.", flush=True)
            time.sleep(min(30, restante))
    if not 1 <= len(reservas) <= maximo:
        raise SemVagaGlobal("sem vaga global para o Lote; aguarde término natural e reexecute o workflow completo")
    confirmar(len(reservas))
    return len(reservas)


def confirmar(esperadas: int) -> None:
    run_id, tentativa = contexto()

    def atualizar(estado):
        reservas = cotas(estado, run_id)
        if not 1 <= esperadas <= F.TETO or len(reservas) != esperadas:
            raise RuntimeError("Lote sem as cotas da rodada; reexecute o workflow completo antes do cálculo")
        if any(type(r["pedido"].get("tentativa")) is not int or r["pedido"]["tentativa"] > tentativa for r in reservas):
            raise RuntimeError("tentativa das cotas não confirmada; nenhum cálculo autorizado")
        for reserva in reservas:
            # Um snapshot antigo da API durante um rerun não pode liberar as
            # cotas da tentativa nova enquanto o cálculo já foi autorizado.
            reserva["pedido"]["tentativa"] = tentativa

    F.transacao(F.Repositorio(), atualizar)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modo = parser.add_mutually_exclusive_group(required=True)
    modo.add_argument("--reservar", type=int, metavar="MAXIMO")
    modo.add_argument("--confirmar", type=int, metavar="VAGAS")
    parser.add_argument("--aguardar-minutos", type=float, default=0)
    args = parser.parse_args()
    if args.reservar is not None:
        vagas = aguardar(args.reservar, args.aguardar_minutos)
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as saida:
            saida.write(f"vagas={vagas}\n")
        print(f"Lote com {vagas} cotas na fila global de 15; nenhum trabalho foi cancelado.")
    else:
        confirmar(args.confirmar)
        print("Cotas globais confirmadas antes de acessar os dados do Lote.")


def aguardar(maximo: int, minutos: float = 0) -> int:
    if not 0 <= minutos <= 240:
        raise ValueError("Espera deve ficar entre zero e 240 minutos.")
    prazo = time.monotonic() + minutos * 60
    while True:
        try:
            return reservar(maximo)
        except SemVagaGlobal:
            if time.monotonic() >= prazo:
                raise
            print("Quinze cotas ocupadas; aguardando conclusão natural, sem cancelar trabalhos.", flush=True)
            time.sleep(min(60, max(0, prazo - time.monotonic())))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as erro:
        # Mensagens de git/gh não são repetidas: podem conter respostas autenticadas.
        print(
            f"Admissão do Lote interrompida ({type(erro).__name__}); reexecute o workflow completo quando houver vaga.",
            file=sys.stderr,
        )
        sys.exit(1)
