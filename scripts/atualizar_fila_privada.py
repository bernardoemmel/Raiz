"""Atualiza refs pendentes do motor após instalar a publicação privada, sem perder pedidos.

Por padrão apenas mostra a mudança proposta. Cancelamentos e bloqueios anteriores
continuam bloqueados, salvo unidades escolhidas explicitamente com --retomar-unidade.
Reservas ativas não são alteradas. O modo --executar usa a transação CAS da fila.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "motor"))
import fila_processamento as F  # noqa: E402


def atualizar(estado: dict, ref: str, runs: dict, retomar: set[str]) -> dict:
    """Reconcilia só fins confirmados; conserva parâmetros, IDs e contagem de falhas."""
    F.reconciliar(estado, runs, lambda u: bool(re.fullmatch(r"[A-Z]{2}(?:-\d+)?", u)))
    atualizados, retomados = [], []
    for pedido in estado["fila"]:
        if pedido.get("ref") != ref:
            pedido["ref_anterior_privacidade"] = pedido.get("ref")
            pedido["ref"] = ref
            atualizados.append(pedido["id"])
        if pedido["unidade"] in retomar and pedido.get("bloqueado"):
            pedido["bloqueio_anterior_privacidade"] = pedido.pop("bloqueado")
            pedido["falhas_anteriores_privacidade"] = pedido.get("falhas", 0)
            pedido["falhas"] = 0
            retomados.append(pedido["id"])
    return {"refs_atualizadas": atualizados, "pedidos_retomados": retomados, "reservas_ativas": len(estado["reservas"])}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", required=True, help="SHA completo do commit protegido que já passou no CI")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "bernardoemmel/Raiz"))
    parser.add_argument(
        "--retomar-unidade", action="append", default=[], help="retomar explicitamente unidade bloqueada"
    )
    parser.add_argument("--executar", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.ref):
        raise ValueError("--ref deve ser um SHA completo")
    if any(not re.fullmatch(r"[A-Z]{2}(?:-\d+)?", u) for u in args.retomar_unidade):
        raise ValueError("unidade inválida")
    # Confere que não se está apontando a fila novamente para código legado.
    F.comando(["git", "show", f"{args.ref}:raiz/executor/transferencia_privada.py"])
    contrato = F.comando(["git", "show", f"{args.ref}:raiz/executor/publicacao_aberta.py"])
    if 'ESCOPO = "publico_basico"' not in contrato:
        raise ValueError("commit não contém o contrato de publicação mínima")
    repo = F.Repositorio()

    def mudar(estado):
        adicionais = set(estado["planejadores"]) | {r["run_id"] for r in estado["reservas"]}
        runs = F.rodadas(args.repo, "processar-estados.yml", adicionais)
        return atualizar(estado, args.ref, runs, set(args.retomar_unidade))

    if args.executar:
        resultado = F.transacao(repo, mudar)
    else:
        _, estado = repo.ler()
        resultado = mudar(copy.deepcopy(estado))
    print(json.dumps({"executado": args.executar, **resultado}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
