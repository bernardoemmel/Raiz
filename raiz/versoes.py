"""Versões gravadas em cada rodada e em cada previsão: do motor, das regras e das entradas."""

from __future__ import annotations

import hashlib
import subprocess
from functools import lru_cache
from pathlib import Path

from raiz import MOTOR_DIR, RAIZ_REPO


def sha256_arquivo(caminho: str | Path, bloco: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        while b := f.read(bloco):
            h.update(b)
    return h.hexdigest()


def sha256_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


@lru_cache
def motor_hash() -> str:
    """sha256 do código do motor (scripts e exportações do Earth Engine), independente de git."""
    h = hashlib.sha256()
    for p in sorted(MOTOR_DIR.rglob("*")):
        if p.is_file() and p.suffix in {".py", ".sh", ".js"} and "__pycache__" not in p.parts:
            h.update(str(p.relative_to(MOTOR_DIR)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def motor_versao() -> str:
    return f"motor-{motor_hash()[:12]}"


def motor_commit() -> str | None:
    try:
        r = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", "motor"],
            cwd=RAIZ_REPO,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def regras_versao() -> str:
    """Enquanto a tabela de parâmetros legais (E2 passo 1) não existe, as regras moram no código do motor."""
    return f"regras-no-motor-{motor_hash()[:12]}"
