"""Sessão HTTP da coleta: novas tentativas com espera, TLS antigo do servidor do CAR e cache que não guarda erro.

- O GeoServer do CAR usa TLS antigo; o Python novo recusa sem baixar o nível de segurança só para ele (mesmo
  ajuste do motor, motor/raiz_estado.py: LegacyTLS).
- requests-cache (BSD-2) guarda só respostas 200: uma página que deu erro nunca fica presa no cache.
- 429 e 5xx: até 5 tentativas com espera exponencial, respeitando Retry-After.
"""

from __future__ import annotations

import ssl
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from raiz import RAIZ_REPO

AGENTE = "Raiz-coleta/0.1 (+dados publicos; contato pelo repositorio)"


def _contexto_legado() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
    ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
    return ctx


class AdaptadorTLSLegado(HTTPAdapter):
    def init_poolmanager(self, *a, **k):
        k["ssl_context"] = _contexto_legado()
        return super().init_poolmanager(*a, **k)

    def proxy_manager_for(self, proxy, **k):
        k["ssl_context"] = _contexto_legado()
        return super().proxy_manager_for(proxy, **k)


def _retry() -> Retry:
    return Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
        respect_retry_after_header=True,
    )


def sessao(
    tls_legado: bool = False, cache: bool = False, expira_s: int = 6 * 3600, pasta_cache: Path | None = None
) -> requests.Session:
    if cache:
        from requests_cache import CachedSession

        pasta = pasta_cache or RAIZ_REPO / "dados" / "cache_http"
        pasta.mkdir(parents=True, exist_ok=True)
        s: requests.Session = CachedSession(
            str(pasta / "coleta"),
            backend="sqlite",
            expire_after=expira_s,
            allowable_codes=(200,),
            allowable_methods=("GET", "HEAD"),
        )
    else:
        s = requests.Session()
    adaptador = AdaptadorTLSLegado(max_retries=_retry()) if tls_legado else HTTPAdapter(max_retries=_retry())
    s.mount("https://", adaptador)
    s.mount("http://", HTTPAdapter(max_retries=_retry()))
    s.headers["User-Agent"] = AGENTE
    return s
