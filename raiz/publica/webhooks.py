"""Standard Webhooks v1 e outbox durável por empresa, com destino aprovado pelo operador.

Texto recebido de terceiros nunca é instrução. Eventos só carregam identificadores e
estados conhecidos, nunca nomes, documentos, contatos, prompts, URLs ou texto livre.
"""

from __future__ import annotations

import base64
import datetime as dt
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import time
import uuid
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from urllib.parse import urlsplit
from urllib.request import getproxies, proxy_bypass_environment

import httpx
from sqlalchemy import Connection, Engine, text

from raiz.pessoal import Cofre

_SIGILO = ContextVar("webhook_sigilo", default=False)


class _FiltroSigilo(logging.Filter):
    def filter(self, record):
        return not _SIGILO.get()


_FILTRO = _FiltroSigilo()
# HTTPX registra URL em INFO e HTTPCore pode registrar headers em DEBUG.
# O filtro atua apenas no contexto desta entrega, preservando os outros requests.
for _nome_logger in (
    "httpx",
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
    "httpcore.socks",
):
    logging.getLogger(_nome_logger).addFilter(_FILTRO)


TIPOS = frozenset(
    {"pedido.atualizado", "lote.pronto", "contato.atualizado", "reserva.atualizada", "revisao.atualizada"}
)
ESTADOS = frozenset(
    {
        "pendente",
        "recebido",
        "aguardando",
        "processando",
        "concluido",
        "pronto",
        "erro",
        "falhou",
        "cancelado",
        "cancelada",
        "aguardando_confirmacao",
        "aguardando_pagamento",
        "ativa",
        "expirada",
        "convertida",
        "conflito",
        "sem_contato",
        "contatado",
        "interessado",
        "aceite_fase1",
        "contrato_firme",
        "recusou",
        "sem_resposta",
        "em_revisao",
        "mantida",
        "revista",
    }
)


def gerar_segredo() -> str:
    return "whsec_" + base64.b64encode(secrets.token_bytes(32)).decode("ascii")


def _chave(segredo: str) -> bytes:
    try:
        if not isinstance(segredo, str) or not segredo.startswith("whsec_"):
            raise ValueError
        chave = base64.b64decode(segredo[6:], validate=True)
        if not 24 <= len(chave) <= 64:
            raise ValueError
        return chave
    except (ValueError, TypeError) as ex:
        raise ValueError("segredo de webhook inválido") from ex


def assinar(corpo: bytes, segredo: str, evento_id: str, *, timestamp: int | None = None) -> dict[str, str]:
    """Assina os bytes exatos enviados; ID estável e timestamp novo em cada tentativa."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", evento_id):
        raise ValueError("identificador de webhook inválido")
    ts = str(int(time.time()) if timestamp is None else int(timestamp))
    if not ts.isdecimal():
        raise ValueError("timestamp de webhook inválido")
    mensagem = evento_id.encode() + b"." + ts.encode() + b"." + corpo
    assinatura = base64.b64encode(hmac.digest(_chave(segredo), mensagem, "sha256")).decode("ascii")
    return {"webhook-id": evento_id, "webhook-timestamp": ts, "webhook-signature": "v1," + assinatura}


def verificar(
    corpo: bytes,
    cabecalhos: Mapping[str, str],
    segredo: str,
    *,
    agora: int | None = None,
    tolerancia: int = 300,
) -> str:
    """Verifica assinatura e janela temporal; receptor deve deduplicar o ID retornado."""
    headers = {k.lower(): v for k, v in cabecalhos.items()}
    try:
        evento_id = headers["webhook-id"]
        ts = headers["webhook-timestamp"]
        if not ts.isdecimal() or len(ts) > 12 or not 0 <= tolerancia <= 300:
            raise ValueError
        if abs((int(time.time()) if agora is None else agora) - int(ts)) > tolerancia:
            raise ValueError
        esperado = assinar(corpo, segredo, evento_id, timestamp=int(ts))["webhook-signature"]
        if ts != str(int(ts)):
            raise ValueError
        if not any(hmac.compare_digest(esperado, assinatura) for assinatura in headers["webhook-signature"].split()):
            raise ValueError
    except (KeyError, ValueError, TypeError) as ex:
        raise ValueError("assinatura de webhook inválida ou expirada") from ex
    return evento_id


def validar_destino(url: str, *, hosts: str | None = None) -> str:
    """Só HTTPS:443 em hosts exatos aprovados; sem credenciais, query ou fragmento."""
    try:
        partes = urlsplit(url)
        host = partes.hostname or ""
        permitidos = {
            h.strip().lower()
            for h in (hosts if hosts is not None else os.getenv("RAIZ_WEBHOOK_HOSTS", "")).split(",")
            if h.strip()
        }
        if (
            partes.scheme != "https"
            or partes.port not in {None, 443}
            or not host
            or partes.username is not None
            or partes.password is not None
            or partes.query
            or partes.fragment
            or host != host.lower()
            or host.endswith(".")
            or not re.fullmatch(r"[a-z0-9.-]+", host)
            or host not in permitidos
            or any(c in url for c in "\r\n\t\\")
        ):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError
        return host
    except (ValueError, TypeError) as ex:
        raise ValueError("destino de webhook não autorizado") from ex


def _enderecos_publicos(host: str) -> list[str]:
    enderecos = sorted({item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    if not enderecos or any(not ipaddress.ip_address(ip).is_global for ip in enderecos):
        raise ValueError("destino de webhook não autorizado")
    return enderecos


def enviar_https(url: str, corpo: bytes, cabecalhos: dict[str, str]) -> int:
    """Preserva proxies do ambiente. Operador controla hosts e o egress do proxy.

    Sem proxy, fixa o IP validado mantendo Host/SNI e validação TLS. Com proxy,
    este resolve o destino e deve impedir redes privadas e DNS rebinding no egress.
    """
    host = validar_destino(url)
    enderecos = _enderecos_publicos(host)
    proxies = getproxies()
    tem_proxy = bool(proxies.get("https") or proxies.get("all"))
    if tem_proxy and (
        proxy_bypass_environment(host, proxies) or any("://" in entrada for entrada in proxies.get("no", "").split(","))
    ):
        # Não transformar exceção NO_PROXY em conexão direta sem fixação de IP.
        raise ValueError("destino de webhook não autorizado pelo proxy")
    headers = {**cabecalhos, "Content-Type": "application/json"}
    destino = httpx.URL(url)
    extensoes = {}
    if not tem_proxy:
        destino = destino.copy_with(host=enderecos[0])
        headers["Host"] = host
        extensoes["sni_hostname"] = host
    sigilo = _SIGILO.set(True)
    try:
        with httpx.Client(timeout=3, follow_redirects=False, trust_env=True) as client:
            with client.stream("POST", destino, content=corpo, headers=headers, extensions=extensoes) as resposta:
                return resposta.status_code
    except httpx.HTTPError:
        raise ValueError("falha no envio de webhook") from None
    finally:
        _SIGILO.reset(sigilo)


def cadastrar_inscricao(con: Connection, cliente_id: int, url: str, segredo: str, *, cofre: Cofre) -> str:
    """Operação administrativa; nunca expor como ferramenta de agente."""
    validar_destino(url)
    _chave(segredo)
    inscricao_id = str(uuid.uuid4())
    con.execute(
        text("""
        INSERT INTO negocio.webhook_inscricao (id, cliente_id, url_cifrada, segredo_cifrado)
        VALUES (:id, :cliente, :url, :segredo)
    """),
        {"id": inscricao_id, "cliente": cliente_id, "url": cofre.cifrar(url), "segredo": cofre.cifrar(segredo)},
    )
    return inscricao_id


def enfileirar(
    con: Connection,
    cliente_id: int,
    tipo: str,
    pedido_id: str,
    estado: str,
    *,
    reserva_id: int | None = None,
) -> list[str]:
    """Inserir na MESMA transação da mudança de estado; commit torna ambos duráveis."""
    if tipo not in TIPOS or estado not in ESTADOS:
        raise ValueError("tipo ou estado de evento inválido")
    dados = {"pedido_id": str(uuid.UUID(str(pedido_id))), "estado": estado}
    if reserva_id is not None:
        if not isinstance(reserva_id, int) or isinstance(reserva_id, bool) or reserva_id <= 0:
            raise ValueError("identificador de reserva inválido")
        dados["reserva_id"] = reserva_id
    corpo = json.dumps(
        {"type": tipo, "timestamp": dt.datetime.now(dt.UTC).isoformat(), "data": dados},
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    inscricoes = con.execute(
        text("SELECT id FROM negocio.webhook_inscricao WHERE cliente_id = :c AND ativa"), {"c": cliente_id}
    ).scalars()
    ids = []
    for inscricao in inscricoes:
        evento = str(uuid.uuid4())
        con.execute(
            text("""
            INSERT INTO negocio.webhook_entrega (id, cliente_id, inscricao_id, corpo)
            VALUES (:id, :c, :inscricao, :corpo)
        """),
            {"id": evento, "c": cliente_id, "inscricao": inscricao, "corpo": corpo},
        )
        ids.append(evento)
    return ids


def entregar_proximo(
    engine: Engine,
    cliente_id: int,
    *,
    cofre: Cofre,
    enviar: Callable[[str, bytes, dict[str, str]], int] = enviar_https,
    agora: dt.datetime | None = None,
) -> dict | None:
    """Uma entrega com lease de 60 s; reinício/concorrência não perde evento.

    Garantia pelo menos uma vez: após queda entre envio e commit pode haver repetição.
    Receptor deduplica webhook-id. Nunca gravamos URL, corpo de erro ou resposta remota.
    """
    agora = agora or dt.datetime.now(dt.UTC)
    lease = str(uuid.uuid4())
    with engine.begin() as con:
        linha = (
            con.execute(
                text("""
            SELECT e.id, e.corpo, e.inscricao_id, e.tentativas, i.url_cifrada, i.segredo_cifrado
            FROM negocio.webhook_entrega e JOIN negocio.webhook_inscricao i
              ON i.id = e.inscricao_id AND i.cliente_id = e.cliente_id
            WHERE e.cliente_id = :c AND i.ativa AND e.disponivel_em <= :agora
              AND (e.estado = 'pendente' OR (e.estado = 'enviando' AND e.lease_ate < :agora))
            ORDER BY e.disponivel_em, e.id LIMIT 1 FOR UPDATE OF e SKIP LOCKED
        """),
                {"c": cliente_id, "agora": agora},
            )
            .mappings()
            .first()
        )
        if not linha:
            return None
        linha = dict(linha)
        con.execute(
            text("""
            UPDATE negocio.webhook_entrega SET estado = 'enviando', lease_id = :lease,
                lease_ate = :ate, tentativas = tentativas + 1
            WHERE id = :id AND cliente_id = :c
        """),
            {"lease": lease, "ate": agora + dt.timedelta(seconds=60), "id": linha["id"], "c": cliente_id},
        )
    status = None
    try:
        url = cofre.decifrar(linha["url_cifrada"])
        validar_destino(url)
        corpo = bytes(linha["corpo"])
        cabecalhos = assinar(
            corpo, cofre.decifrar(linha["segredo_cifrado"]), str(linha["id"]), timestamp=int(agora.timestamp())
        )
        status = enviar(url, corpo, cabecalhos)
        if not isinstance(status, int) or not 100 <= status <= 599:
            status = None
    except Exception:
        # Texto de erro remoto pode conter segredos/PII; só o estado categórico é persistido.
        pass
    tentativa = linha["tentativas"] + 1
    sucesso = status is not None and 200 <= status < 300
    estado = "entregue" if sucesso else "cancelada" if status == 410 else "falhou" if tentativa >= 20 else "pendente"
    espera = min(60 * 2 ** min(tentativa - 1, 11), 86400) + secrets.randbelow(30)
    with engine.begin() as con:
        atualizado = con.execute(
            text("""
            UPDATE negocio.webhook_entrega SET estado = :estado, http_status = :status,
                disponivel_em = :proxima, lease_id = NULL, lease_ate = NULL, entregue_em = :entregue
            WHERE id = :id AND cliente_id = :c AND lease_id = :lease
        """),
            {
                "estado": estado,
                "status": status,
                "proxima": agora + dt.timedelta(seconds=espera),
                "entregue": agora if sucesso else None,
                "id": linha["id"],
                "c": cliente_id,
                "lease": lease,
            },
        )
        if atualizado.rowcount and status == 410:
            con.execute(
                text("UPDATE negocio.webhook_inscricao SET ativa = false WHERE id = :id AND cliente_id = :c"),
                {"id": linha["inscricao_id"], "c": cliente_id},
            )
    return {"evento_id": str(linha["id"]), "estado": estado, "tentativas": tentativa}
