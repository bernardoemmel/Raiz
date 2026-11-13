"""Falha (código 1) se alguma dependência Python instalada, npm do front (front/globo, front/produtor) ou crate Rust
tiver licença proibida, GPL sem registro ou licença não declarada e não conferida.
Uso: uv run python scripts/checar_licencas.py"""

import sys
from pathlib import Path

from raiz import RAIZ_REPO
from raiz.licencas import avaliar, falhas, ler_registro, pacotes_cargo, pacotes_npm, pacotes_python


def main() -> int:
    registro = ler_registro(Path(__file__).with_name("licencas.toml"))
    cargo = pacotes_cargo(RAIZ_REPO / "nativo" / "raiz_iov" / "Cargo.toml")
    pastas = [RAIZ_REPO / "front" / app / "package-lock.json" for app in ("globo", "produtor")]
    pastas.append(RAIZ_REPO / "servicos" / "cartao" / "package-lock.json")  # Takumi (cartão e vídeo)
    pastas.append(RAIZ_REPO / "servicos" / "conferencia-agentes" / "package-lock.json")  # Inspector e vacuum
    npm = [p for lock in pastas for p in pacotes_npm(lock)]
    pacotes = avaliar(pacotes_python() + npm + cargo, registro)
    ruins = falhas(pacotes)
    avisos = [p for p in pacotes if p.situacao in {"lgpl", "gpl_servidor"}]
    for p in avisos:
        print(f"aviso  {p.origem:6} {p.nome} {p.versao}: {p.licenca} ({p.motivo})")
    for p in ruins:
        print(f"FALHA  {p.origem:6} {p.nome} {p.versao}: {p.licenca or '-'} ({p.motivo})")
    print(f"{len(pacotes)} pacotes conferidos, {len(ruins)} com problema.")
    return 1 if ruins else 0


if __name__ == "__main__":
    sys.exit(main())
