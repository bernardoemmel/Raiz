"""Arquivo local privado, somente acréscimo; hashes canônicos não são autorização de acesso."""

import hashlib
import json
import os
from pathlib import Path

from pydantic import BaseModel


def canonico(valor) -> bytes:
    def converter(v):
        if isinstance(v, BaseModel):
            return v.model_dump(mode="json")
        raise TypeError("tipo fora do contrato")

    return json.dumps(valor, default=converter, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def resumo_hash(valor) -> str:
    return hashlib.sha256(canonico(valor)).hexdigest()


def congelar(pasta: Path, valor) -> str:
    """Não sobrescreve versão antiga. Um processo com acesso ao disco ainda exige WORM/backup no servidor."""
    corpo = canonico(valor)
    chave = hashlib.sha256(corpo).hexdigest()
    pasta.mkdir(parents=True, exist_ok=True, mode=0o700)
    destino = pasta / f"{chave}.json"
    try:
        fd = os.open(destino, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if destino.is_symlink() or destino.read_bytes() != corpo:
            raise ValueError("arquivo congelado adulterado") from None
    else:
        with os.fdopen(fd, "wb") as arquivo:
            arquivo.write(corpo)
            arquivo.flush()
            os.fsync(arquivo.fileno())
    return chave


def fixar_plano(pasta: Path, plano, *, agora=None) -> None:
    """Recebimento antes do treino; no servidor usar armazenamento privado imutável e relógio confiável."""
    from datetime import UTC, datetime

    agora = agora or datetime.now(UTC)
    if abs((agora - plano.fixado_em).total_seconds()) > 300 or agora >= plano.inicio_treino_em:
        raise ValueError("plano não pode ser registrado retroativamente ou depois do início do treino")
    h = congelar(pasta, plano)
    recibo = canonico({"plano_sha256": h, "recebido_em": agora.isoformat()})
    destino = pasta / f"plano-{plano.plano_id}.json"
    try:
        fd = os.open(destino, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError("identificador de plano já fixado; não pode trocar tolerâncias") from None
    with os.fdopen(fd, "wb") as arquivo:
        arquivo.write(recibo)
        arquivo.flush()
        os.fsync(arquivo.fileno())


def conferir_plano_fixado(pasta: Path, plano) -> None:
    from datetime import datetime

    destino = pasta / f"plano-{plano.plano_id}.json"
    if destino.is_symlink():
        raise ValueError("recibo de plano inválido")
    r = json.loads(destino.read_bytes())
    h = resumo_hash(plano)
    if r["plano_sha256"] != h or datetime.fromisoformat(r["recebido_em"]) >= plano.inicio_treino_em:
        raise ValueError("plano não coincide com o registrado antes do treino")
    congelado = pasta / f"{h}.json"
    if congelado.is_symlink() or congelado.read_bytes() != canonico(plano):
        raise ValueError("plano congelado adulterado")
