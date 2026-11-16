"""Gera contratos JSON Schema fechados; --conferir reprova divergência no CI."""

import argparse
import json
from pathlib import Path

from raiz import RAIZ_REPO
from raiz.avaliacao.contratos import ControleEstavel, FunilFixo, GabaritoCego, PlanoMudanca
from raiz.avaliacao.mudanca import Ensaio

CONTRATOS = {
    "ensaio": Ensaio,
    "plano-mudanca": PlanoMudanca,
    "gabarito-cego": GabaritoCego,
    "controle-estavel": ControleEstavel,
    "funil-denominador-fixo": FunilFixo,
}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--conferir", action="store_true")
    p.add_argument("--destino", type=Path, default=RAIZ_REPO / "docs/esquemas/avaliacao")
    args = p.parse_args(argv)
    for nome, modelo in CONTRATOS.items():
        texto = json.dumps(modelo.model_json_schema(), indent=2, ensure_ascii=False) + "\n"
        arquivo = args.destino / f"{nome}.json"
        if args.conferir:
            if not arquivo.is_file() or arquivo.read_text() != texto:
                return 1
        else:
            args.destino.mkdir(parents=True, exist_ok=True)
            arquivo.write_text(texto)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
