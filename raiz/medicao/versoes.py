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
    """Versão nomeada das regras (E2 passo 7): 'regras-2026b+<hash dos parâmetros>' (raiz/regras/parametros/), que
    leva às duas datas de cada valor (vigência legal e quando a Raíz passou a usar) em regras.parametro. O motor usa os
    mesmos valores (testes/test_regras_parametros.py confere RL, escadinha e teto do 61-B contra o motor); a versão do
    código do motor vai à parte, em motor_versao. Sem a tabela, cai na versão antiga (as regras no código do motor)."""
    try:
        from raiz.regras import parametros

        return parametros().versao
    except Exception:  # noqa: BLE001
        return f"regras-no-motor-{motor_hash()[:12]}"
