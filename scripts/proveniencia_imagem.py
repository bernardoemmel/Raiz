"""Registra hashes das fontes públicas copiadas para a imagem, sem ler variáveis de ambiente ou segredos."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

PASTAS = ("raiz", "scripts", "migracoes", "infra", "motor", "nativo")
ARQUIVOS = ("pyproject.toml", "uv.lock", "alembic.ini")
IGNORADOS = {
    ".git",
    ".venv",
    "__pycache__",
    "target",
    ".cache",
    "node_modules",
    "saida",
    "cache",
    "extras",
    "mapbiomas",
    "projetos_carbono",
}


def manifesto(raiz: Path) -> dict:
    caminhos = [raiz / nome for nome in ARQUIVOS]
    for nome in PASTAS:
        caminhos.extend((raiz / nome).rglob("*"))
    hashes = {}
    for caminho in sorted(caminhos):
        relativo = caminho.relative_to(raiz)
        if (
            any(parte in IGNORADOS for parte in relativo.parts)
            or relativo.parts[:2] == ("infra", "modelos")
            or not caminho.is_file()
            or caminho.is_symlink()
            or caminho.suffix in {".pyc", ".env", ".log", ".parquet", ".gpkg", ".zip"}
            or (caminho.name.startswith(".env") and caminho.name != ".env.example")
        ):
            continue
        hashes[relativo.as_posix()] = hashlib.sha256(caminho.read_bytes()).hexdigest()
    return {"versao": 1, "algoritmo": "sha256", "arquivos": hashes}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raiz", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--saida", type=Path, required=True)
    a = p.parse_args()
    a.saida.write_text(json.dumps(manifesto(a.raiz), sort_keys=True, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
