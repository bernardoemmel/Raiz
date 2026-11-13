"""OAuth real e descartável: Authorization Code + PKCE S256 no Keycloak local.

Credenciais sintéticas permanecem na memória. Não usa password grant, JWT fabricado
nem perfil de produção. Cada tentativa cria e remove seu próprio realm.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx


@dataclass(frozen=True)
class OAuthConfig:
    url: str = "http://127.0.0.1:18180"
    administrador: str = "avaliador"
    senha: str = "avaliacao-local-sem-dados-reais"

    @classmethod
    def from_env(cls):
        return cls(
            os.getenv("RAIZ_AVALIACAO_KEYCLOAK_URL", cls.url),
            os.getenv("RAIZ_AVALIACAO_KEYCLOAK_ADMIN", cls.administrador),
            os.getenv("RAIZ_AVALIACAO_KEYCLOAK_SENHA", cls.senha),
        )

    def validar(self):
        u = urlsplit(self.url)
        if u.scheme != "http" or u.hostname != "127.0.0.1" or u.port != 18180 or u.path or u.query or u.username:
            raise ValueError("OAuth da avaliação exige a pilha local na porta 18180")


def _codigo(cli, issuer, client_id, redirect, usuario, senha, escopos):
    verificador = secrets.token_urlsafe(48)
    desafio = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
    estado = secrets.token_urlsafe(24)
    parametros = {
        "client_id": client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "response_mode": "query",
        "scope": escopos,
        "code_challenge": desafio,
        "code_challenge_method": "S256",
        "state": estado,
    }
    navegador = Path(__file__).with_name("avaliacao_oauth_navegador.mjs")
    # Chromium aplica cookies Secure em localhost como no login humano. Tokens/códigos nunca vão aos logs.
    r = subprocess.run(
        ["node", str(navegador)],
        input=json.dumps(
            {
                "autorizacao": issuer + "/protocol/openid-connect/auth?" + urlencode(parametros),
                "redirect": redirect,
                "usuario": usuario,
                "senha": senha,
            }
        ),
        text=True,
        capture_output=True,
        timeout=60,
    )
    if r.returncode:
        raise ValueError("Login OAuth da pilha não concluiu")
    destino = json.loads(r.stdout)["callback"]
    query = parse_qs(urlsplit(destino).query)
    if destino.split("?", 1)[0] != redirect or query.get("state") != [estado] or len(query.get("code", [])) != 1:
        raise ValueError("Callback OAuth inválido")
    token = cli.post(
        issuer + "/protocol/openid-connect/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "redirect_uri": redirect,
            "code": query["code"][0],
            "code_verifier": verificador,
        },
    )
    if token.status_code != 200:
        raise ValueError("Troca OAuth da pilha recusada")
    return token.json()["access_token"]


@contextmanager
def autenticar(cliente_id, sessao_id, resource, escopos, config=None):
    config = config or OAuthConfig.from_env()
    config.validar()
    if not isinstance(cliente_id, int) or cliente_id <= 0 or set(escopos) - {"consultar", "pedir", "reservar"}:
        raise ValueError("Identidade da avaliação inválida")
    realm = "avaliacao-" + hashlib.sha256(sessao_id.encode()).hexdigest()[:24]
    with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as cli:
        admin = _codigo(
            cli,
            config.url + "/realms/master",
            "security-admin-console",
            config.url + "/admin/master/console/",
            config.administrador,
            config.senha,
            "openid",
        )
        h = {"Authorization": "Bearer " + admin}
        modelo = json.loads((Path(__file__).resolve().parents[1] / "infra/keycloak/raiz-realm.json").read_text())
        redirect = "https://avaliacao.raiz.invalid/callback"
        senha = secrets.token_urlsafe(32)
        modelo.update(
            realm=realm,
            sslRequired="none",
            accessTokenLifespan=900,
            resetPasswordAllowed=False,
            users=[
                {
                    "username": "agente-avaliacao",
                    "enabled": True,
                    "attributes": {"empresa_id": [str(cliente_id)]},
                    "credentials": [{"type": "password", "value": senha, "temporary": False}],
                }
            ],
        )
        modelo = json.loads(
            json.dumps(modelo).replace("${RAIZ_MCP_RESOURCE}", resource).replace("${RAIZ_OAUTH_REDIRECT_URI}", redirect)
        )
        for cliente in modelo["clients"]:
            if cliente["clientId"] == "raiz-agentes":
                cliente["defaultClientScopes"] = ["raiz-identidade"]
                cliente["optionalClientScopes"] = ["consultar", "pedir", "reservar"]
        r = cli.post(config.url + "/admin/realms", headers=h, json=modelo)
        r.raise_for_status()
        try:
            issuer = config.url + "/realms/" + realm
            token = _codigo(
                cli, issuer, "raiz-agentes", redirect, "agente-avaliacao", senha, "openid " + " ".join(escopos)
            )
            yield type("SessaoOAuth", (), {"token": token, "issuer": issuer})()
        finally:
            cli.delete(config.url + "/admin/realms/" + realm, headers=h).raise_for_status()
