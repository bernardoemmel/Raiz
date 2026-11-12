"""Contagem atômica compartilhada em Valkey; endereços ficam apenas como HMAC com TTL.

O pacote redis é o cliente MIT do protocolo, não o servidor Redis. Falha no armazenamento
não libera chamadas nem muda silenciosamente para um contador local.
"""

from __future__ import annotations

import hashlib
import hmac
from urllib.parse import urlsplit

# Uma operação: verificar ambos os tetos e, só quando aceita, incrementar ambos.
# O relógio e a expiração são os do servidor, iguais em todos os workers.
_CONTAR = """
local total = tonumber(redis.call('HGET', KEYS[1], 'total') or '0')
local login = tonumber(redis.call('HGET', KEYS[1], 'login') or '0')
local ttl = redis.call('TTL', KEYS[1])
if total >= tonumber(ARGV[1]) or (ARGV[3] == '1' and login >= tonumber(ARGV[2])) then
    return math.max(1, ttl)
end
redis.call('HINCRBY', KEYS[1], 'total', 1)
if ARGV[3] == '1' then redis.call('HINCRBY', KEYS[1], 'login', 1) end
if ttl < 0 then redis.call('EXPIRE', KEYS[1], ARGV[4]) end
return 0
"""


class LimiteCompartilhado:
    def __init__(self, url: str, chave: str, *, cliente=None):
        if urlsplit(url).scheme not in {"redis", "rediss"}:
            raise ValueError("limite compartilhado exige URL redis:// ou rediss:// do Valkey")
        if len(chave.encode()) < 32:
            raise ValueError("RAIZ_API_LIMITE_CHAVE precisa de pelo menos 32 bytes")
        from redis.asyncio import Redis
        from redis.asyncio.retry import Retry
        from redis.backoff import NoBackoff

        self.cliente = cliente or Redis.from_url(
            url,
            socket_connect_timeout=1,
            socket_timeout=1,
            retry_on_timeout=False,
            retry=Retry(NoBackoff(), 0),
            max_connections=50,
        )
        self.chave = chave.encode()

    def identificador(self, ip: str) -> str:
        resumo = hmac.new(self.chave, ip.encode(), hashlib.sha256).hexdigest()
        return "raiz:limite:v1:" + resumo

    async def espera(self, ip: str, login: bool, limite: int, login_limite: int, janela: int) -> int:
        return int(
            await self.cliente.eval(_CONTAR, 1, self.identificador(ip), limite, login_limite, int(login), janela)
        )

    async def saude(self) -> None:
        await self.cliente.ping()

    async def fechar(self) -> None:
        await self.cliente.aclose()


def do_config(cfg) -> LimiteCompartilhado | None:
    url = getattr(cfg, "api_limite_storage_url", None)
    if not url:
        return None
    chave = getattr(cfg, "api_limite_chave", None)
    if not chave:
        raise ValueError("defina RAIZ_API_LIMITE_CHAVE para usar o limite compartilhado")
    return LimiteCompartilhado(url.get_secret_value(), chave.get_secret_value())
