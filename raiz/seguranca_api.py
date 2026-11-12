"""Cabeçalhos e limite por IP, sem guardar IP, corpo, token ou URL em logs.

O limite é por processo: use um worker ou aplique também um limite no proxy quando houver réplicas.
Só o endereço de conexão é usado; cabeçalhos enviados pelo visitante não mudam a chave.
"""

from __future__ import annotations

import math
import time
from collections import OrderedDict

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
    ):
        self.app = app
        self.limite, self.login_limite = limite, login_limite
        self.janela, self.max_clientes = janela, max_clientes
        self.clientes: OrderedDict[str, tuple[float, int, int]] = OrderedDict()
        # Ordem: cabeçalhos de segurança → CORS → limite/erros → aplicação.
        # Assim o navegador lê 429/500 e o preflight também recebe os cabeçalhos de segurança.
        self.atender = (
            CORSMiddleware(
                self._atender,
                allow_origins=origens,
                allow_methods=["GET", "POST", "PATCH", "DELETE"],
                allow_headers=["Authorization", "Range", "Content-Type"],
                expose_headers=["Content-Range", "Accept-Ranges", "Content-Length", "ETag", "Retry-After"],
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
                headers["Content-Security-Policy"] = "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
                if scope.get("scheme") == "https":
                    headers["Strict-Transport-Security"] = "max-age=31536000"
                if any(k.lower() == b"authorization" for k, _ in scope.get("headers", [])) or scope["path"].startswith(
                    ("/entrar", "/pedidos", "/notificacoes", "/pagamentos", "/backoffice")
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
        espera = self._espera(ip, scope["path"].rstrip("/") in {"/entrar", "/entrar/confirmar"})
        if espera:
            resposta = JSONResponse(
                {"detail": "limite de chamadas atingido; tente novamente depois"},
                status_code=429,
                headers={"Retry-After": str(espera), "Cache-Control": "no-store"},
            )
            return await resposta(scope, receive, enviar)
        try:
            await self.app(scope, receive, enviar)
        except Exception:
            # O ServerErrorMiddleware externo não passa pelo middleware ao criar o 500.
            if not iniciado:
                await JSONResponse({"detail": "erro interno"}, status_code=500)(scope, receive, enviar)
            raise
