"""Integração HTTP/OAuth/SQL real para latência e Locust do MCP da Raíz.

O corpus usa o leitor Claude/MCP real pelo adaptador próprio. A ausência histórica
não autoriza aviso quando esse leitor está presente.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import importlib
import importlib.util
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
from mcp.types import Tool
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from raiz import RAIZ_REPO
from raiz.banco import desfazer, migrar
from raiz.config import Config, config
from raiz.pessoal import gerar_chave
from testes.mcp.cliente import ClienteMCP

AVISO_INJECOES = (
    "Corpus AgentDojo pendente: o MCP oferece ferramentas de pedidos e ficha, sem agente cliente "
    "nem entrada de leitura de certidão, edital ou nome de arquivo. Nenhuma execução de agente foi simulada."
)
CAMPOS = {"meta": {"tipo": "creditos", "valor": 1000000}, "onde": {"ufs": ["PA"]}}
MODULO_LEITOR = "raiz.publica.agente_documentos"
MODULO_AGENTE_REAL = "raiz.publica.agente_real"
MODULO_ADAPTADOR = "testes.mcp.leitor_documentos"
REFERENCIA_SEM_LEITOR = Path(__file__).with_name("sem_leitor_auditado.json")


class AgenteAusente(RuntimeError):
    """Ausência específica do agente leitor; nunca indica aprovação do corpus."""


class SemAgenteLeitor:
    ferramentas_leitura = frozenset({"acompanhar_contato", "consultar_ficha"})

    async def preparar(self, *_):
        raise AgenteAusente(AVISO_INJECOES)

    async def efeitos(self):
        raise AgenteAusente(AVISO_INJECOES)

    async def executar(self, *_):
        raise AgenteAusente(AVISO_INJECOES)


def _modulos_leitor() -> tuple[bool, bool]:
    # find_spec distingue ausência do módulo de falha ao importar sua dependência.
    # Erro de descoberta também reprova, nunca é convertido em ausência.
    leitor = any(importlib.util.find_spec(nome) is not None for nome in (MODULO_LEITOR, MODULO_AGENTE_REAL))
    return leitor, importlib.util.find_spec(MODULO_ADAPTADOR) is not None


def _codigo_mcp(raiz: Path) -> dict[str, str]:
    arquivos = [raiz / "raiz/api.py", *sorted((raiz / "raiz/publica").rglob("*.py"))]
    if len(arquivos) < 2 or any(p.is_symlink() for p in arquivos):
        raise RuntimeError("Superfície MCP ausente ou inválida para a referência auditada")
    return {p.relative_to(raiz).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in arquivos}


def _ferramentas_canonicas(inventario: dict) -> dict:
    return {
        nome: Tool.model_validate(ferramenta).model_dump(mode="json", by_alias=True, exclude_none=True)
        for nome, ferramenta in inventario.items()
    }


def corpus_pendente(ambiente, inventario: dict, *, raiz: Path = RAIZ_REPO) -> bool:
    """Só a ausência exata e a superfície já auditada permitem o aviso temporário.

    Um leitor novo, inclusive com as mesmas ferramentas, invalida a exceção ao ser
    registrado no ponto canônico. Mudanças em API/MCP ou em tools/list também exigem
    revisão antes de renovar a referência; ela nunca é atualizada pelo runner.
    """
    if type(ambiente) is not SemAgenteLeitor:
        return False
    if any(_modulos_leitor()):
        raise RuntimeError("Leitor MCP registrado exige adaptador e corpus executado")
    referencia = json.loads(REFERENCIA_SEM_LEITOR.read_text())
    if _codigo_mcp(raiz) != referencia["codigo"] or _ferramentas_canonicas(inventario) != referencia["ferramentas"]:
        raise RuntimeError("Superfície MCP mudou: integrar o leitor ao corpus ou revisar a ausência antes do aviso")
    return True


@contextlib.contextmanager
def _ambiente_corpus(*, engine, mcp):
    leitor, adaptador = _modulos_leitor()
    if not leitor and not adaptador:
        yield SemAgenteLeitor()
        return
    if leitor:
        nome = MODULO_LEITOR if importlib.util.find_spec(MODULO_LEITOR) is not None else MODULO_AGENTE_REAL
        importlib.import_module(nome)
    if not adaptador:
        raise RuntimeError("Leitor MCP registrado sem adaptador do corpus")
    fabrica = getattr(importlib.import_module(MODULO_ADAPTADOR), "integracao", None)
    if not callable(fabrica):
        raise RuntimeError("Adaptador do leitor MCP não oferece a fábrica integracao")
    with fabrica(engine=engine, mcp=mcp) as ambiente:
        if type(ambiente) is SemAgenteLeitor or not all(
            callable(getattr(ambiente, nome, None)) for nome in ("preparar", "efeitos", "executar")
        ):
            raise RuntimeError("Adaptador registrado não oferece o ambiente real do corpus")
        yield ambiente


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
    from raiz import prospeccao_acesso
    from raiz.calendario import banco as calendario
    from raiz.calendario.coleta import fontes
    from raiz.calendario.modelos import Evento, identificador
    from raiz.pedidos import servico
    from raiz.publica import trabalhos

    cid, _ = servico.criar_cliente(engine, "Empresa sintética do ensaio MCP")
    with engine.begin() as con:
        # Calendário real no banco, dentro da janela móvel do servidor e sem texto de terceiros.
        agora = dt.datetime.now(dt.UTC)
        fonte = next(f for f in fontes() if f["id"] == "icvcm")
        calendario.gravar(
            con,
            [
                Evento(
                    id=identificador("icvcm", "ensaio-mcp", "icvcm", "1"),
                    tipo="icvcm",
                    data=agora.date() + dt.timedelta(days=1),
                    fonte_id=fonte["id"],
                    fonte_nome=fonte["nome"],
                    fonte_url=fonte["urls"][0],
                    coletado_em=agora,
                    confianca=1,
                )
            ],
            [],
            cruzar_imoveis=False,
        )
        # Estado inicial isolado: crédito fictício, permissão administrativa e liberação já concedidas.
        # Não dispara pagamento nem aprovação usando uma ferramenta de agente.
        con.execute(
            text("""insert into negocio.conta_api
            (cliente_id,cnpj_hmac,cnpj_mascarado,termos_versao,testes_restantes,saldo_rs,
             contrato_aceito_em,sinal_pago_em,reservar_habilitado)
            values (:c,:h,'**','teste-mcp',3,1000000,now(),now(),true)"""),
            {"c": cid, "h": uuid.uuid4().hex},
        )
        car = con.execute(text("select cod_imovel from funil.vigente order by cod_imovel limit 1")).scalar_one()
        con.execute(text("insert into negocio.prospeccao_carteira(cliente_id,creditos) values (:c,1)"), {"c": cid})
    # Saldo sintético só na fixture; o serviço real registra débito e autorização por CAR desta empresa.
    # A consulta MCP posterior não compra acesso e deve funcionar com a carteira já zerada.
    liberacao = prospeccao_acesso.desbloquear(engine, cid, car)
    if liberacao["cobrado"] is not True or liberacao["saldo"] != 0:
        raise RuntimeError("A fixture não confirmou a aquisição da ficha pela própria empresa")
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
        "proximos_eventos": {"argumentos": {"tipo": "icvcm", "dias": 7}},
        "consultar_ficha": {"argumentos": {"codigo_car": car}},
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
        # Somente o cliente do modelo, no processo pai, recebe esta credencial.
        # O subprocesso API/MCP mantém sua lista própria sem credenciais externas.
        ambiente_limpo = {
            k: os.environ[k] for k in ("PATH", "HOME", "LANG", "LC_ALL", "ANTHROPIC_API_KEY") if k in os.environ
        }
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
                    yield SimpleNamespace(
                        cliente=cliente, casos=estado["casos"], inventario=inventario, url=origem + "/mcp/", token=token
                    )
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
            principal.nova_instancia = instancia
            principal.pasta = pasta
            with _ambiente_corpus(engine=engine, mcp=principal) as ambiente:
                yield SimpleNamespace(
                    ambiente=ambiente,
                    cliente=principal.cliente,
                    casos=principal.casos,
                    inventario=principal.inventario,
                    carga=carga,
                    aviso_injecoes=AVISO_INJECOES,
                )
