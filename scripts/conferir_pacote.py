"""Barra scpi/vegan no pacote e na resolução distribuível, mesmo com exceção GPL no servidor."""

import argparse
import ast
import re
import tomllib
from email.parser import BytesParser
from pathlib import Path
from zipfile import ZipFile

from packaging.requirements import Requirement

PROIBIDOS = {"scpi", "scpi-pkg", "vegan"}


def nome(valor):
    return re.sub(r"[-_.]+", "-", valor).lower()


def conferir(lock: dict, wheel: Path) -> None:
    pacotes = {}
    for p in lock["package"]:
        pacotes.setdefault(nome(p["name"]), []).append(p)
    with ZipFile(wheel) as z:
        metadados = [p for p in z.namelist() if p.endswith(".dist-info/METADATA")]
        if len(metadados) != 1:
            raise ValueError("metadados do pacote ausentes ou ambíguos")
        m = BytesParser().parsebytes(z.read(metadados[0]))
        fila = [nome(Requirement(x).name) for x in m.get_all("Requires-Dist", [])]
        if not fila:
            raise ValueError("inventário de dependências vazio")
        visitados = set()
        while fila:
            atual = fila.pop()
            if atual in visitados:
                continue
            visitados.add(atual)
            if atual in PROIBIDOS:
                raise ValueError("scpi/vegan proibido no pacote distribuível")
            if atual not in pacotes:
                raise ValueError("dependência distribuível sem resolução no lock")
            # Inclui todos os extras, plataformas e versões possíveis; não confia no ambiente instalado.
            for p in pacotes[atual]:
                deps = list(p.get("dependencies", []))
                for xs in p.get("optional-dependencies", {}).values():
                    deps.extend(xs)
                fila.extend(nome(x["name"]) for x in deps)
        for caminho in z.namelist():
            if any(nome(parte.split(".")[0]) in PROIBIDOS for parte in Path(caminho).parts):
                raise ValueError("scpi/vegan copiado para o pacote")
            if caminho.endswith(".py"):
                arvore = ast.parse(z.read(caminho))
                for no in ast.walk(arvore):
                    nomes = [x.name for x in no.names] if isinstance(no, ast.Import) else []
                    if isinstance(no, ast.ImportFrom) and no.module:
                        nomes.append(no.module)
                    if any(nome(x.split(".")[0]) in PROIBIDOS for x in nomes):
                        raise ValueError("importação GPL proibida no pacote")
                    if any(x.split(".")[0] == "imblearn" for x in nomes) and caminho != "raiz/avaliacao/treino.py":
                        raise ValueError("imbalanced-learn fora do módulo de treino")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("wheel", type=Path)
    p.add_argument("--lock", type=Path, default=Path("uv.lock"))
    args = p.parse_args(argv)
    try:
        conferir(tomllib.loads(args.lock.read_text()), args.wheel)
    except (ValueError, KeyError, OSError):
        print("Pacote reprovado: inventário ou conteúdo distribuível inválido.")
        return 1
    print("Pacote conferido: scpi/vegan ausentes; reamostragem restrita ao treino.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
