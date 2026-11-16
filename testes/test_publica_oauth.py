"""Autorização OAuth: tokens assinados de verdade e política de empresa, sem Keycloak remoto nos testes."""

import json
import time

import anyio
import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from mcp.server.auth.provider import AccessToken
from starlette.requests import Request

from raiz.publica.oauth import VerificadorKeycloak, acesso_interno, administrador_da_empresa, com_identidade

ISSUER = "https://login.raiz.example/realms/raiz"
RESOURCE = "https://api.raiz.example/mcp"


@pytest.fixture
def assinador():
    privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(privada.public_key()))
    jwk.update(kid="chave-1", use="sig", alg="RS256")

    def assinar(**campos):
        dados = {
            "iss": ISSUER,
            "aud": RESOURCE,
            "sub": "usuario-interno",
            "azp": "raiz-agentes",
            "empresa_id": 42,
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "scope": "consultar pedir reservar",
            **campos,
        }
        return jwt.encode(dados, privada, algorithm="RS256", headers={"kid": "chave-1"})

    return assinar, jwk


def verificador(assinador, monkeypatch, permissao=False):
    _, jwk = assinador
    v = VerificadorKeycloak(
        lambda: None,
        issuer=ISSUER,
        resource=RESOURCE,
        http_transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"keys": [jwk]})),
    )
    monkeypatch.setattr(v, "_empresa", lambda cid: permissao if cid == 42 else None)
    return v


def test_reservar_so_com_concessao_persistida(assinador, monkeypatch):
    assinar, _ = assinador
    v = verificador(assinador, monkeypatch)
    token = assinar()
    a = anyio.run(v.verify_token, token)
    assert a.scopes == ["consultar", "pedir"]
    monkeypatch.setattr(v, "_empresa", lambda cid: True)
    assert "reservar" in anyio.run(v.verify_token, token).scopes
    monkeypatch.setattr(v, "_empresa", lambda cid: False)
    assert "reservar" not in anyio.run(v.verify_token, token).scopes
    assert a.claims == {"empresa_id": 42, "admin_empresa": False, "iss": ISSUER}


@pytest.mark.parametrize(
    "mudanca",
    [
        {"aud": "https://outro.example/mcp"},
        {"iss": "https://falso.example"},
        {"exp": 1},
        {"empresa_id": 77},
        {"empresa_id": True},
        {"empresa_id": -1},
        {"iat": int(time.time()) + 3600},
        {"sub": ""},
        {"azp": ""},
    ],
)
def test_jwt_rejeita_claims_invalidos(assinador, monkeypatch, mudanca):
    assinar, _ = assinador
    assert anyio.run(verificador(assinador, monkeypatch).verify_token, assinar(**mudanca)) is None


def test_rejeita_assinatura_alterada_chave_api_e_algoritmo(assinador, monkeypatch):
    assinar, _ = assinador
    v = verificador(assinador, monkeypatch)
    token = assinar()
    partes = token.split(".")
    partes[-1] = "falso"
    for falso in (
        ".".join(partes),
        "raiz_chave-de-api",
        jwt.encode({"sub": "x"}, "segredo-de-teste-sem-validade-real-123456", algorithm="HS256"),
    ):
        assert anyio.run(v.verify_token, falso) is None


def test_admin_e_role_do_cliente_e_empresa_certa(assinador, monkeypatch):
    assinar, _ = assinador
    v = verificador(assinador, monkeypatch)
    role_global = anyio.run(v.verify_token, assinar(realm_access={"roles": ["admin_empresa"]}))
    assert not administrador_da_empresa(role_global, 42)
    role_cliente = anyio.run(v.verify_token, assinar(resource_access={"raiz-api": {"roles": ["admin_empresa"]}}))
    assert administrador_da_empresa(role_cliente, 42)
    assert not administrador_da_empresa(role_cliente, 43)


def test_cabecalhos_nao_criam_identidade_interna():
    scope = {"type": "http", "headers": [(b"x-raiz-cliente", b"42"), (b"x-raiz-via", b"mcp")], "state": {}}
    assert acesso_interno(Request(scope)) is None
    assert acesso_interno(Request({**scope, "state": {"raiz_acesso_mcp": 42, "raiz_marcador_mcp": "true"}})) is None
    token = AccessToken(token="ignorado", client_id="raiz-agentes", scopes=["consultar"], claims={"empresa_id": 42})
    recebidos = []

    async def app(scope, receive, send):
        recebidos.append(acesso_interno(Request(scope)))

    async def executar():
        await com_identidade(app, token)(scope, None, None)

    anyio.run(executar)
    assert recebidos[0].cliente_id == 42 and recebidos[0].escopos == frozenset({"consultar"})


def test_configuracao_falha_fechada():
    for issuer, resource, jwks in (
        ("http://login.example", RESOURCE, None),
        (ISSUER, "", None),
        (ISSUER, RESOURCE, "https://outro.example/jwks"),
    ):
        with pytest.raises(ValueError):
            VerificadorKeycloak(lambda: None, issuer=issuer, resource=resource, jwks_url=jwks)
