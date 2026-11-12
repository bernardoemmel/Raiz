"""Ambiente do Alembic: a URL vem de quem chamou (raiz.banco.migrar) ou de RAIZ_BANCO_URL."""

from alembic import context
from sqlalchemy import create_engine

from raiz.config import config


def _url() -> str:
    return context.config.attributes.get("url") or config().banco_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    conexao = context.config.attributes.get("conexao")
    if conexao is not None:
        context.configure(connection=conexao)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(_url())
    with engine.connect() as con:
        context.configure(connection=con)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
