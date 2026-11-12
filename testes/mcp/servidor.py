"""Processo descartável: app REST/MCP do produto, PostGIS e emissor JWKS local.

O emissor só serve a chave pública do ensaio; a validação RS256, audiência, escopos
 e vínculo da empresa continua integralmente no VerificadorKeycloak do produto.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import socket
from pathlib import Path
from unittest.mock import patch

import uvicorn
from sqlalchemy import create_engine

from raiz.config import Config, config
from raiz.privacidade import configurar_log
from raiz.publica import conta
from raiz.seguranca_api import SegurancaAPI


@contextlib.contextmanager
def rede_local(tentativas: Path):
    permitidos = {"127.0.0.1", "localhost", "::1"}
    conectar = socket.socket.connect
    resolver = socket.getaddrinfo

    def somente_local(self, endereco):
        if isinstance(endereco, tuple) and str(endereco[0]) not in permitidos:
            with tentativas.open("a", encoding="utf-8") as f:
                f.write("conexao_externa_bloqueada\n")
            raise RuntimeError("O ensaio MCP não permite conexão externa")
        return conectar(self, endereco)

    def resolver_local(host, *args, **kwargs):
        if host not in permitidos and host is not None:
            with tentativas.open("a", encoding="utf-8") as f:
                f.write("dns_externo_bloqueado\n")
            raise RuntimeError("O ensaio MCP não permite DNS externo")
        return resolver(host, *args, **kwargs)

    with patch.object(socket.socket, "connect", somente_local), patch.object(socket, "getaddrinfo", resolver_local):
        yield


def executar(caminho: Path) -> None:
    dado = json.loads(caminho.read_text())
    # Nada do .env ou das integrações do operador é carregado neste subprocesso.
    cfg = Config(
        _env_file=None,
        banco_url=dado["banco"],
        chave_pessoal=dado["chave_pessoal"],
        api_token=dado["api_token"],
        api_limite_minuto=100000 if dado["fase"] != "limite" else 18,
        api_login_limite_minuto=10,
        mcp_hosts=dado["origem"].removeprefix("http://"),
    )
    os.environ.update(
        RAIZ_OAUTH_ISSUER=dado["origem"] + "/issuer",
        RAIZ_MCP_RESOURCE=dado["origem"] + "/mcp",
        RAIZ_API_PUBLICA_URL=dado["origem"],
        RAIZ_API_LIMIT_STORAGE_URI="memory://",
    )
    # Arquivo de regras temporário muda somente o orçamento de chamadas do ensaio.
    with (
        patch("raiz.config.Config", return_value=cfg),
        patch.object(conta, "ARQ", Path(dado["regras"])),
        rede_local(Path(dado["rede_bloqueada"])),
    ):
        config.cache_clear()
        configurar_log()
        engine = create_engine(dado["banco"], pool_size=12, max_overflow=12)
        try:
            from raiz.api import criar_app

            app = criar_app(engine=engine, grafo=object(), deps=object(), whatsapp=False)
            for middleware in app.user_middleware:
                if middleware.cls is SegurancaAPI:
                    middleware.kwargs["janela"] = 2

            @app.get("/issuer/protocol/openid-connect/certs", include_in_schema=False)
            def jwks():
                return {"keys": [dado["jwk"]]}

            # Presidio e JSON estruturado executam normalmente; apenas o destino do processo é descartado.
            uvicorn.run(
                app, host="127.0.0.1", port=dado["porta"], access_log=False, log_config=None, log_level="critical"
            )
        finally:
            engine.dispose()
            config.cache_clear()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("configuracao", type=Path)
    executar(p.parse_args().configuracao)
