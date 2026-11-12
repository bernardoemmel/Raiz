"""Concorrência, débito único e recuperação da fila durável com PostgreSQL real."""

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, text

from raiz.pedidos.campos import CamposPedido
from raiz.publica import trabalhos as T

pytestmark = pytest.mark.banco


@pytest.fixture(scope="module")
def eng(request):
    # O banco especial evita compartilhar migrações e dados com testes paralelos de outros chats.
    url = os.environ.get("RAIZ_TRABALHOS_URL_TESTE") or request.getfixturevalue("banco_url")
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def empresa(eng):
    with eng.begin() as con:
        cid = con.execute(
            text("insert into negocio.cliente(rotulo,token_hmac) values('teste-fila',:h) returning id"),
            {"h": uuid.uuid4().hex},
        ).scalar_one()
        con.execute(
            text("""insert into negocio.conta_api(cliente_id,cnpj_hmac,cnpj_mascarado,termos_versao,
            saldo_rs,contrato_aceito_em,sinal_pago_em) values(:c,:h,'**.***.***/****-**','teste',2000,now(),now())"""),
            {"c": cid, "h": uuid.uuid4().hex},
        )
    yield cid
    with eng.begin() as con:
        con.execute(text("delete from negocio.pedido where cliente_id=:c"), {"c": cid})
        con.execute(text("delete from negocio.cliente where id=:c"), {"c": cid})


def _saldo(eng, cid):
    with eng.connect() as con:
        return float(
            con.execute(text("select saldo_rs from negocio.conta_api where cliente_id=:c"), {"c": cid}).scalar()
        )


def _pedidos(eng, cid):
    with eng.connect() as con:
        return con.execute(text("select count(*) from negocio.pedido where cliente_id=:c"), {"c": cid}).scalar()


def _servico(vinculo, cliente, corpo):
    """Grava efeito de negócio real pela mesma interface de conexão usada pelo serviço de lote."""
    pid = str(uuid.uuid4())
    with vinculo.begin() as con:
        con.execute(
            text("""insert into negocio.pedido(id,cliente_id,estado,campos,premissas_versao)
            values(:p,:c,'lote_montado',cast(:b as jsonb),'teste')"""),
            {"p": pid, "c": cliente, "b": json.dumps(corpo)},
        )
    with vinculo.connect() as con:
        assert con.execute(text("select id from negocio.pedido where id=:p"), {"p": pid}).scalar()
    return {"id": pid, "opcoes": [], "nome_proprietario": "não exportar"}


def test_submissao_nao_executa_trabalho_e_replay_nao_cobra(eng, empresa, monkeypatch):
    monkeypatch.setattr(T.S, "criar_pedido", lambda *a, **kw: pytest.fail("submissão não executa o solver"))
    inicio = time.monotonic()
    primeiro = T.submeter(eng, empresa, "pedir_lote", {}, "chave-teste-01")
    assert time.monotonic() - inicio < 5
    assert primeiro["estado"] == "submitted"
    assert T.submeter(eng, empresa, "pedir_lote", {}, "chave-teste-01") == primeiro
    assert _saldo(eng, empresa) == 1600
    assert _pedidos(eng, empresa) == 0
    with pytest.raises(T.ErroTrabalho) as erro:
        T.submeter(eng, empresa, "pedir_lote", {"meta": {"valor": 2}}, "chave-teste-01")
    assert erro.value.status == 409
    assert _saldo(eng, empresa) == 1600


def test_duas_submissoes_concorrentes_cobram_uma_vez(eng, empresa):
    with ThreadPoolExecutor(max_workers=2) as pool:
        futuros = [pool.submit(T.submeter, eng, empresa, "pedir_lote", {}, "chave-concorrente") for _ in range(2)]
        resultados = [f.result(timeout=5) for f in futuros]
    assert resultados[0] == resultados[1]
    assert _saldo(eng, empresa) == 1600


def test_saldo_insuficiente_nao_cria_pix_nem_operacao(eng, empresa, monkeypatch):
    monkeypatch.setattr(T.CT, "criar_cobranca", lambda *a, **kw: pytest.fail("não chamar Pix na submissão"))
    with eng.begin() as con:
        con.execute(text("update negocio.conta_api set saldo_rs=0 where cliente_id=:c"), {"c": empresa})
    with pytest.raises(T.ErroTrabalho) as erro:
        T.submeter(eng, empresa, "pedir_lote", {}, "sem-saldo-01")
    assert erro.value.status == 402
    assert erro.value.extra["recarga"]["pagador"] == "pessoa"
    assert _pedidos(eng, empresa) == 0


def test_worker_conclui_e_apenas_empresa_le_seu_resultado(eng, empresa, monkeypatch):
    monkeypatch.setattr(T.S, "criar_pedido", _servico)
    job = T.submeter(eng, empresa, "pedir_lote", {}, "worker-conclui")
    resultado = T.executar_proximo(eng)
    assert resultado["pedido_id"] == job["pedido_id"]
    assert resultado["estado"] == "completed"
    assert resultado["negocio_pedido_id"] == resultado["resultado"]["id"]
    assert "nome_proprietario" not in resultado["resultado"]
    assert _pedidos(eng, empresa) == 1
    assert T.executar_proximo(eng) is None
    assert T.obter(eng, empresa, job["pedido_id"]) == resultado
    with pytest.raises(T.ErroTrabalho) as erro:
        T.obter(eng, empresa + 100000, job["pedido_id"])
    assert erro.value.status == 404


def test_queda_apos_efeito_reverte_e_recupera_sem_duplicar(eng, empresa, monkeypatch):
    job = T.submeter(eng, empresa, "pedir_lote", {}, "queda-recuperada")
    codigo = """
import os
from sqlalchemy import create_engine
from raiz.publica import trabalhos as T
from testes.test_publica_trabalhos import _servico
def cair(vinculo, cliente, corpo):
    _servico(vinculo, cliente, corpo)
    os._exit(17)
T.S.criar_pedido = cair
T.executar_proximo(create_engine(os.environ['RAIZ_FILA_URL_TESTE']))
"""
    proc = subprocess.run(
        [sys.executable, "-c", codigo],
        env={**os.environ, "RAIZ_FILA_URL_TESTE": eng.url.render_as_string(hide_password=False)},
        capture_output=True,
        timeout=10,
    )
    assert proc.returncode == 17  # encerrou sem fechar contexto nem fazer rollback no Python
    assert _pedidos(eng, empresa) == 0
    assert T.obter(eng, empresa, job["pedido_id"])["estado"] == "working"
    assert T.executar_proximo(eng) is None  # a reivindicação não venceu ainda
    with eng.begin() as con:
        con.execute(
            text("update negocio.trabalho_api set lease_ate=now()-interval '1 second' where id=:i"),
            {"i": job["pedido_id"]},
        )
    monkeypatch.setattr(T.S, "criar_pedido", _servico)
    assert T.executar_proximo(eng)["estado"] == "completed"
    assert _pedidos(eng, empresa) == 1
    assert _saldo(eng, empresa) == 1600
    assert T.executar_proximo(eng) is None


def test_falha_reverte_efeito_e_estorna_uma_vez(eng, empresa, monkeypatch):
    def falhar(vinculo, cliente, corpo):
        _servico(vinculo, cliente, corpo)
        raise ValueError("texto privado de documento não pode entrar em log")

    job = T.submeter(eng, empresa, "pedir_lote", {}, "falha-estornada")
    monkeypatch.setattr(T.S, "criar_pedido", falhar)
    falha = T.executar_proximo(eng)
    assert falha["estado"] == "failed"
    assert "privado" not in json.dumps(falha)
    assert _pedidos(eng, empresa) == 0
    assert _saldo(eng, empresa) == 2000
    assert T.submeter(eng, empresa, "pedir_lote", {}, "falha-estornada") == falha
    assert T.executar_proximo(eng) is None
    assert _saldo(eng, empresa) == 2000
    assert falha["pedido_id"] == job["pedido_id"]


def test_cancelamento_antes_worker_estorna_sem_reexecucao(eng, empresa):
    job = T.submeter(eng, empresa, "pedir_lote", {}, "cancelar-antes")
    cancelado = T.cancelar(eng, empresa, job["pedido_id"])
    assert cancelado["estado"] == "canceled"
    assert T.cancelar(eng, empresa, job["pedido_id"]) == cancelado
    assert T.executar_proximo(eng) is None
    assert _saldo(eng, empresa) == 2000


def test_workers_pulam_trava_e_cancelamento_nao_promete_desfazer(eng, empresa, monkeypatch):
    entrou, liberar = threading.Event(), threading.Event()
    primeiro = T.submeter(eng, empresa, "pedir_lote", {"meta": {"valor": 1}}, "primeiro-worker")
    segundo = T.submeter(eng, empresa, "pedir_lote", {"meta": {"valor": 2}}, "segundo-worker")

    def demorado(vinculo, cliente, corpo):
        if corpo["meta"]["valor"] == 1:
            entrou.set()
            assert liberar.wait(10)
        return _servico(vinculo, cliente, corpo)

    monkeypatch.setattr(T.S, "criar_pedido", demorado)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futuro = pool.submit(T.executar_proximo, eng)
        try:
            assert entrou.wait(5)
            assert T.obter(eng, empresa, primeiro["pedido_id"])["estado"] == "working"
            outro = pool.submit(T.executar_proximo, eng).result(timeout=5)
            assert outro["pedido_id"] == segundo["pedido_id"]
            with pytest.raises(T.ErroTrabalho) as erro:
                T.cancelar(eng, empresa, primeiro["pedido_id"])
            assert erro.value.status == 409
        finally:
            liberar.set()
        assert futuro.result(timeout=5)["estado"] == "completed"
    assert _pedidos(eng, empresa) == 2


def test_reserva_so_prepara_para_pessoa(eng, empresa, monkeypatch):
    pedido = str(uuid.uuid4())
    recebido = []

    def reservar(vinculo, pid, cliente, por_agente=None, base_url=""):
        recebido.append((pid, cliente, por_agente, base_url))
        return {
            "pedido": pid,
            "aguardando_confirmacao": True,
            "pix": None,
            "pago": False,
            "aprovacao_url": "https://raiz.example/aprovar/token",
        }

    monkeypatch.setattr(T.S, "reservar", reservar)
    job = T.submeter(
        eng, empresa, "preparar_reserva", {"pedido_id": pedido, "base_url": "https://raiz.example"}, "reserva-humana"
    )
    resultado = T.executar_proximo(eng)
    assert resultado["estado"] == "input-required"
    assert resultado["resultado"]["pix"] is None
    assert recebido == [(pedido, empresa, f"operacao:{job['pedido_id']}", "https://raiz.example")]
    assert _saldo(eng, empresa) == 2000
    with pytest.raises(T.ErroTrabalho) as erro:
        T.cancelar(eng, empresa, job["pedido_id"])
    assert erro.value.status == 409


def test_liberacao_precisa_continuar_valida_no_worker(eng, empresa, monkeypatch):
    monkeypatch.setattr(T.S, "criar_pedido", lambda *a: pytest.fail("não executar conta bloqueada"))
    T.submeter(eng, empresa, "pedir_lote", {}, "liberacao-revogada")
    with eng.begin() as con:
        con.execute(
            text("update negocio.conta_api set bloqueada_em=now(),bloqueio_motivo='teste' where cliente_id=:c"),
            {"c": empresa},
        )
    assert T.executar_proximo(eng)["estado"] == "failed"
    assert _saldo(eng, empresa) == 2000


def test_servico_real_mantem_pedido_e_resultado_na_mesma_transacao(eng, empresa, monkeypatch):
    from raiz.pedidos import oferta

    monkeypatch.setattr(T.S, "_oferta", lambda *a: oferta.tabela([]))
    T.submeter(eng, empresa, "pedir_lote", CamposPedido().model_dump(mode="json"), "pedido-servico-real")
    resultado = T.executar_proximo(eng)
    assert resultado["estado"] == "completed", resultado
    assert _pedidos(eng, empresa) == 1
    assert resultado["resultado"] == {"id": resultado["negocio_pedido_id"]}
    with eng.connect() as con:
        salvo = con.execute(
            text("select resultado from negocio.trabalho_api where id=:i"), {"i": resultado["pedido_id"]}
        ).scalar_one()
    assert salvo["opcoes"] == []  # base vazia é dado honesto, sem opções inventadas
    assert salvo["status"] == "lote_montado"
