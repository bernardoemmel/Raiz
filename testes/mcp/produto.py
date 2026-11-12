"""Integração HTTP/OAuth/SQL real para latência e Locust do MCP da Raíz.

Não inventa um agente de leitura: o produto publica ferramentas de pedidos para
agentes externos e não fornece cliente que leia certidão/edital/nomes de arquivo.
O corpus adversarial exige essa integração adicional e permanece explicitamente pendente.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import jwt
import requests
import yaml
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from raiz import RAIZ_REPO
from raiz.banco import desfazer, migrar
from raiz.config import Config, config
from raiz.pessoal import gerar_chave
from testes.mcp.cliente import ClienteMCP

AVISO_INJECOES = (
    "Corpus AgentDojo pendente: o MCP oferece ferramentas de pedidos, sem agente cliente "
    "nem entrada de leitura de certidão, edital ou nome de arquivo. Nenhuma execução de agente foi simulada."
)
CAMPOS = {"meta": {"tipo": "creditos", "valor": 1000000}, "onde": {"ufs": ["PA"]}}


class AgenteAusente(RuntimeError):
    """Ausência específica do agente leitor; nunca indica aprovação do corpus."""


class SemAgenteLeitor:
    ferramentas_leitura = frozenset({"acompanhar_contato"})

    async def preparar(self, *_):
        raise AgenteAusente(AVISO_INJECOES)

    async def efeitos(self):
        raise AgenteAusente(AVISO_INJECOES)

    async def executar(self, *_):
        raise AgenteAusente(AVISO_INJECOES)


def _url_banco() -> str:
    bruto = os.environ.get("RAIZ_BANCO_URL_MCP_TESTE", "")
    if not bruto:
        raise RuntimeError("Defina RAIZ_BANCO_URL_MCP_TESTE para PostGIS local descartável")
    url = make_url(bruto)
    if (
        url.drivername not in {"postgresql", "postgresql+psycopg"}
        or url.host not in {"localhost", "127.0.0.1"}
        or url.database != "raiz_mcp_teste"
        or url.query  # host/hostaddr/dbname/service na query podem substituir o destino visto na URL.
    ):
        raise RuntimeError("O ensaio MCP exige banco local chamado raiz_mcp_teste")
    return bruto


def _gravar_json(caminho: Path, dado) -> None:
    caminho.touch(mode=0o600)
    caminho.write_text(json.dumps(dado), encoding="utf-8")


@contextlib.contextmanager
def _vigiar_rede(registro: Path):
    try:
        yield
    finally:
        if registro.exists() and registro.stat().st_size:
            raise RuntimeError("Aplicação tentou conexão externa durante o ensaio MCP")


def _porta() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _criar_banco(url: str) -> None:
    destino = make_url(url)
    admin = create_engine(destino.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as con:
            existe = con.execute(text("select 1 from pg_database where datname='raiz_mcp_teste'")).scalar()
            if not existe:
                con.execute(text("create database raiz_mcp_teste"))
    finally:
        admin.dispose()
    desfazer(url)
    migrar(url)


def _semente(engine) -> dict:
    from raiz.pedidos import servico
    from raiz.publica import trabalhos

    cid, _ = servico.criar_cliente(engine, "Empresa sintética do ensaio MCP")
    with engine.begin() as con:
        # Estado inicial isolado: crédito fictício, permissão administrativa e liberação já concedidas.
        # Não dispara pagamento nem aprovação usando uma ferramenta de agente.
        con.execute(
            text("""insert into negocio.conta_api
            (cliente_id,cnpj_hmac,cnpj_mascarado,termos_versao,testes_restantes,saldo_rs,
             contrato_aceito_em,sinal_pago_em,reservar_habilitado)
            values (:c,:h,'**','teste-mcp',3,1000000,now(),now(),true)"""),
            {"c": cid, "h": uuid.uuid4().hex},
        )
    negocio = servico.criar_pedido(engine, cid, CAMPOS)["id"]
    acompanhamento = trabalhos.submeter(engine, cid, "consultar_disponibilidade", CAMPOS, "preparacao-acompanhar")
    # As fases anteriores podem ter deixado trabalho submetido; o worker real conclui a fila,
    # inclusive essas intenções, até chegar à consulta de referência da empresa desta fase.
    for _ in range(30):
        trabalhos.executar_proximo(engine)
        resultado = trabalhos.obter(engine, cid, acompanhamento["pedido_id"])
        if resultado["estado"] == "completed":
            break
        if resultado["estado"] != "submitted":
            raise RuntimeError("A consulta de referência terminou sem resultado válido")
    else:
        raise RuntimeError("O trabalho real da consulta de referência não concluiu")
    cancelamento = trabalhos.submeter(engine, cid, "pedir_lote", CAMPOS, "preparacao-cancelar")
    casos = {
        "consultar_disponibilidade": {"argumentos": {"campos": CAMPOS, "idempotency_key": "consulta-manifesto"}},
        "pedir_lote": {"argumentos": {"campos": CAMPOS, "idempotency_key": "pedido-manifesto"}},
        "comparar_lotes": {"argumentos": {"pedido_id": negocio, "idempotency_key": "comparacao-manifesto"}},
        "acompanhar_contato": {
            "argumentos": {"pedido_id": acompanhamento["pedido_id"], "idempotency_key": "contato-manifesto"}
        },
        "preparar_reserva": {"argumentos": {"pedido_id": negocio, "idempotency_key": "reserva-manifesto"}},
        "cancelar": {
            "argumentos": {"pedido_id": cancelamento["pedido_id"], "idempotency_key": "cancelamento-manifesto"}
        },
    }
    return {"cliente_id": cid, "casos": casos}


@contextlib.contextmanager
def integracao():
    url = _url_banco()
    with tempfile.TemporaryDirectory(prefix="raiz-mcp-") as pasta_bruta, contextlib.ExitStack() as pilha:
        pasta = Path(pasta_bruta)
        ambiente_limpo = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "LC_ALL") if k in os.environ}
        pilha.enter_context(patch.dict(os.environ, ambiente_limpo, clear=True))
        privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(privada.public_key()))
        jwk.update(kid="ensaio-local", use="sig", alg="RS256")
        chave_pessoal = gerar_chave()
        cfg = Config(_env_file=None, banco_url=url, chave_pessoal=chave_pessoal)
        pilha.enter_context(patch("raiz.config.Config", return_value=cfg))
        config.cache_clear()
        pilha.callback(config.cache_clear)
        _criar_banco(url)
        engine = create_engine(url, pool_size=12, max_overflow=12)
        pilha.callback(engine.dispose)
        from raiz.carga import carregar_pasta
        from raiz.publica import conta

        carregar_pasta(engine, RAIZ_REPO / "dados" / "amostra", dt.date(2026, 11, 12))
        regras = yaml.safe_load(conta.ARQ.read_text())
        regras["limites"] = {"por_minuto": 100000, "por_dia": 1000000, "por_mes": 10000000}
        regra_arquivo = pasta / "orcamento.yaml"
        regra_arquivo.write_text(yaml.safe_dump(regras))
        pilha.enter_context(patch.object(conta, "ARQ", regra_arquivo))
        pilha.enter_context(patch.dict(os.environ, {"RAIZ_MCP_TESTE_PROTOCOLO": "2026-07-28"}))

        @contextlib.contextmanager
        def instancia(fase):
            estado = _semente(engine)
            porta = _porta()
            origem = f"http://127.0.0.1:{porta}"
            agora = int(time.time())
            claims = {
                "iss": origem + "/issuer",
                "aud": origem + "/mcp",
                "sub": "agente-local-descartavel",
                "iat": agora,
                "exp": agora + 3600,
                "azp": "qualidade-mcp",
                "empresa_id": estado["cliente_id"],
                "scope": "consultar pedir reservar",
            }
            token = jwt.encode(claims, privada, algorithm="RS256", headers={"kid": "ensaio-local"})
            arquivo = pasta / f"servidor-{fase}.json"
            rede = pasta / f"rede-{fase}.txt"
            _gravar_json(
                arquivo,
                {
                    "fase": fase,
                    "banco": url,
                    "chave_pessoal": chave_pessoal,
                    "api_token": secrets.token_urlsafe(24),
                    "origem": origem,
                    "porta": porta,
                    "regras": str(regra_arquivo),
                    "jwk": jwk,
                    "rede_bloqueada": str(rede),
                },
            )
            env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "LC_ALL") if k in os.environ}
            processo = subprocess.Popen(
                [sys.executable, "-m", "testes.mcp.servidor", str(arquivo)],
                cwd=RAIZ_REPO,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            cliente = ClienteMCP(origem + "/mcp/", token)
            with _vigiar_rede(rede):
                try:
                    prazo = time.monotonic() + 40
                    while time.monotonic() < prazo:
                        if processo.poll() is not None:
                            raise RuntimeError("Servidor MCP de teste encerrou antes da saúde")
                        try:
                            if requests.get(origem + "/saude", timeout=1).status_code == 200:
                                break
                        except requests.RequestException:
                            pass
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("Servidor MCP de teste não ficou saudável")
                    cliente.inicializar()
                    inventario = cliente.listar_ferramentas()
                    if set(inventario) != set(estado["casos"]):
                        raise RuntimeError("Manifesto não cobre todas as ferramentas reais")
                    # Sem JWT, o servidor real deve recusar; o JWKS servido é apenas o emissor descartável.
                    r = requests.post(
                        origem + "/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, timeout=4
                    )
                    if r.status_code != 401:
                        raise RuntimeError("MCP aceitou transporte sem OAuth")
                    yield SimpleNamespace(cliente=cliente, casos=estado["casos"], url=origem + "/mcp/", token=token)
                finally:
                    cliente.fechar()
                    processo.terminate()
                    try:
                        processo.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        processo.kill()
                        processo.wait(timeout=5)

        @contextlib.contextmanager
        def carga(fase):
            if fase not in {"normal", "limite"}:
                raise ValueError("Fase de carga inválida")
            with instancia(fase) as alvo:
                arquivo = pasta / f"casos-{fase}.json"
                _gravar_json(arquivo, {"ferramentas": alvo.casos})
                yield {
                    "RAIZ_MCP_TESTE_URL": alvo.url,
                    "RAIZ_MCP_TESTE_TOKEN": alvo.token,
                    "RAIZ_MCP_TESTE_CASOS": str(arquivo),
                    "RAIZ_MCP_TESTE_PROTOCOLO": "2026-07-28",
                }

        with instancia("latencia") as principal:
            yield SimpleNamespace(
                ambiente=SemAgenteLeitor(),
                cliente=principal.cliente,
                casos=principal.casos,
                carga=carga,
                aviso_injecoes=AVISO_INJECOES,
                injecoes_disponiveis=False,
            )
