"""python -m raiz.estaduais coletar|recalcular|validar (sem mexer no raiz/cli.py, que é de todos os threads).

coletar     --saida PASTA [--ufs SP,MG]       coleta o catálogo das UFs (vazio = todas) sem dado pessoal
recalcular  --pasta SAIDA_DO_MOTOR --municipios 3106200,5208707 [--camadas PASTA]
validar                                       confere o catálogo e as regras (o CI roda isto nos testes)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m raiz.estaduais")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("coletar")
    c.add_argument("--saida", required=True)
    c.add_argument("--ufs", default="")
    r = sub.add_parser("recalcular")
    r.add_argument("--pasta", required=True)
    r.add_argument("--municipios", required=True)
    r.add_argument("--camadas", default=None)
    sub.add_parser("validar")
    a = p.parse_args(argv)

    from raiz.estaduais import coleta

    if a.cmd == "validar":
        erros = coleta.validar(coleta.catalogo())
        print("\n".join(erros) or f"catálogo ok: {len(coleta.catalogo())} fontes")
        return 1 if erros else 0
    if a.cmd == "coletar":
        ufs = [u.strip().upper() for u in a.ufs.split(",") if u.strip()] or None
        cob = coleta.coletar(Path(a.saida), ufs)
        for fid, info in sorted(cob["fontes"].items()):
            print(f"  {info.get('uf')} {fid}: {info.get('estado')} {info.get('feicoes', '')}")
        return 0
    from raiz.estaduais import cruzamento

    camadas = cruzamento.Camadas(Path(a.camadas) if a.camadas else None)
    for cod in [int(x) for x in a.municipios.split(",") if x.strip()]:
        df = cruzamento.escrever_municipio(Path(a.pasta), cod, camadas=camadas)
        print(cod, json.dumps(cruzamento.resumo(df), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
