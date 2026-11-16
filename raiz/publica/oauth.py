"""OAuth do MCP: JWT do Keycloak, empresa vinculada e autorização administrativa de reserva.

A ponte para a REST injeta uma identidade no escopo ASGI, com sentinela privada. Nenhum cabeçalho fornecido pelo
cliente pode criar essa identidade. Tokens, claims pessoais e textos de terceiros nunca viram atributos de log.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from urllib.parse import urlsplit

import anyio
import httpx
import jwt
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.routes import create_protected_resource_routes
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request

from raiz.publica.chaves import Acesso

ESCOPOS = frozenset({"consultar", "pedir", "reservar"})
_MARCADOR = object()


def _url_segura(url: str) -> bool:
    u = urlsplit(url)
    return bool(
        u.hostname
        and not u.username
        and not u.password
        and not u.query
        and not u.fragment
        and (u.scheme == "https" or (u.scheme == "http" and u.hostname in {"localhost", "127.0.0.1", "::1"}))
    )


class VerificadorKeycloak:
    """Valida RS256 por JWKS do emissor fixo, audiência, tempo, sujeito e vínculo ativo com a empresa.

    Não segue jku/x5u do token, redirecionamentos HTTP nem algoritmos informados pelo atacante. A permissão de reserva
    é relida no banco a cada autenticação, portanto desligá-la vale mesmo para um JWT ainda não vencido.
    """

    def __init__(
        self,
        engine_de: Callable[[], Engine],
        *,
        issuer: str | None = None,
        resource: str | None = None,
        jwks_url: str | None = None,
        roles_client: str | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.engine_de = engine_de
        self.issuer = (issuer or os.environ.get("RAIZ_OAUTH_ISSUER") or "").rstrip("/")
        self.resource = (resource or os.environ.get("RAIZ_MCP_RESOURCE") or "").rstrip("/")
        self.jwks_url = (
            jwks_url or os.environ.get("RAIZ_OAUTH_JWKS_URL") or (self.issuer + "/protocol/openid-connect/certs")
        )
        self.roles_client = roles_client or os.environ.get("RAIZ_OAUTH_ROLES_CLIENT", "raiz-api")
        self.http_transport = http_transport
        self._chaves: dict = {}
        self._atualizado = 0.0
        self._trava = anyio.Lock()
        if not _url_segura(self.issuer) or not _url_segura(self.resource):
            raise ValueError("configure RAIZ_OAUTH_ISSUER e RAIZ_MCP_RESOURCE com URLs HTTPS (HTTP só em localhost)")
        emissor, jwks = urlsplit(self.issuer), urlsplit(self.jwks_url)
        if not _url_segura(self.jwks_url) or (emissor.scheme, emissor.netloc) != (jwks.scheme, jwks.netloc):
            raise ValueError("o JWKS deve estar na mesma origem HTTPS do emissor Keycloak")

    @property
    def auth(self) -> AuthSettings:
        return AuthSettings(
            issuer_url=AnyHttpUrl(self.issuer),
            resource_server_url=AnyHttpUrl(self.resource),
            required_scopes=[],
            validate_token_resource=True,
        )

    async def _chave(self, kid: str):
        agora = time.monotonic()
        if kid in self._chaves and agora - self._atualizado < 300:
            return self._chaves[kid]
        async with self._trava:
            agora = time.monotonic()
            if agora - self._atualizado < 5:
                return self._chaves.get(kid)
            async with httpx.AsyncClient(transport=self.http_transport, timeout=1, follow_redirects=False) as cli:
                r = await cli.get(self.jwks_url)
                r.raise_for_status()
                if len(r.content) > 262144:
                    return None
                data = r.json()
            chaves = {}
            for k in data.get("keys", [])[:30]:
                if k.get("kty") == "RSA" and k.get("use", "sig") == "sig" and k.get("alg", "RS256") == "RS256":
                    chaves[str(k.get("kid", ""))] = jwt.PyJWK.from_dict(k).key
            self._chaves, self._atualizado = chaves, agora
            return self._chaves.get(kid)

    def _empresa(self, empresa_id: int) -> bool | None:
        with self.engine_de().connect() as con:
            return con.execute(
                text("""select a.reservar_habilitado from negocio.conta_api a
                        join negocio.cliente c on c.id = a.cliente_id
                        where a.cliente_id = :c and c.ativo and a.bloqueada_em is null"""),
                {"c": empresa_id},
            ).scalar_one_or_none()

    async def verify_token(self, token: str) -> AccessToken | None:
        if len(token) > 16384 or token.startswith("raiz_"):
            return None
        try:
            with anyio.fail_after(1.5):
                cab = jwt.get_unverified_header(token)
                kid = cab.get("kid")
                if cab.get("alg") != "RS256" or not isinstance(kid, str) or not 1 <= len(kid) <= 128:
                    return None
                key = await self._chave(kid)
                if key is None:
                    return None
                c = jwt.decode(
                    token,
                    key,
                    algorithms=["RS256"],
                    issuer=self.issuer,
                    audience=self.resource,
                    options={"require": ["exp", "iat", "iss", "aud", "sub"]},
                    leeway=5,
                )
                if not isinstance(c.get("sub"), str) or not c["sub"]:
                    return None
                empresa = c.get("empresa_id")
                if isinstance(empresa, bool) or not str(empresa).isdigit() or int(empresa) < 1:
                    return None
                cid = int(empresa)
                pode_reservar = await anyio.to_thread.run_sync(self._empresa, cid, abandon_on_cancel=True)
                if pode_reservar is None:
                    return None
                escopos = set(str(c.get("scope", "")).split()) & ESCOPOS
                if not pode_reservar:
                    escopos.discard("reservar")
                client_id = c.get("azp") or c.get("client_id")
                if not isinstance(client_id, str) or not client_id:
                    return None
                roles = ((c.get("resource_access") or {}).get(self.roles_client) or {}).get("roles", [])
                return AccessToken(
                    token=token,
                    client_id=client_id,
                    subject=c["sub"],
                    expires_at=int(c["exp"]),
                    resource=self.resource,
                    scopes=sorted(escopos),
                    claims={
                        "empresa_id": cid,
                        "admin_empresa": isinstance(roles, list) and "admin_empresa" in roles,
                        "iss": self.issuer,
                    },
                )
        except (
            jwt.PyJWTError,
            httpx.HTTPError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            TimeoutError,
            SQLAlchemyError,
        ):
            return None


def administrador_da_empresa(token: AccessToken | None, empresa_id: int) -> bool:
    """Só role de cliente confiável + empresa do JWT; realm role global não autoriza uma empresa."""
    c = token.claims if token else None
    return bool(c and c.get("admin_empresa") is True and c.get("empresa_id") == empresa_id)


def identidade(token: AccessToken) -> Acesso:
    return Acesso(int((token.claims or {})["empresa_id"]), None, "mcp", frozenset(token.scopes))


def acesso_interno(request: Request) -> Acesso | None:
    estado = request.scope.get("state") or {}
    a = estado.get("raiz_acesso_mcp")
    return a if estado.get("raiz_marcador_mcp") is _MARCADOR and isinstance(a, Acesso) else None


def com_identidade(app, token: AccessToken):
    """Ponte somente em memória; não cria um cabeçalho privilegiado que possa ser enviado pela rede."""
    a = identidade(token)

    async def interno(scope, receive, send):
        scope = {**scope, "state": {**scope.get("state", {}), "raiz_marcador_mcp": _MARCADOR, "raiz_acesso_mcp": a}}
        await app(scope, receive, send)

    return interno


def rotas_metadados(verificador: VerificadorKeycloak):
    """Montar estas rotas na raiz do app, fora do prefixo /mcp (RFC 9728)."""
    return create_protected_resource_routes(
        AnyHttpUrl(verificador.resource),
        [AnyHttpUrl(verificador.issuer)],
        scopes_supported=sorted(ESCOPOS),
        resource_name="Raíz: pedido de lote",
    )
