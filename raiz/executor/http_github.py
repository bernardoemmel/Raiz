"""Revalida metadados e respeita a cota do GitHub, sem guardar respostas em disco."""

from __future__ import annotations

import hashlib
import logging
import math
import threading
import time
from collections import OrderedDict
from email.utils import parsedate_to_datetime

import httpx

log = logging.getLogger(__name__)


class ClienteGitHub:
    """Cada leitura privada continua remota; só 304 autorizado reaproveita bytes.

    Erros de acesso não usam cache. Repetem-se somente recusas explícitas de cota,
    nunca POST/DELETE de resultado incerto. URLs, corpos e credenciais não são logados.
    """

    def __init__(self, cliente, *, espera_max_s: float = 120, gerenciar_cota: bool = True):
        if not 0 <= espera_max_s <= 3700:
            raise ValueError("espera da cota deve ficar entre zero e 3700 segundos")
        self.cliente = cliente
        self.espera_max_s = espera_max_s
        self.gerenciar_cota = gerenciar_cota
        self._cache = OrderedDict()
        self._serial = threading.RLock()
        self._cota_ate = 0.0
        self._cota_status = 429

    def __getattr__(self, nome):
        return getattr(self.cliente, nome)

    @staticmethod
    def _espera(resposta, tentativa):
        if resposta.status_code not in (403, 429):
            return None
        h = resposta.headers
        limitada = resposta.status_code == 429 or h.get("x-ratelimit-remaining") == "0"
        if not limitada and len(resposta.content) < 16384:
            try:
                limitada = "rate limit" in str(resposta.json().get("message", "")).lower()
            except (ValueError, AttributeError):
                pass
        if not limitada:
            return None
        esperas = [60.0 * 2**tentativa]
        if depois := h.get("retry-after"):
            try:
                esperas = [max(1.0, float(depois))]
            except ValueError:
                try:
                    esperas = [max(1.0, parsedate_to_datetime(depois).timestamp() - time.time())]
                except (ValueError, TypeError, OverflowError):
                    pass
        if h.get("x-ratelimit-remaining") == "0":
            try:
                esperas.append(max(1.0, float(h["x-ratelimit-reset"]) - time.time() + 1))
            except (KeyError, ValueError, OverflowError):
                pass
        espera = max(esperas)
        return espera if math.isfinite(espera) else float("inf")

    def _chamar(self, metodo, url, **kwargs):
        destino = httpx.URL(url)
        if destino.scheme != "https" or destino.host not in {"api.github.com", "uploads.github.com"}:
            return getattr(self.cliente, metodo)(url, **kwargs)
        with self._serial:
            return self._serializado(metodo, url, **kwargs)

    def _serializado(self, metodo, url, **kwargs):
        inicio = time.monotonic()
        falta = self._cota_ate - inicio
        if falta > self.espera_max_s:
            # Não agrava a recusa já confirmada ao tentar publicar outro município.
            return httpx.Response(self._cota_status, json={"message": "API rate limit exceeded"},
                                  headers={"Retry-After": str(math.ceil(falta) if math.isfinite(falta) else 3700)},
                                  request=httpx.Request(metodo, url))  # fmt: skip
        while (falta := self._cota_ate - time.monotonic()) > 0:
            time.sleep(min(60.0, falta))
        headers = httpx.Headers(kwargs.pop("headers", {}))
        completo = str(httpx.URL(url).copy_merge_params(kwargs.get("params") or {}))
        chave = None
        anterior = None
        if (metodo == "get" and headers.get("authorization")
                and headers.get("accept") == "application/vnd.github+json"
                and httpx.URL(url).host == "api.github.com"):  # fmt: skip
            chave = (completo, hashlib.sha256(headers["authorization"].encode()).digest(), headers["accept"])
            anterior = self._cache.get(chave)
            if anterior:
                headers["If-None-Match"] = anterior[0]
        for tentativa in range(4):
            resposta = getattr(self.cliente, metodo)(url, headers=headers, **kwargs)
            espera = self._espera(resposta, tentativa) if self.gerenciar_cota else None
            if espera is not None:
                self._cota_ate = time.monotonic() + espera
                self._cota_status = resposta.status_code
            if espera is None or tentativa == 3 or time.monotonic() - inicio + espera > self.espera_max_s:
                break
            log.warning("cota_github: aguardando %.0f segundos antes de repetir a requisição recusada", espera)
            # Intervalos curtos permitem que o encerramento normal do executor interrompa a espera.
            ate = time.monotonic() + espera
            while (falta := ate - time.monotonic()) > 0:
                time.sleep(min(60.0, falta))
        if chave is not None:
            if resposta.status_code == 304 and anterior:
                _, corpo, salvos = anterior
                combinados = {**salvos, **dict(resposta.headers)}
                for nome in ("content-encoding", "content-length", "transfer-encoding"):
                    combinados.pop(nome, None)
                return httpx.Response(200, content=corpo, headers=combinados, request=resposta.request)
            self._cache.pop(chave, None)
            if (resposta.status_code == 200 and resposta.headers.get("etag")
                    and len(resposta.content) <= 512 * 1024):  # fmt: skip
                self._cache[chave] = (resposta.headers["etag"], resposta.content, dict(resposta.headers))
                while len(self._cache) > 64:
                    self._cache.popitem(last=False)
        return resposta

    def get(self, url, **kwargs):
        return self._chamar("get", url, **kwargs)

    def post(self, url, **kwargs):
        return self._chamar("post", url, **kwargs)

    def delete(self, url, **kwargs):
        return self._chamar("delete", url, **kwargs)
