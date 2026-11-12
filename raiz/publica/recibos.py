"""Recibo verificável da aprovação humana. Não é comprovante de pagamento.

Assinatura Ed25519 em JWS compacto; chave privada somente em variável de ambiente.
Não declara certificação ou conformidade AP2 sem validação externa desse perfil.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def _b64(dado: bytes) -> str:
    return base64.urlsafe_b64encode(dado).rstrip(b"=").decode()


def _bytes(dado: str) -> bytes:
    return base64.urlsafe_b64decode(dado + "=" * (-len(dado) % 4))


def chave_privada() -> Ed25519PrivateKey:
    valor = os.environ.get("RAIZ_RECIBO_CHAVE", "")
    if not valor:
        raise ValueError("defina RAIZ_RECIBO_CHAVE antes de aprovar reservas")
    return Ed25519PrivateKey.from_private_bytes(_bytes(valor))


def jwk(chave: Ed25519PrivateKey | None = None) -> dict:
    chave = chave or chave_privada()
    pub = chave.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return {
        "kty": "OKP",
        "crv": "Ed25519",
        "x": _b64(pub),
        "use": "sig",
        "alg": "EdDSA",
        "kid": hashlib.sha256(pub).hexdigest()[:20],
    }


def assinar(mandato: dict, chave: Ed25519PrivateKey | None = None) -> str:
    chave = chave or chave_privada()
    cabecalho = {"alg": "EdDSA", "typ": "raiz-aprovacao+jwt", "kid": jwk(chave)["kid"]}
    serializar = lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()  # noqa: E731
    entrada = f"{_b64(serializar(cabecalho))}.{_b64(serializar(mandato))}"
    return f"{entrada}.{_b64(chave.sign(entrada.encode()))}"


def verificar(recibo: str, publica: dict, agora: dt.datetime | None = None) -> dict:
    cab, corpo, sig = recibo.split(".")
    header = json.loads(_bytes(cab))
    if header != {"alg": "EdDSA", "typ": "raiz-aprovacao+jwt", "kid": publica["kid"]}:
        raise ValueError("cabeçalho do recibo inválido")
    Ed25519PublicKey.from_public_bytes(_bytes(publica["x"])).verify(_bytes(sig), f"{cab}.{corpo}".encode())
    payload = json.loads(_bytes(corpo))
    agora = agora or dt.datetime.now(dt.UTC)
    if payload.get("tipo") != "aprovacao_humana_reserva" or payload.get("pagamento_confirmado") is not False:
        raise ValueError("tipo do mandato inválido")
    if int(payload["iat"]) > agora.timestamp() + 60:
        raise ValueError("recibo com data futura")
    return payload
