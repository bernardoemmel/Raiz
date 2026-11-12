"""Conexão com o PostgreSQL + PostGIS e migrações (Alembic)."""

from __future__ import annotations

from functools import lru_cache

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Engine, create_engine

from raiz import RAIZ_REPO
from raiz.config import config


@lru_cache
def engine(url: str | None = None) -> Engine:
    return create_engine(url or config().banco_url, pool_pre_ping=True)


def _alembic(url: str | None) -> AlembicConfig:
    cfg = AlembicConfig(str(RAIZ_REPO / "alembic.ini"))
    cfg.attributes["url"] = url or config().banco_url
    return cfg


def migrar(url: str | None = None, alvo: str = "head") -> None:
    command.upgrade(_alembic(url), alvo)


def desfazer(url: str | None = None, alvo: str = "base") -> None:
    command.downgrade(_alembic(url), alvo)
