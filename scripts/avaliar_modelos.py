"""Portão de avaliação privada. Nunca publica entrada, IDs ou mensagens de validação no log."""

import argparse
import json
from pathlib import Path

from raiz.avaliacao.contratos import PlanoMudanca
from raiz.avaliacao.integridade import conferir_plano_fixado, congelar, fixar_plano
from raiz.avaliacao.mudanca import Ensaio, avaliar


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("entrada", type=Path)
    p.add_argument("--arquivo-privado", type=Path, required=True)
    p.add_argument("--fixar-plano", action="store_true")
    args = p.parse_args(argv)
    try:
        if args.fixar_plano:
            plano = PlanoMudanca.model_validate_json(args.entrada.read_bytes())
            fixar_plano(args.arquivo_privado, plano)
            print(json.dumps({"plano_fixado": True}))
            return 0
        ensaio = Ensaio.model_validate_json(args.entrada.read_bytes())
        conferir_plano_fixado(args.arquivo_privado, ensaio.plano)
        resultado = avaliar(ensaio)
        # Guarda também candidato reprovado. Nenhuma versão é substituída.
        for valor in (ensaio.plano, list(ensaio.anteriores), list(ensaio.candidatas), ensaio, resultado):
            congelar(args.arquivo_privado, valor)
    except (ValueError, TypeError, KeyError, OSError):
        print(json.dumps({"aprovado": False, "motivo": "entrada_ou_arquivo_privado_invalido"}))
        return 1
    print(json.dumps({"aprovado": resultado["aprovado"], "acao": resultado["acao"]}))
    return 0 if resultado["aprovado"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
