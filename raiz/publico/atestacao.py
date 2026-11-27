"""Checksums dos uploads concluídos, para a atestação de procedência do Actions.

O Release é mutável: no canal público cada nome conserva o último digest enviado.
O canal privado identifica somente o conteúdo: aliases colapsam, mas versões de
bytes distintas permanecem atestadas. Nenhuma lista contém nomes privados nem os
dados. A assinatura OIDC é feita pelo actions/attest.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path


def identificador(nome: str, *, privado: bool = False, digest: str | None = None) -> str:
    """Nome público de um assunto; arquivos privados nunca revelam o nome original."""
    if privado:
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("digest de conteúdo inválido para a atestação privada")
        return f"privado-sha256-{digest}"
    if not nome or any(c in nome for c in "\r\n\x00\\/") or nome in {".", ".."}:
        raise ValueError("nome de arquivo inválido para a atestação")
    return nome


def registrar(nome: str, dados: bytes, *, privado: bool = False) -> None:
    """Registra somente depois do upload bem-sucedido; sem RUNNER_TEMP, não grava."""
    temporaria = os.environ.get("RUNNER_TEMP")
    if not temporaria:
        return
    digest_atual = hashlib.sha256(dados).hexdigest()
    assunto = identificador(nome, privado=privado, digest=digest_atual)
    import fcntl

    pasta = Path(temporaria)
    pasta.mkdir(parents=True, exist_ok=True)
    base = "atestar-privado" if privado else "atestar"
    destino = pasta / f"{base}.txt"
    with (pasta / f"{base}.lock").open("a") as trava:
        fcntl.flock(trava, fcntl.LOCK_EX)
        checksums = {}
        try:
            if destino.exists():
                for linha in destino.read_text(encoding="utf-8").splitlines():
                    digest, arquivo = linha.split("  ", 1)
                    if not re.fullmatch(r"[a-f0-9]{64}", digest):
                        raise ValueError("checksum inválido para a atestação")
                    if privado:
                        # Converte também a versão antiga que derivava o subject
                        # do nome. Só o digest dos bytes pode aparecer em público.
                        arquivo = identificador(arquivo, privado=True, digest=digest)
                    checksums[arquivo] = digest
            checksums[assunto] = digest_atual
            if len(checksums) > 1024:
                raise ValueError("mais de 1024 arquivos no job: dividir a publicação para atestar todos")
        except (ValueError, UnicodeError):
            if privado:
                # Um passo always() não pode publicar nomes de uma lista legada
                # cuja conversão falhou, mesmo quando a catalogação já parou.
                destino.unlink(missing_ok=True)
                raise ValueError("lista de atestação inválida ou acima do limite de 1024 arquivos") from None
            raise
        novo = destino.with_suffix(f".{os.getpid()}.tmp")
        novo.write_text("".join(f"{checksums[n]}  {n}\n" for n in sorted(checksums)), encoding="utf-8")
        novo.replace(destino)
