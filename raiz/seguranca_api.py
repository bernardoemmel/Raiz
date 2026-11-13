"""Cabeçalhos e limite por IP, sem guardar IP, corpo, token ou URL em logs.

O limite é por processo: use um worker ou aplique também um limite no proxy quando houver réplicas.
Só o endereço de conexão é usado; cabeçalhos enviados pelo visitante não mudam a chave.
"""

from __future__ import annotations

import math
import time
from collections import OrderedDict
from collections.abc import Callable

from starlette.datastructures import MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse


class SegurancaAPI:
    def __init__(
        self,
        app,
        limite: int = 120,
        login_limite: int = 10,
        janela: int = 60,
        max_clientes: int = 10000,
        origens: list[str] | None = None,
        autenticada_interna: Callable[[dict], bool] | None = None,
    ):
        self.app = app
        self.limite, self.login_limite = limite, login_limite
        self.janela, self.max_clientes = janela, max_clientes
        self.clientes: OrderedDict[str, tuple[float, int, int]] = OrderedDict()
        # Somente uma ponte ASGI autenticada pelo app pode dispensar a segunda contagem por IP.
        # O chamador valida uma sentinela em memória; nunca aceitar cabeçalho/rede como prova.
        self.autenticada_interna = autenticada_interna
        # Ordem: cabeçalhos de segurança → CORS → limite/erros → aplicação.
        # Assim o navegador lê 429/500 e o preflight também recebe os cabeçalhos de segurança.
        self.atender = (
            CORSMiddleware(
                self._atender,
                allow_origins=origens,
                allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
                allow_headers=[
                    "Authorization",
                    "Range",
                    "Content-Type",
                    "X-Chave-API",
                    "Idempotency-Key",
                    "If-Match",
                    "MCP-Protocol-Version",
                    "MCP-Method",
                    "MCP-Name",
                    "MCP-Session-Id",
                    "Last-Event-ID",
                ],
                expose_headers=[
                    "Content-Range",
                    "Accept-Ranges",
                    "Content-Length",
                    "ETag",
                    "Retry-After",
                    "WWW-Authenticate",
                    "Location",
                    "MCP-Session-Id",
                    "MCP-Protocol-Version",
                ],
            )
            if origens
            else self._atender
        )

    def _espera(self, ip: str, login: bool) -> int:
        agora = time.monotonic()
        # Ordem de criação da janela, não de acesso: retirar expirados não varre todos os clientes.
        while self.clientes and next(iter(self.clientes.values()))[0] + self.janela <= agora:
            self.clientes.popitem(last=False)
        if ip not in self.clientes:
            if len(self.clientes) >= self.max_clientes:
                return max(1, math.ceil(next(iter(self.clientes.values()))[0] + self.janela - agora))
            self.clientes[ip] = (agora, 0, 0)
        inicio, total, entradas = self.clientes[ip]
        if total >= self.limite or (login and entradas >= self.login_limite):
            return max(1, math.ceil(inicio + self.janela - agora))
        self.clientes[ip] = (inicio, total + 1, entradas + int(login))
        return 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def enviar(mensagem):
            if mensagem["type"] == "http.response.start":
                headers = MutableHeaders(scope=mensagem)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
                headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
                # Compatível com os painéis HTML atuais, que têm scripts inline.
                # Uma página pode fornecer uma política mais estrita, com nonce de script. Não a enfraquecer.
                headers.setdefault(
                    "Content-Security-Policy", "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
                )
                if scope.get("scheme") == "https":
                    headers["Strict-Transport-Security"] = "max-age=31536000"
                if (
                    any(k.lower() in {b"authorization", b"x-chave-api"} for k, _ in scope.get("headers", []))
                    or scope["path"].startswith(
                        ("/entrar", "/pedidos", "/notificacoes", "/pagamentos", "/backoffice", "/v1/", "/mcp")
                    )
                    or scope["path"] == "/v1"
                ):
                    headers["Cache-Control"] = "no-store"
            await send(mensagem)

        await self.atender(scope, receive, enviar)

    async def _atender(self, scope, receive, send):
        iniciado = False

        async def enviar(mensagem):
            nonlocal iniciado
            if mensagem["type"] == "http.response.start":
                iniciado = True
            await send(mensagem)

        ip = (scope.get("client") or ("desconhecido", 0))[0]
        interna = self.autenticada_interna is not None and self.autenticada_interna(scope) is True
        espera = 0 if interna else self._espera(ip, scope["path"].rstrip("/") in {"/entrar", "/entrar/confirmar"})
        if espera:
            resposta = _problema(
                429,
                "Limite de chamadas",
                "limite de chamadas atingido; tente novamente depois",
                headers={"Retry-After": str(espera), "Cache-Control": "no-store"},
            )
            return await resposta(scope, receive, enviar)
        try:
            await self.app(scope, receive, enviar)
        except Exception:
            # O ServerErrorMiddleware externo não passa pelo middleware ao criar o 500.
            if not iniciado:
                await _problema(500, "Erro interno", "erro interno")(scope, receive, enviar)
            raise


def _problema(status: int, titulo: str, detalhe: str, *, headers: dict | None = None) -> JSONResponse:
    """RFC 9457 também antes de autenticar/rotear, sem reproduzir URL, token ou exceção."""
    return JSONResponse(
        {"type": "about:blank", "title": titulo, "status": status, "detail": detalhe},
        status_code=status,
        media_type="application/problem+json",
        headers=headers,
    )
