"""Checksums dos uploads concluídos, para a atestação de procedência do Actions.

O Release é mutável: cada nome conserva o último digest enviado por este job,
separado por canal público ou privado. As listas contêm nomes e hashes, nunca os
dados. A assinatura OIDC é feita pelo actions/attest, nunca pelo processo Python.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def registrar(nome: str, dados: bytes, *, privado: bool = False) -> None:
    """Registra somente depois do upload bem-sucedido; sem RUNNER_TEMP, não grava."""
    temporaria = os.environ.get("RUNNER_TEMP")
    if not temporaria:
        return
    if not nome or any(c in nome for c in "\r\n\x00\\/") or nome in {".", ".."}:
        raise ValueError("nome de arquivo inválido para a atestação")
    import fcntl

    pasta = Path(temporaria)
    pasta.mkdir(parents=True, exist_ok=True)
    base = "atestar-privado" if privado else "atestar"
    destino = pasta / f"{base}.txt"
    with (pasta / f"{base}.lock").open("a") as trava:
        fcntl.flock(trava, fcntl.LOCK_EX)
        checksums = {}
        if destino.exists():
            for linha in destino.read_text(encoding="utf-8").splitlines():
                digest, arquivo = linha.split("  ", 1)
                checksums[arquivo] = digest
        checksums[nome] = hashlib.sha256(dados).hexdigest()
        if len(checksums) > 1024:
            raise ValueError("mais de 1024 arquivos no job: dividir a publicação para atestar todos")
        novo = destino.with_suffix(f".{os.getpid()}.tmp")
        novo.write_text("".join(f"{checksums[n]}  {n}\n" for n in sorted(checksums)), encoding="utf-8")
        novo.replace(destino)
