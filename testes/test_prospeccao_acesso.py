"""Créditos de consulta só pagos, consumo concorrente, privacidade e limites reais."""

import datetime as dt
import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, text

from raiz import prospeccao_acesso as A
from raiz.busca import normalizar_codigo
from raiz.pedidos import pix
from raiz.pedidos.servico import criar_cliente

CATALOGO = [{"id": "avulsa", "nome": "Consulta", "creditos": 1, "valor_rs": 12.34}]


@pytest.fixture
def catalogo(monkeypatch):
    monkeypatch.setenv("RAIZ_PROSPECCAO_PLANOS", json.dumps(CATALOGO))
    monkeypatch.setattr(pix, "chave", lambda: "chave-de-teste-unitario")


def test_catalogo_sem_inventar_preco_ou_liberar_pagamento(monkeypatch):
    monkeypatch.delenv("RAIZ_PROSPECCAO_PLANOS", raising=False)
    monkeypatch.setattr(pix, "chave", lambda: None)
    assert A.planos()["planos"] == []
    assert not A.planos()["pagamento_disponivel"]
    assert A.planos()["custo_ficha"] == 1


@pytest.mark.parametrize("valor", ["NaN", "Infinity", -1, 0, 0.001, None])
def test_catalogo_rejeita_precos_invalidos(monkeypatch, valor):
    monkeypatch.setenv("RAIZ_PROSPECCAO_PLANOS", json.dumps([{**CATALOGO[0], "valor_rs": valor}]))
    with pytest.raises(A.ErroAcesso) as erro:
        A.planos()
    assert erro.value.status == 503


@pytest.fixture
def eng(banco_url):
    engine = create_engine(banco_url)
    yield engine
    engine.dispose()


@pytest.fixture
def cliente(eng):
    return criar_cliente(eng, "Cliente de teste")[0]


@pytest.fixture
def fazendas(eng):
    codigos = ["PA-1504950-" + uuid.uuid4().hex.upper() for _ in range(3)]
    with eng.begin() as con:
        rodada = con.execute(
            text("""insert into funil.rodada
                    (tipo, uf, cod_municipio, origem, arquivos, hash_entradas,
                     motor_versao, regras_versao, data_corte)
                    values ('municipio','PA',1504950,'teste','{}',:h,'teste','teste','2026-11-12')
                    returning id"""),
            {"h": str(uuid.uuid4())},
        ).scalar_one()
        for codigo in codigos:
            con.execute(
                text("""insert into funil.vigente(cod_imovel, rodada_id, cod_municipio_ibge, uf, cod_busca)
                        values (:car, :rodada, 1504950, 'PA', :busca)"""),
                {"car": codigo, "rodada": rodada, "busca": normalizar_codigo(codigo)},
            )
    return codigos


@pytest.fixture
def provedor(catalogo, monkeypatch):
    criadas = []

    def criar(valor, descricao, validade):
        criada = pix.Cobranca(
            f"pix_{uuid.uuid4()}",
            "producao",
            valor,
            "codigo-pix-de-teste-unitario",
            dt.datetime.now(dt.UTC) + dt.timedelta(seconds=validade),
        )
        criadas.append(criada)
        return criada

    monkeypatch.setattr(pix, "criar", criar)
    monkeypatch.setattr(pix, "conferir", lambda _ident: "pendente")
    return criadas


def _pagar(eng, cliente, monkeypatch):
    compra = A.iniciar_compra(eng, cliente, "avulsa", str(uuid.uuid4()))
    monkeypatch.setattr(pix, "conferir", lambda _ident: "paga")
    assert A.conferir_compra(eng, cliente, compra["id"])["estado"] == "paga"
    return compra


@pytest.mark.banco
def test_compra_idempotente_e_saldo_so_apos_confirmacao(eng, cliente, provedor, monkeypatch):
    chave = str(uuid.uuid4())
    compra = A.iniciar_compra(eng, cliente, "avulsa", chave)
    assert A.iniciar_compra(eng, cliente, "avulsa", chave) == compra
    assert len(provedor) == 1
    assert A.saldo(eng, cliente)["creditos"] == 0
    assert A.conferir_compra(eng, cliente, compra["id"])["estado"] == "pendente"
    assert A.saldo(eng, cliente)["creditos"] == 0
    monkeypatch.setattr(pix, "conferir", lambda _ident: "paga")
    with ThreadPoolExecutor(max_workers=5) as pool:
        pagos = list(pool.map(lambda _: A.conferir_compra(eng, cliente, compra["id"]), range(8)))
    assert all(p["estado"] == "paga" for p in pagos)
    assert A.saldo(eng, cliente)["creditos"] == 1
    with eng.connect() as con:
        assert (
            con.execute(
                text("select count(*) from negocio.prospeccao_movimento where compra_id = :id"), {"id": compra["id"]}
            ).scalar_one()
            == 1
        )
    with pytest.raises(A.ErroAcesso) as erro:
        A.iniciar_compra(eng, cliente, "outro-plano", chave)
    assert erro.value.status == 409
    outro = criar_cliente(eng, "Outro cliente de teste")[0]
    with pytest.raises(A.ErroAcesso) as erro:
        A.conferir_compra(eng, outro, compra["id"])
    assert erro.value.status == 404


@pytest.mark.banco
def test_pagamento_de_teste_nao_cria_credito_pago(eng, cliente, provedor, monkeypatch):
    monkeypatch.setattr(
        pix,
        "criar",
        lambda *_: pix.Cobranca(
            "teste_invalido", "teste", 12.34, "teste", dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)
        ),
    )
    with pytest.raises(A.ErroAcesso) as erro:
        A.iniciar_compra(eng, cliente, "avulsa", str(uuid.uuid4()))
    assert erro.value.status == 503
    assert A.saldo(eng, cliente)["creditos"] == 0


@pytest.mark.banco
def test_recupera_compras_do_cliente_apos_sair_da_tela(eng, cliente, provedor, monkeypatch):
    outro = criar_cliente(eng, "Outro cliente do histórico")[0]
    assert A.listar_compras(eng, cliente) == []
    antiga = A.iniciar_compra(eng, cliente, "avulsa", str(uuid.uuid4()))
    for _ in range(22):
        _pagar(eng, cliente, monkeypatch)
    privada = A.iniciar_compra(eng, outro, "avulsa", str(uuid.uuid4()))
    recuperadas = A.listar_compras(eng, cliente)
    assert len(recuperadas) == 20
    assert recuperadas[0] == antiga  # pendente mais antiga não é escondida pelas pagas
    assert privada["id"] not in {c["id"] for c in recuperadas}
    assert all("externo_id" not in c for c in recuperadas)
    A.conferir_compra(eng, cliente, recuperadas[0]["id"])
    assert A.saldo(eng, cliente)["creditos"] == 23


@pytest.mark.banco
@pytest.mark.parametrize("estado", ["expirada", "cancelada"])
def test_cobranca_encerrada_nao_credita_e_reconciliacao_tardia_e_idempotente(
    eng, cliente, provedor, monkeypatch, estado
):
    compra = A.iniciar_compra(eng, cliente, "avulsa", str(uuid.uuid4()))
    monkeypatch.setattr(pix, "conferir", lambda _ident: estado)
    assert A.conferir_compra(eng, cliente, compra["id"])["estado"] == estado
    assert A.saldo(eng, cliente)["creditos"] == 0
    # Se o provedor corrigir o estado para pago, o pagamento entra uma única vez.
    monkeypatch.setattr(pix, "conferir", lambda _ident: "paga")
    A.conferir_compra(eng, cliente, compra["id"])
    A.conferir_compra(eng, cliente, compra["id"])
    assert A.saldo(eng, cliente)["creditos"] == 1


@pytest.mark.banco
def test_desbloqueio_e_releitura_concorrentes_nao_debitam_duas_vezes(eng, cliente, provedor, fazendas, monkeypatch):
    _pagar(eng, cliente, monkeypatch)
    car = fazendas[0]
    with ThreadPoolExecutor(max_workers=5) as pool:
        respostas = list(pool.map(lambda _: A.desbloquear(eng, cliente, normalizar_codigo(car).lower()), range(8)))
    assert sum(r["cobrado"] for r in respostas) == 1
    assert {r["codigo_car"] for r in respostas} == {car}
    assert A.exigir_desbloqueio(eng, cliente, car) == car
    assert A.saldo(eng, cliente) == {"creditos": 0, "fichas_desbloqueadas": 1}
    with eng.connect() as con:
        assert (
            con.execute(
                text("select sum(quantidade) from negocio.prospeccao_movimento where cliente_id = :c"), {"c": cliente}
            ).scalar_one()
            == 0
        )
    for funcao in (A.desbloquear, A.exigir_desbloqueio, A.pedir_contato):
        with pytest.raises(A.ErroAcesso) as erro:
            funcao(eng, cliente, fazendas[1])
        assert erro.value.status == 402


@pytest.mark.banco
def test_ultimo_credito_nao_pode_liberar_duas_fazendas(eng, cliente, provedor, fazendas, monkeypatch):
    _pagar(eng, cliente, monkeypatch)

    def tentar(car):
        try:
            return A.desbloquear(eng, cliente, car)["desbloqueada"]
        except A.ErroAcesso as erro:
            assert erro.status == 402
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(tentar, fazendas[:2])) == 1
    assert A.saldo(eng, cliente) == {"creditos": 0, "fichas_desbloqueadas": 1}


@pytest.mark.banco
def test_contato_interno_idempotente_e_reserva_bloqueia_releitura(eng, cliente, provedor, fazendas, monkeypatch):
    _pagar(eng, cliente, monkeypatch)
    car = fazendas[0]
    A.desbloquear(eng, cliente, car)
    pedido = A.pedir_contato(eng, cliente, car)
    assert A.pedir_contato(eng, cliente, car) == pedido
    assert pedido["estado"] == "recebido"
    assert set(pedido) == {"id", "codigo_car", "estado", "criado_em", "mensagem"}
    with eng.connect() as con:
        assert (
            con.execute(
                text("select count(*) from negocio.contato_fila where cod_imovel = :car"), {"car": car}
            ).scalar_one()
            == 0
        )  # nenhum disparo é autorizado pelo botão
    outro = criar_cliente(eng, "Cliente com reserva")[0]
    with eng.begin() as con:
        pid = uuid.uuid4()
        con.execute(
            text("insert into negocio.pedido(id, cliente_id, campos) values (:p, :c, '{}')"), {"p": pid, "c": outro}
        )
        rid = con.execute(
            text("""insert into negocio.reserva(pedido_id, cliente_id, estado, ha, valor_rs, dias)
                    values (:p, :c, 'ativa', 1, 1, 30) returning id"""),
            {"p": pid, "c": outro},
        ).scalar_one()
        con.execute(
            text("insert into negocio.reserva_fazenda(reserva_id, cod_imovel, ativa) values (:r, :car, true)"),
            {"r": rid, "car": car},
        )
    for funcao in (A.desbloquear, A.exigir_desbloqueio, A.pedir_contato):
        with pytest.raises(A.ErroAcesso) as erro:
            funcao(eng, cliente, car)
        assert erro.value.status == 404


@pytest.mark.banco
def test_nao_cobra_por_car_inexistente(eng, cliente, provedor, monkeypatch):
    _pagar(eng, cliente, monkeypatch)
    with pytest.raises(A.ErroAcesso) as erro:
        A.desbloquear(eng, cliente, "CAR-inexistente")
    assert erro.value.status == 404
    assert A.saldo(eng, cliente)["creditos"] == 1


@pytest.mark.banco
def test_limite_persistente_resiste_concorrencia_e_expira(eng):
    chave = f"cliente:{uuid.uuid4()}"

    def tentar(_):
        try:
            A.limitar(eng, chave, "ficha", 3, 60)
            return True
        except A.ErroAcesso as erro:
            assert erro.status == 429 and 1 <= erro.retry_after <= 60
            return False

    with ThreadPoolExecutor(max_workers=5) as pool:
        assert sum(pool.map(tentar, range(10))) == 3
    with eng.begin() as con:
        limite = con.execute(text("select * from negocio.prospeccao_limite where acao = 'ficha'")).one()
        assert limite.quantidade == 10 and chave not in str(limite)
        con.execute(text("update negocio.prospeccao_limite set expira_em = now() - interval '1 second'"))
    A.limitar(eng, chave, "ficha", 3, 60)
