"""API real de carga com PostGIS descartável; nenhuma integração externa é configurada."""

from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path
from unittest.mock import patch

import uvicorn
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from raiz import RAIZ_REPO
from raiz.banco import desfazer, migrar
from raiz.carga import carregar_pasta
from raiz.config import Config, config
from raiz.pessoal import gerar_chave
from raiz.seguranca_api import SegurancaAPI


def banco_local(url: str) -> str:
    destino = make_url(url)
    if destino.host not in {"localhost", "127.0.0.1"} or not (destino.database or "").endswith("_carga"):
        raise ValueError("A carga exige PostGIS local descartável com nome terminado em _carga")
    return url


def servir(args: argparse.Namespace) -> None:
    url = banco_local(os.environ["RAIZ_BANCO_URL_CARGA"])
    token = os.environ["RAIZ_CARGA_TOKEN"]
    # Configuração explícita: nem .env nem chaves de integrações do operador entram na API de teste.
    with patch.dict(os.environ, {}, clear=True):
        cfg = Config(
            _env_file=None,
            banco_url=url,
            api_token=token,
            chave_pessoal=gerar_chave(),
            api_limite_minuto=100000 if args.fase == "normal" else 6,
            api_login_limite_minuto=10,
        )
    with patch("raiz.config.Config", return_value=cfg):
        config.cache_clear()
        if not args.reutilizar:
            desfazer(url)
            migrar(url)
            engine = create_engine(url)
            try:
                carregar_pasta(engine, RAIZ_REPO / "dados" / "amostra", dt.date(2026, 11, 12))
            finally:
                engine.dispose()
        engine = create_engine(url)
        from raiz.api import criar_app

        app = criar_app(engine=engine, grafo=object(), deps=object(), whatsapp=False)
        # A janela curta permite medir saturação e recuperação sem esperar um minuto no CI.
        for middleware in app.user_middleware:
            if middleware.cls is SegurancaAPI:
                middleware.kwargs["janela"] = 2
        Path(args.pronto).touch(mode=0o600)
        try:
            uvicorn.run(app, host="127.0.0.1", port=args.porta, access_log=False, log_config=None)
        finally:
            engine.dispose()
            config.cache_clear()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fase", choices=("normal", "limite"), required=True)
    p.add_argument("--porta", type=int, required=True)
    p.add_argument("--pronto", required=True)
    p.add_argument("--reutilizar", action="store_true")
    servir(p.parse_args())
