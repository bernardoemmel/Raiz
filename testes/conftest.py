"""Fixtures. Testes marcados com `banco` usam RAIZ_BANCO_URL_TESTE (PostgreSQL + PostGIS) e são pulados sem ele.
O banco de teste é zerado e migrado do zero a cada sessão."""

import os

import pytest
from sqlalchemy import create_engine, text

from raiz import RAIZ_REPO

AMOSTRA = RAIZ_REPO / "dados" / "amostra"


def _url_teste() -> str | None:
    from raiz.config import config

    return os.environ.get("RAIZ_BANCO_URL_TESTE") or config().banco_url_teste


@pytest.fixture(scope="session")
def banco_url():
    url = _url_teste()
    if not url:
        pytest.skip("sem RAIZ_BANCO_URL_TESTE")
    eng = create_engine(url)
    try:
        with eng.connect() as c:
            c.execute(text("select 1"))
    except Exception as ex:  # noqa: BLE001
        pytest.skip(f"banco de teste fora do ar: {ex}")
    from raiz.banco import desfazer, migrar

    desfazer(url)
    migrar(url)
    yield url
    eng.dispose()


@pytest.fixture
def con(banco_url):
    eng = create_engine(banco_url)
    with eng.begin() as c:
        yield c
    eng.dispose()
