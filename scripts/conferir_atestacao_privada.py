"""Recusa subjects pessoais/legados antes de chamar a atestação pública do Actions."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def conferir(caminho: Path) -> None:
    # Sem dependências do produto: também funciona após falha de instalação ou de um executor antigo.
    if caminho.stat().st_size > 256_000:
        raise ValueError("lista acima do limite")
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    if not 1 <= len(linhas) <= 1024:
        raise ValueError("quantidade inválida")
    for linha in linhas:
        if not re.fullmatch(r"([a-f0-9]{64})  privado-sha256-\1", linha):
            raise ValueError("subject privado não corresponde ao digest do conteúdo")


def main(argv: list[str] | None = None) -> int:
    argumentos = sys.argv[1:] if argv is None else argv
    try:
        if len(argumentos) != 1:
            raise ValueError("uso inválido")
        conferir(Path(argumentos[0]))
    except (OSError, ValueError, UnicodeError):
        print("::error::Atestação privada bloqueada: lista ausente, inválida ou com subject legado.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
