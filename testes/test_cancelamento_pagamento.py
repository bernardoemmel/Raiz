"""Pagamento observado é durável; cancelamento de agente nunca decide dinheiro ou exclusividade."""

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, text

from raiz import salvaguardas as SG
from raiz.pedidos import servico as S
from raiz.publica import conta as CT
from raiz.publica import trabalhos as T
from raiz.publica.rotas_agentes import cancelar_idempotente

pytestmark = pytest.mark.banco


@pytest.fixture(scope="module")
def eng(request):
    engine = create_engine(os.environ.get("RAIZ_CANCELAMENTO_URL_TESTE") or request.getfixturevalue("banco_url"))
    yield engine
    engine.dispose()


@pytest.fixture
def empresa(eng):
    with eng.begin() as con:
        cid = con.execute(
            text("insert into negocio.cliente(rotulo,token_hmac) values('teste-cancelamento',:h) returning id"),
            {"h": uuid.uuid4().hex},
        ).scalar_one()
        con.execute(
            text("""insert into negocio.conta_api(cliente_id,cnpj_hmac,cnpj_mascarado,termos_versao,
            saldo_rs,contrato_aceito_em,sinal_pago_em,reservar_habilitado)
            values(:c,:h,'**.***.***/****-**','teste',2000,now(),now(),true)"""),
            {"c": cid, "h": uuid.uuid4().hex},
        )
        con.execute(
            text("""insert into negocio.webhook_inscricao(id,cliente_id,url_cifrada,segredo_cifrado)
            values(:i,:c,:v,:v)"""),
            {"i": str(uuid.uuid4()), "c": cid, "v": b"teste-nao-entregar"},
        )
    yield cid
    with eng.begin() as con:
        cods = list(
            con.execute(
                text("""select f.cod_imovel from negocio.pedido_fazenda f
        join negocio.pedido p on p.id=f.pedido_id where p.cliente_id=:c"""),
                {"c": cid},
            ).scalars()
        )
        con.execute(text("delete from negocio.reserva where cliente_id=:c"), {"c": cid})
        con.execute(text("delete from negocio.pedido where cliente_id=:c"), {"c": cid})
        con.execute(text("delete from negocio.cliente where id=:c"), {"c": cid})
        con.execute(text("delete from funil.imovel where cod_imovel=any(:cs) and uf='ZZ'"), {"cs": cods})


def _reserva(eng, cid, *, cobranca=True, cod=None):
    pid, externo = str(uuid.uuid4()), uuid.uuid4().hex
    cod = cod or uuid.uuid4().hex
    with eng.begin() as con:
        # Evidências sintéticas explícitas; os testes financeiros passam pela salvaguarda real.
        ev = SG.Evidencia(sha256="a" * 64, data=S._agora().date())
        verificacao = SG.Verificacao(verificacao=ev, territorio_tradicional=False)
        con.execute(
            text("""insert into funil.imovel(cod_imovel,uf,geom) values(:f,'ZZ',
        ST_Multi(ST_GeomFromText('POLYGON((-47 -1,-46.99 -1,-46.99 -0.99,-47 -0.99,-47 -1))',4674)))
        on conflict (cod_imovel) do nothing"""),
            {"f": cod},
        )
        con.execute(
            text("""insert into negocio.salvaguarda(cod_imovel,evidencia) values(:f,cast(:e as jsonb))
        on conflict (cod_imovel) do nothing"""),
            {"f": cod, "e": verificacao.model_dump_json()},
        )
        con.execute(
            text("""insert into geo.redd_cobertura(uf,verificada_em,valida_ate,evidencia)
        values('ZZ',current_date,current_date,cast(:e as jsonb)) on conflict (uf) do update
        set verificada_em=current_date,valida_ate=current_date,evidencia=excluded.evidencia"""),
            {"e": ev.model_dump_json()},
        )
        con.execute(
            text("""insert into negocio.pedido(id,cliente_id,estado,campos)
            values(:p,:c,'grupo_pronto','{}')"""),
            {"p": pid, "c": cid},
        )
        con.execute(
            text("insert into negocio.pedido_fazenda(pedido_id,cod_imovel,papel) values(:p,:f,'lote')"),
            {"p": pid, "f": cod},
        )
        rid = con.execute(
            text("""insert into negocio.reserva(pedido_id,cliente_id,estado,ha,valor_rs,dias,
            confirmacao_hash,confirmacao_token_cifrado,confirmacao_expira,preco_valido_ate)
            values(:p,:c,:s,10,100,30,:h,:v,now()+interval '1 day',now()+interval '1 day') returning id"""),
            {
                "p": pid,
                "c": cid,
                "s": "aguardando_pagamento" if cobranca else "aguardando_confirmacao",
                "h": uuid.uuid4().hex,
                "v": b"link-cifrado-teste",
            },
        ).scalar_one()
        con.execute(
            text("insert into negocio.reserva_fazenda(reserva_id,cod_imovel) values(:r,:f)"),
            {"r": rid, "f": cod},
        )
        if cobranca:
            con.execute(
                text("""insert into negocio.cobranca(reserva_id,provedor,modo,externo_id,valor_rs,estado,expira_em)
                values(:r,'teste','teste',:x,100,'pendente',now()+interval '1 day')"""),
                {"r": rid, "x": externo},
            )
    return pid, rid, externo


def _estado(eng, rid):
    with eng.connect() as con:
        return con.execute(
            text("""select r.estado,p.estado,c.estado,rf.ativa from negocio.reserva r
            join negocio.pedido p on p.id=r.pedido_id join negocio.cobranca c on c.reserva_id=r.id
            join negocio.reserva_fazenda rf on rf.reserva_id=r.id where r.id=:r"""),
            {"r": rid},
        ).one()


def test_cancelamento_concorrente_idempotente_estorna_uma_vez(eng, empresa):
    job = T.submeter(eng, empresa, "pedir_lote", {}, "submeter-cancelavel")
    with ThreadPoolExecutor(max_workers=2) as pool:
        respostas = list(
            pool.map(lambda _: cancelar_idempotente(eng, empresa, job["pedido_id"], "cancelar-uma-vez"), range(2))
        )
    assert respostas[0] == respostas[1]
    assert respostas[0]["estado"] == "canceled"
    with eng.connect() as con:
        assert (
            con.execute(text("select saldo_rs from negocio.conta_api where cliente_id=:c"), {"c": empresa}).scalar()
            == 2000
        )
        assert (
            con.execute(
                text("select count(*) from negocio.cancelamento_api where cliente_id=:c"), {"c": empresa}
            ).scalar()
            == 1
        )
        assert (
            con.execute(
                text("""select count(*) from negocio.webhook_entrega where cliente_id=:c
        and convert_from(corpo,'UTF8')::jsonb->'data'->>'estado'='cancelado'"""),
                {"c": empresa},
            ).scalar()
            == 1
        )
    with pytest.raises(CT.ErroConta) as erro:
        cancelar_idempotente(eng, empresa, str(uuid.uuid4()), "cancelar-uma-vez")
    assert erro.value.status == 409


def test_cancelar_pre_reserva_apaga_link_sem_pagar_e_isola_empresa(eng, empresa):
    pid, rid, _ = _reserva(eng, empresa, cobranca=False)
    with pytest.raises(CT.ErroConta) as erro:
        cancelar_idempotente(eng, empresa + 100000, pid, "outra-empresa")
    assert erro.value.status == 404
    assert cancelar_idempotente(eng, empresa, pid, "cancelar-pre-reserva")["estado"] == "canceled"
    with eng.connect() as con:
        r = con.execute(
            text("select estado,confirmacao_hash,confirmacao_token_cifrado from negocio.reserva where id=:r"),
            {"r": rid},
        ).one()
        assert tuple(r) == ("cancelada", None, None)
        assert not con.execute(text("select 1 from negocio.cobranca where reserva_id=:r"), {"r": rid}).first()


def test_cancelamento_e_confirmacao_concorrentes_preservam_decisao_humana(eng, empresa):
    pid, rid, externo = _reserva(eng, empresa)
    largada = threading.Barrier(2)

    def cancelar():
        largada.wait(5)
        return cancelar_idempotente(eng, empresa, pid, "cancelamento-vs-pix")

    def pagar():
        largada.wait(5)
        return S.confirmar_pagamento(eng, externo)

    with ThreadPoolExecutor(max_workers=2) as pool:
        fc, fp = pool.submit(cancelar), pool.submit(pagar)
        assert fc.result(5)["estado"] == "input-required"
        assert fp.result(5) == "ativa"
    assert tuple(_estado(eng, rid)) == ("ativa", "reservado", "paga", True)
    assert S.confirmar_pagamento(eng, externo) == "ja_paga"
    with eng.connect() as con:
        assert (
            con.execute(
                text("select count(*) from negocio.reserva_evento where reserva_id=:r and evento='paga'"), {"r": rid}
            ).scalar()
            == 1
        )


@pytest.mark.parametrize(
    "alteracao,motivo",
    [
        ("update negocio.cobranca set expira_em=now()-interval '1 second' where reserva_id=:r", "prazo_vencido"),
        ("update negocio.reserva set preco_valido_ate=now()-interval '1 second' where id=:r", "prazo_vencido"),
        ("update negocio.cobranca set valor_rs=200 where reserva_id=:r", "cobranca_divergente"),
        ("update negocio.reserva set estado='cancelada' where id=:r", "estado_alterado"),
        ("update negocio.reserva set estado='expirada' where id=:r", "estado_alterado"),
        ("update negocio.pedido set estado='cancelado' where id=:p", "estado_alterado"),
        ("delete from negocio.pedido_fazenda where pedido_id=:p", "grupo_alterado"),
    ],
)
def test_pagamento_divergente_fica_registrado_sem_exclusividade(eng, empresa, alteracao, motivo):
    pid, rid, externo = _reserva(eng, empresa)
    with eng.begin() as con:
        con.execute(text(alteracao), {"r": rid, "p": pid})
    assert S.confirmar_pagamento(eng, externo) == "input-required"
    assert _estado(eng, rid)[2:] == ("paga", False)
    assert S.confirmar_pagamento(eng, externo) == "ja_paga"
    with eng.connect() as con:
        detalhe = con.execute(
            text("select detalhe from negocio.reserva_evento where reserva_id=:r"), {"r": rid}
        ).scalar_one()
        assert detalhe == {"motivo": motivo, "estado": "input-required", "pagamento_confirmado": True}
        assert (
            con.execute(
                text("select count(*) from negocio.webhook_entrega where cliente_id=:c"), {"c": empresa}
            ).scalar()
            == 1
        )


def test_pagamento_concorrente_so_uma_reserva_ganha_exclusividade(eng, empresa):
    cod = uuid.uuid4().hex
    _, rid1, externo1 = _reserva(eng, empresa, cod=cod)
    _, rid2, externo2 = _reserva(eng, empresa, cod=cod)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futuros = [pool.submit(S.confirmar_pagamento, eng, x) for x in (externo1, externo2)]
        assert sorted(f.result(5) for f in futuros) == ["ativa", "conflito"]
    estados = [_estado(eng, rid1), _estado(eng, rid2)]
    assert all(r[2] == "paga" for r in estados)
    assert sum(r[3] for r in estados) == 1


def test_falha_de_outbox_reverte_e_retry_confirma_tudo(eng, empresa, monkeypatch):
    from raiz.publica import webhooks

    _, rid, externo = _reserva(eng, empresa)
    original = webhooks.enfileirar
    monkeypatch.setattr(webhooks, "enfileirar", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("falha teste")))
    with pytest.raises(RuntimeError):
        S.confirmar_pagamento(eng, externo)
    assert tuple(_estado(eng, rid)) == ("aguardando_pagamento", "grupo_pronto", "pendente", False)
    monkeypatch.setattr(webhooks, "enfileirar", original)
    assert S.confirmar_pagamento(eng, externo) == "ativa"


def test_revogacao_administrativa_antes_worker_impede_reserva(eng, empresa, monkeypatch):
    monkeypatch.setattr(S, "reservar", lambda *a, **k: pytest.fail("administrador revogou reservar"))
    T.submeter(eng, empresa, "preparar_reserva", {"pedido_id": str(uuid.uuid4())}, "reserva-revogada")
    with eng.begin() as con:
        con.execute(text("update negocio.conta_api set reservar_habilitado=false where cliente_id=:c"), {"c": empresa})
    resultado = T.executar_proximo(eng)
    assert resultado["estado"] == "failed"
    assert resultado["erro"]["status"] == 403


@pytest.mark.parametrize("acao", ["expirar", "converter"])
def test_expiracao_conversao_nao_invertem_travas_com_replay_pago(eng, empresa, acao):
    import datetime as dt

    from sqlalchemy import event

    pid, rid, externo = _reserva(eng, empresa)
    assert S.confirmar_pagamento(eng, externo) == "ativa"
    aguardando_pedido = threading.Event()

    def observar(con, cursor, statement, parameters, context, executemany):
        sql = statement.lower()
        if threading.current_thread().name.startswith("writer-reserva") and "negocio.pedido" in sql:
            if "for update" in sql or "update negocio.pedido" in sql:
                aguardando_pedido.set()

    event.listen(eng, "before_cursor_execute", observar)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="writer-reserva") as pool:
            with eng.begin() as con:
                con.execute(text("select id from negocio.pedido where id=:p for update"), {"p": pid})
                futuro = (
                    pool.submit(S.expirar_reservas, eng, S._agora() + dt.timedelta(days=31))
                    if acao == "expirar"
                    else (pool.submit(S.converter_reserva, eng, rid, 10))
                )
                assert aguardando_pedido.wait(3)
                # O writer aguarda pedido sem reter reserva: replay consegue seguir sem ciclo de deadlock.
                con.execute(text("select id from negocio.reserva where id=:r for update nowait"), {"r": rid})
                assert S.confirmar_pagamento(T.ConexaoVinculada(con), externo) == "ja_paga"
            resultado = futuro.result(3)
        assert resultado == 1 if acao == "expirar" else resultado["abatido_rs"] == 100
        estado = _estado(eng, rid)
        assert estado[:2] == (("expirada", "reserva_vencida") if acao == "expirar" else ("convertida", "contrato"))
        assert estado[3] is (acao == "converter")
    finally:
        event.remove(eng, "before_cursor_execute", observar)


def test_fechamento_atrasado_nao_troca_grupo_pago(eng, empresa, monkeypatch):
    import pandas as pd
    from sqlalchemy import event

    from raiz.pedidos.campos import CamposPedido

    pid, rid, externo = _reserva(eng, empresa)
    with eng.connect() as con:
        antigo = dict(S._linha_pedido(con, pid, empresa))
        grupo = S._grupo(con, pid)
    antigo["estado"] = "buscando_interesse"  # avanço que iniciou antes de outro fechamento
    monkeypatch.setattr(S, "_oferta", lambda *a: pd.DataFrame([{"cod_imovel": "nova-fazenda", "area_ha": 10}]))
    monkeypatch.setattr(S.A, "chances", lambda *a: [1])
    monkeypatch.setattr(S.Z, "resolver", lambda *a: {"sel": [0]})
    pagamento_travado, liberar_pagamento, fechamento_chegou = (threading.Event() for _ in range(3))

    def depois(con, cursor, statement, parameters, context, executemany):
        if (
            threading.current_thread().name.startswith("pagar-grupo")
            and "negocio.pedido" in statement
            and "for update" in statement
        ):
            pagamento_travado.set()
            assert liberar_pagamento.wait(5)

    def antes(con, cursor, statement, parameters, context, executemany):
        if threading.current_thread().name.startswith("fechar-grupo") and "negocio.pedido" in statement:
            fechamento_chegou.set()

    event.listen(eng, "after_cursor_execute", depois)
    event.listen(eng, "before_cursor_execute", antes)
    try:
        with (
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="pagar-grupo") as pagador,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="fechar-grupo") as fechador,
        ):
            pagamento = pagador.submit(S.confirmar_pagamento, eng, externo)
            assert pagamento_travado.wait(3)
            fechamento = fechador.submit(
                S._fechar_grupo, eng, antigo, CamposPedido(), {"niveis": {"nova-fazenda": "interessado"}}, S._agora()
            )
            try:
                assert fechamento_chegou.wait(3)
            finally:
                liberar_pagamento.set()
            assert pagamento.result(3) == "ativa"
            fechamento.result(3)
        with eng.connect() as con:
            assert S._grupo(con, pid) == grupo
        assert _estado(eng, rid)[:2] == ("ativa", "reservado")
    finally:
        liberar_pagamento.set()
        event.remove(eng, "after_cursor_execute", depois)
        event.remove(eng, "before_cursor_execute", antes)


def test_aprovacao_revalida_token_depois_de_aguardar_pedido(eng, empresa, monkeypatch):
    from sqlalchemy import event

    from raiz.publica.aprovacao import ErroAprovacao, aprovar

    pid, rid, _ = _reserva(eng, empresa, cobranca=False)
    token = uuid.uuid4().hex
    with eng.begin() as con:
        con.execute(text("update negocio.reserva set confirmacao_hash=:h where id=:r"), {"h": S._hash(token), "r": rid})
    monkeypatch.setattr(S, "_cobrar", lambda *a, **k: pytest.fail("token revogado não gera Pix"))
    aguardando_pedido = threading.Event()

    def observar(con, cursor, statement, parameters, context, executemany):
        if (
            threading.current_thread().name.startswith("aprovar-grupo")
            and "negocio.pedido" in statement
            and "for update" in statement
        ):
            aguardando_pedido.set()

    event.listen(eng, "before_cursor_execute", observar)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="aprovar-grupo") as pool:
            with eng.begin() as con:
                con.execute(text("select id from negocio.pedido where id=:p for update"), {"p": pid})
                futuro = pool.submit(aprovar, eng, token, empresa)
                assert aguardando_pedido.wait(3)
                con.execute(
                    text("""update negocio.reserva set estado='cancelada',confirmacao_hash=null,
                confirmacao_token_cifrado=null where id=:r"""),
                    {"r": rid},
                )
            with pytest.raises(ErroAprovacao) as erro:
                futuro.result(3)
            assert erro.value.status == 410
    finally:
        event.remove(eng, "before_cursor_execute", observar)


def test_pagamento_com_salvaguarda_vencida_apos_aprovacao_exige_revisao(eng, empresa):
    pid, rid, externo = _reserva(eng, empresa)
    with eng.connect() as con:
        grupo = S._grupo(con, pid)
    SG.exigir_para_reserva(eng, grupo)  # evidência válida quando a pessoa aprovou a cobrança
    with eng.begin() as con:
        con.execute(
            text("""update geo.redd_cobertura set verificada_em=current_date-2,
        valida_ate=current_date-1 where uf='ZZ'""")
        )
    assert S.confirmar_pagamento(eng, externo) == "input-required"
    assert tuple(_estado(eng, rid)) == ("conflito", "grupo_pronto", "paga", False)
    with eng.connect() as con:
        detalhe = con.execute(
            text("select detalhe from negocio.reserva_evento where reserva_id=:r"), {"r": rid}
        ).scalar_one()
    assert detalhe["motivo"] == "salvaguarda_pendente"
    assert detalhe["pagamento_confirmado"] is True
