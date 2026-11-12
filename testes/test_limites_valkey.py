"""Dois workers e uma contagem real no Valkey do CI; nunca limpa o banco inteiro."""

import asyncio
import os
import secrets
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raiz.limites import LimiteCompartilhado
from raiz.seguranca_api import SegurancaAPI


def _app(backend, **opcoes):
    app = FastAPI()

    @app.get("/ok")
    @app.post("/entrar")
    def ok():
        return {"ok": True}

    app.add_middleware(SegurancaAPI, backend=backend, **opcoes)
    return app


def test_contagem_atomica_compartilhada_concorrente_com_log_real():
    from raiz.logs_seguros import sanitizar_log
    from raiz.privacidade import configurar_log

    configurar_log()
    assert "indisponível" not in sanitizar_log("modelo aquecido")

    async def rodar():
        chave = secrets.token_hex(32)
        url = os.environ.get("RAIZ_VALKEY_URL_TESTE", "redis://127.0.0.1:6379/15")
        backends = [LimiteCompartilhado(url, chave) for _ in range(2)]
        clientes = [
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=_app(b, limite=7, janela=60)), base_url="http://testserver"
            )
            for b in backends
        ]
        try:
            respostas = await asyncio.gather(*(clientes[i % 2].get("/ok") for i in range(50)))
            assert sum(r.status_code == 200 for r in respostas) == 7
            negadas = [r for r in respostas if r.status_code == 429]
            assert len(negadas) == 43
            assert all(1 <= int(r.headers["retry-after"]) <= 60 for r in negadas)
            identificador = backends[0].identificador("127.0.0.1")
            assert "127.0.0.1" not in identificador
            assert 0 < await backends[0].cliente.ttl(identificador) <= 60
            # Reiniciar um worker não reinicia o orçamento.
            novo = LimiteCompartilhado(url, chave)
            try:
                assert await novo.espera("127.0.0.1", False, 7, 10, 60) > 0
            finally:
                await novo.fechar()
        finally:
            await backends[0].cliente.delete(backends[0].identificador("127.0.0.1"))
            for cliente in clientes:
                await cliente.aclose()
            for backend in backends:
                await backend.fechar()

    asyncio.run(rodar())


def test_janela_real_expira_sem_confundir_com_duracao_da_rajada():
    async def rodar():
        url = os.environ.get("RAIZ_VALKEY_URL_TESTE", "redis://127.0.0.1:6379/15")
        backend = LimiteCompartilhado(url, secrets.token_hex(32))
        ip = "192.0.2.10"
        try:
            assert await backend.espera(ip, False, 1, 1, 1) == 0
            assert await backend.espera(ip, False, 1, 1, 1) == 1
            await asyncio.sleep(1.05)
            assert await backend.espera(ip, False, 1, 1, 1) == 0
        finally:
            await backend.cliente.delete(backend.identificador(ip))
            await backend.fechar()

    asyncio.run(rodar())


def test_login_compartilhado_preserva_orcamento_geral():
    async def rodar():
        url = os.environ.get("RAIZ_VALKEY_URL_TESTE", "redis://127.0.0.1:6379/15")
        chave = secrets.token_hex(32)
        a, b = LimiteCompartilhado(url, chave), LimiteCompartilhado(url, chave)
        try:
            assert await a.espera("192.0.2.9", True, 5, 1, 60) == 0
            assert await b.espera("192.0.2.9", True, 5, 1, 60) > 0
            assert await b.espera("192.0.2.9", False, 5, 1, 60) == 0
            assert await a.cliente.hget(a.identificador("192.0.2.9"), "total") == b"2"
        finally:
            await a.cliente.delete(a.identificador("192.0.2.9"))
            await a.fechar()
            await b.fechar()

    asyncio.run(rodar())


def test_falha_no_valkey_nao_desliga_limite():
    class ForaDoAr:
        async def espera(self, *args):
            raise ConnectionError("URL com senha que não deve sair")

    cliente = TestClient(_app(ForaDoAr()))
    for _ in range(2):
        resposta = cliente.get("/ok")
        assert resposta.status_code == 503
        assert resposta.headers["retry-after"] == "1"
        assert resposta.headers["x-frame-options"] == "DENY"
        assert "senha" not in resposta.text


def test_backend_recusa_chave_fraca_e_protocolo_errado():
    with pytest.raises(ValueError, match="32 bytes"):
        LimiteCompartilhado("redis://localhost", "curta")
    with pytest.raises(ValueError, match="Valkey"):
        LimiteCompartilhado("https://localhost", secrets.token_hex(32))


def test_servidor_travado_falha_fechado_sem_repeticoes_demorradas():
    async def rodar():
        encerrar = asyncio.Event()
        conexoes = []

        async def travar(_leitor, escritor):
            conexoes.append(escritor)
            await encerrar.wait()
            escritor.close()
            await escritor.wait_closed()

        servidor = await asyncio.start_server(travar, "127.0.0.1", 0)
        porta = servidor.sockets[0].getsockname()[1]
        backend = LimiteCompartilhado(f"redis://127.0.0.1:{porta}/0", secrets.token_hex(32))
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=_app(backend)), base_url="http://testserver"
            ) as cliente:
                inicio = time.monotonic()
                resposta = await cliente.get("/ok")
                assert resposta.status_code == 503
                assert resposta.headers["retry-after"] == "1"
                assert time.monotonic() - inicio < 3
                assert len(conexoes) == 1
        finally:
            encerrar.set()
            await backend.fechar()
            servidor.close()
            await servidor.wait_closed()

    asyncio.run(rodar())
