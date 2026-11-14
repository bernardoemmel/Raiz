"""Falha real do transporte Valkey/Redis recusa a operação rapidamente, sem banco do produto."""

import asyncio
import copy
import os
import secrets
import socket
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from mcp.server.auth.provider import AccessToken

from raiz.publica import api
from raiz.publica import chaves as K
from raiz.publica import conta as CT


@pytest.fixture
def servidor_sem_resposta():
    parar = threading.Event()
    conexoes = []
    aceitas = []
    with socket.socket() as servidor:
        servidor.bind(("127.0.0.1", 0))
        servidor.listen()
        servidor.settimeout(0.05)

        def atender():
            while not parar.is_set():
                try:
                    con, _ = servidor.accept()
                except TimeoutError:
                    continue
                conexoes.append(con)
                aceitas.append(True)
                # Recebe TCP, mas não responde ao protocolo: o prazo deve vir do cliente, sem retry.

        thread = threading.Thread(target=atender, daemon=True)
        thread.start()
        try:
            yield f"redis://127.0.0.1:{servidor.getsockname()[1]}/0", aceitas
        finally:
            parar.set()
            thread.join(timeout=1)
            for con in conexoes:
                con.close()


def app_sem_banco(monkeypatch, uri, *, limite=30):
    regras = copy.deepcopy(CT.premissas())
    regras["limites"]["por_minuto"] = limite
    monkeypatch.setattr(CT, "premissas", lambda: regras)
    monkeypatch.setenv("RAIZ_API_LIMIT_STORAGE_URI", uri)
    chamadas = []
    monkeypatch.setattr(K, "acesso_da_chave", lambda eng, chave: K.Acesso(int(chave[-1]), None, "api"))
    monkeypatch.setattr(K, "registrar", lambda *args, **kwargs: 1)
    monkeypatch.setattr(CT, "estornar", lambda *args, **kwargs: None)
    monkeypatch.setattr(CT, "registrar_exposicao", lambda *args, **kwargs: None)

    def exigir(eng, cid):
        chamadas.append(cid)
        return {"empresa_id": cid}

    monkeypatch.setattr(CT, "exigir", exigir)

    class Verificador:
        async def verify_token(self, token):
            return AccessToken(
                token="interno-de-teste",
                client_id="teste",
                subject="administrador-sintetico",
                scopes=["consultar", "pedir"],
                claims={"empresa_id": 1, "admin_empresa": True},
            )

    return api.criar(lambda request: object(), verificador=Verificador()), chamadas


@pytest.mark.parametrize(
    "uri", ["redis://127.0.0.1:6379/0", "rediss://127.0.0.1:6379/0", "redis+unix:///tmp/valkey.sock"]
)
def test_cliente_configura_conexao_leitura_e_zero_retries(uri):
    limiter = api._criar_limitador(uri)
    opcoes = limiter._storage.storage.connection_pool.connection_kwargs
    assert opcoes["socket_connect_timeout"] == 0.5 and opcoes["socket_timeout"] == 0.5
    assert opcoes["retry"].get_retries() == 0 and opcoes["retry_on_timeout"] is False
    assert opcoes["retry_on_error"] == [] and limiter._storage.wrap_exceptions
    assert not limiter._swallow_errors and not limiter._in_memory_fallback_enabled


@pytest.mark.parametrize("query", ["socket_timeout=30", "socket_connect_timeout=30", "retry_on_timeout=true"])
def test_query_nao_remove_prazo_nem_habilita_retries(query):
    with pytest.raises(ValueError, match="não pode alterar"):
        api._criar_limitador(f"redis://127.0.0.1:6379/0?{query}")


@pytest.mark.parametrize("variavel", ["RATELIMIT_SWALLOW_ERRORS", "RATELIMIT_IN_MEMORY_FALLBACK_ENABLED"])
def test_fallback_ou_erro_ignorado_na_configuracao_impede_inicio(monkeypatch, variavel):
    monkeypatch.setenv(variavel, "true")
    with pytest.raises(ValueError, match="sem ignorar erros"):
        api._criar_limitador("memory://")


def test_backend_sem_politica_de_prazo_e_rejeitado():
    with pytest.raises(ValueError, match="limitador admite"):
        api._criar_limitador("mongodb://127.0.0.1/limites")


@pytest.mark.parametrize("admin", [False, True])
def test_timeout_tcp_real_recusa_rest_e_administracao_em_503_sem_fallback(monkeypatch, servidor_sem_resposta, admin):
    uri, aceitas = servidor_sem_resposta
    app, chamadas = app_sem_banco(monkeypatch, uri)
    with TestClient(app) as cliente:
        for numero in (1, 2):
            inicio = time.monotonic()
            if admin:
                r = cliente.put(
                    "/conta/permissoes/reservar", json={"habilitado": True}, headers={"Authorization": "Bearer teste"}
                )
            else:
                r = cliente.get("/conta", headers={"X-Chave-API": "raiz_teste1"})
            assert time.monotonic() - inicio < 1.5
            assert r.status_code == 503 and r.headers["content-type"].startswith("application/problem+json")
            assert r.json()["status"] == 503 and r.json()["type"].endswith("#erro-limite_indisponivel")
            assert r.headers["retry-after"] == "1"
            assert "127.0.0.1" not in r.text and "redis://" not in r.text
            assert chamadas == [] and len(aceitas) == numero
    assert not app.state.limiter._storage_dead and not app.state.limiter._in_memory_fallback_enabled


def test_memory_preserva_quota_por_empresa(monkeypatch):
    app, chamadas = app_sem_banco(monkeypatch, "memory://", limite=2)
    with TestClient(app) as cliente:
        for _ in range(2):
            assert cliente.get("/conta", headers={"X-Chave-API": "raiz_teste1"}).status_code == 200
        r = cliente.get("/conta", headers={"X-Chave-API": "raiz_teste1"})
        assert r.status_code == 429 and "retry-after" in r.headers
        assert cliente.get("/conta", headers={"X-Chave-API": "raiz_teste2"}).status_code == 200
    assert chamadas == [1, 1, 2]


def test_valkey_compartilha_quota_empresa_entre_apps_concorrentes_e_reinicio(monkeypatch):
    """SlowAPI usa o Valkey real; só autenticação/auditoria do banco de produto são substituídas."""
    uri = os.environ.get("RAIZ_VALKEY_URL_TESTE", "redis://127.0.0.1:6379/15")
    prefixo = "teste-empresa-" + secrets.token_hex(16)
    monkeypatch.setenv("RATELIMIT_KEY_PREFIX", prefixo)
    apps = []

    def nova_app():
        app, _ = app_sem_banco(monkeypatch, uri, limite=7)
        assert app.state.limiter._key_prefix == prefixo
        apps.append(app)
        return app

    def recusada(resposta):
        assert resposta.status_code == 429
        assert 1 <= int(resposta.headers["retry-after"]) <= 60
        assert resposta.headers["content-type"].startswith("application/problem+json")
        assert resposta.json()["status"] == 429

    async def executar():
        async with (
            httpx.AsyncClient(transport=httpx.ASGITransport(app=nova_app()), base_url="http://teste") as primeira,
            httpx.AsyncClient(transport=httpx.ASGITransport(app=nova_app()), base_url="http://teste") as segunda,
        ):
            clientes = (primeira, segunda)
            empresa = {"X-Chave-API": "raiz_teste1"}
            # Ambas as instâncias atendem antes da rajada; sobram cinco chamadas no orçamento comum.
            for cliente in clientes:
                assert (await cliente.get("/conta", headers=empresa)).status_code == 200
            respostas = await asyncio.gather(*(clientes[i % 2].get("/conta", headers=empresa) for i in range(24)))
            assert sum(r.status_code == 200 for r in respostas) == 5
            negadas = [r for r in respostas if r.status_code != 200]
            assert len(negadas) == 19
            for resposta in negadas:
                recusada(resposta)

            # A segunda empresa tem seus próprios sete créditos de chamadas, entre as mesmas duas apps.
            outra = {"X-Chave-API": "raiz_teste2"}
            for i in range(7):
                assert (await clientes[i % 2].get("/conta", headers=outra)).status_code == 200
            recusada(await primeira.get("/conta", headers=outra))
            recusada(await segunda.get("/conta", headers=outra))

        # Uma instância nova não recupera a cota de nenhuma empresa: o estado está no Valkey.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=nova_app()), base_url="http://teste"
        ) as reiniciada:
            recusada(await reiniciada.get("/conta", headers=empresa))
            recusada(await reiniciada.get("/conta", headers=outra))

    try:
        asyncio.run(executar())
    finally:
        if apps:
            armazenamento = apps[0].state.limiter._storage
            padrao = armazenamento.prefixed_key(f"LIMITER/{prefixo}/*")
            # Nunca usar flushdb/reset: este banco também atende outros testes e processos.
            chaves = list(armazenamento.storage.scan_iter(match=padrao))
            if chaves:
                armazenamento.storage.delete(*chaves)
            for app in apps:
                app.state.limiter._storage.storage.close()
                app.state.limiter._storage.storage.connection_pool.disconnect()
