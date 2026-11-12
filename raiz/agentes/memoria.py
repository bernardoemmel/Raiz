"""Memória das conversas (checkpointer do LangGraph no Postgres), no esquema pessoal e cifrada com AES.

A conversa com o dono é dado pessoal: as tabelas ficam em `pessoal` (search_path da conexão) e cada estado é
cifrado (EncryptedSerializer do LangGraph, AES-EAX) com chave derivada de RAIZ_CHAVE_PESSOAL. Desenho do
agent-service-toolkit (MIT): o checkpointer abre uma vez e é entregue ao grafo.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
from collections.abc import Iterator
from urllib.parse import quote

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.encrypted import EncryptedSerializer
from psycopg import Connection
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url

from raiz.config import config
from raiz.pessoal import _chaves


def chave_aes(chave_pessoal: str | None = None) -> bytes:
    k = _chaves(chave_pessoal)[0]
    return hashlib.sha256(b"raiz-conversas|" + base64.urlsafe_b64decode(k)).digest()


def url_psycopg(url_sqlalchemy: str | None = None) -> str:
    """URL do SQLAlchemy (postgresql+psycopg://) para o formato do psycopg, com search_path=pessoal."""
    u = make_url(url_sqlalchemy or config().banco_url).set(drivername="postgresql")
    base = u.render_as_string(hide_password=False)
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}options={quote('-c search_path=pessoal')}"


@contextlib.contextmanager
def checkpointer(url: str | None = None, chave_pessoal: str | None = None) -> Iterator[PostgresSaver]:
    serde = EncryptedSerializer.from_pycryptodome_aes(key=chave_aes(chave_pessoal))
    with Connection.connect(url_psycopg(url), autocommit=True, prepare_threshold=0, row_factory=dict_row) as con:
        yield PostgresSaver(con, serde=serde)


def preparar(url: str | None = None, chave_pessoal: str | None = None) -> None:
    """Cria (ou atualiza) as tabelas do LangGraph no esquema pessoal."""
    with checkpointer(url, chave_pessoal) as cp:
        cp.setup()
