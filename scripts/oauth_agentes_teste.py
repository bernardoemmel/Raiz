"""OAuth real com PKCE para fixtures locais; nenhuma credencial é entregue ao agente.

O grant de senha é usado somente pelo bootstrap administrador do Keycloak/master.
O cliente público raiz-agentes continua exigindo Authorization Code + PKCE S256.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx


def _local(url: str) -> str:
    u = urlsplit(url)
    if u.scheme != "http" or u.hostname not in {"localhost", "127.0.0.1"} or u.username or u.password:
        raise ValueError("O bootstrap OAuth só aceita o Keycloak HTTP local da pilha de teste")
    return url.rstrip("/")


def _exigir(resposta: httpx.Response, codigos=(200, 201, 204)) -> None:
    if resposta.status_code not in codigos:
        # Nem corpo nem URL da resposta: ambos podem conter dados de autenticação.
        raise RuntimeError(f"O bootstrap OAuth falhou com HTTP {resposta.status_code}")


class _Formulario(HTMLParser):
    def __init__(self, html: str):
        super().__init__()
        self.action = ""
        self.campos: dict[str, str] = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form" and not self.action:
            self.action = a.get("action", "")
        if tag == "input" and a.get("name") and a.get("type") == "hidden":
            self.campos[a["name"]] = a.get("value", "")


@dataclass
class SessaoTeste:
    usuario_id: str
    access_token: str = field(repr=False)


class KeycloakTeste:
    def __init__(self, env: dict[str, str]):
        self.issuer = _local(env["RAIZ_OAUTH_ISSUER"])
        self.base = self.issuer.split("/realms/", 1)[0]
        self.callback = _local(env["RAIZ_OAUTH_REDIRECT_URI"])
        self.admin = env["RAIZ_KEYCLOAK_ADMIN"]
        self.senha_admin = env["RAIZ_KEYCLOAK_ADMIN_SENHA"]

    async def _admin(self, cl):
        r = await cl.post(
            f"{self.base}/realms/master/protocol/openid-connect/token",
            data={
                "client_id": "admin-cli",
                "grant_type": "password",
                "username": self.admin,
                "password": self.senha_admin,
            },
        )
        _exigir(r)
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    async def criar_sessao(self, cliente_id: int, identificador: str, reservar: bool = False) -> SessaoTeste:
        """Novo usuário sem privilégios administrativos, com vínculo de empresa definido pelo bootstrap."""
        username = "fixture-" + hashlib.sha256(identificador.encode()).hexdigest()[:24]
        senha = secrets.token_urlsafe(32)
        async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as cl:
            headers = await self._admin(cl)
            users = f"{self.base}/admin/realms/raiz/users"
            r = await cl.get(users, params={"username": username, "exact": "true"}, headers=headers)
            _exigir(r)
            for antigo in r.json():
                _exigir(await cl.delete(f"{users}/{antigo['id']}", headers=headers))
            r = await cl.post(
                users,
                headers=headers,
                json={
                    "username": username,
                    "enabled": True,
                    "requiredActions": [],
                    "attributes": {"empresa_id": [str(cliente_id)]},
                    "credentials": [{"type": "password", "value": senha, "temporary": False}],
                },
            )
            _exigir(r)
            uid = r.headers["Location"].rsplit("/", 1)[-1]
            verifier = secrets.token_urlsafe(48)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            state = secrets.token_urlsafe(24)
            r = await cl.get(
                f"{self.issuer}/protocol/openid-connect/auth",
                params={
                    "client_id": "raiz-agentes",
                    "redirect_uri": self.callback,
                    "response_type": "code",
                    "scope": "consultar pedir" + (" reservar" if reservar else ""),
                    "state": state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                },
            )
            for _ in range(6):
                if r.status_code in (302, 303):
                    destino = urljoin(str(r.url), r.headers["Location"])
                    if destino.startswith(self.callback + "?"):
                        query = parse_qs(urlsplit(destino).query)
                        if query.get("state") != [state] or len(query.get("code", [])) != 1:
                            raise RuntimeError("Resposta OAuth não corresponde ao estado da sessão")
                        r = await cl.post(
                            f"{self.issuer}/protocol/openid-connect/token",
                            data={
                                "client_id": "raiz-agentes",
                                "grant_type": "authorization_code",
                                "code": query["code"][0],
                                "redirect_uri": self.callback,
                                "code_verifier": verifier,
                            },
                        )
                        _exigir(r)
                        return SessaoTeste(uid, r.json()["access_token"])
                    if urlsplit(destino).netloc != urlsplit(self.issuer).netloc:
                        raise RuntimeError("Redirecionamento OAuth fora do Keycloak de teste")
                    r = await cl.get(destino)
                    continue
                _exigir(r)
                form = _Formulario(r.text)
                action = urljoin(str(r.url), form.action)
                if not form.action or urlsplit(action).netloc != urlsplit(self.issuer).netloc:
                    raise RuntimeError("Formulário OAuth de teste ausente ou de origem inesperada")
                dados = dict(form.campos)
                if 'name="username"' in r.text:
                    dados.update(username=username, password=senha)
                else:
                    dados["accept"] = "Yes"
                r = await cl.post(action, data=dados)
        raise RuntimeError("O fluxo PKCE de teste não concluiu login e consentimento")

    async def remover_sessao(self, usuario_id: str) -> None:
        async with httpx.AsyncClient(timeout=20, trust_env=False) as cl:
            headers = await self._admin(cl)
            _exigir(await cl.delete(f"{self.base}/admin/realms/raiz/users/{usuario_id}", headers=headers), (204, 404))
