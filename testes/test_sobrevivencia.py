"""Tempo até o aceite: recusa competitiva, censura e ausência de vazamento temporal."""

import datetime as dt
import uuid

import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from raiz.pedidos import sobrevivencia as S

CORTE = dt.datetime(2020, 6, 1, tzinfo=dt.UTC)


def _obs(dias, desfecho, i=0, espera=0):
    fim = CORTE - dt.timedelta(days=espera) if desfecho else CORTE
    return S.Observacao("pedido-teste", f"CAR-TESTE-{i}", fim - dt.timedelta(days=dias), fim, desfecho)


def _ajustar(especificacoes):
    obs = [_obs(d, e, i) for i, (d, e) in enumerate(especificacoes)]
    return S.ajustar(obs, CORTE, minimo_contatos=1, minimo_aceites=1)


def test_recusa_e_competitiva_nao_censura():
    curva = _ajustar([(1, 2), (2, 1), (10, 0), (10, 0)])
    assert curva.chance(3) == pytest.approx(0.25)  # recusa como censura daria 1/3
    assert curva.chance(10) == pytest.approx(0.25)
    assert curva.chance(2, espera_dias=1) == pytest.approx(1 / 3)
    assert curva.mediana_dias is None
    assert curva.chance(11) is None
    assert curva.chance(10, espera_dias=1) is None
    assert curva.chance(0) == 0


def test_empate_entre_aceite_recusa_e_censura_sem_jitter():
    curva = _ajustar([(1, 1), (1, 2), (1, 0)])
    assert curva.chance(1) == pytest.approx(1 / 3)
    assert curva.tempos == (0.0, 1.0)
    assert curva.sobrevivencia[-1] == pytest.approx(1 / 3)
    assert curva.versao == _ajustar([(1, 1), (1, 2), (1, 0)]).versao


def test_aceite_imediato_e_mediana():
    curva = _ajustar([(0, 1), (2, 1), (10, 0), (10, 0)])
    assert curva.chance(1) == pytest.approx(0.25)
    assert curva.mediana_dias == 2
    assert curva.chance(3, espera_dias=1) == pytest.approx(1 / 3)


def test_pouco_dado_e_validacoes():
    assert S.ajustar([_obs(2, 1)], CORTE) is None
    assert S.ajustar([_obs(10, 0, i) for i in range(40)], CORTE) is None
    obs = _obs(2, 1)
    with pytest.raises(ValueError, match="repetido"):
        S.ajustar([obs, obs], CORTE)
    with pytest.raises(ValueError, match="posterior"):
        S.ajustar([_obs(2, 1, espera=-1)], CORTE)
    with pytest.raises(ValueError, match="inválida"):
        S.ajustar([S.Observacao("p", "c", CORTE + dt.timedelta(days=1), CORTE, 0)], CORTE)
    with pytest.raises(ValueError, match="censurada"):
        S.ajustar([S.Observacao("p", "c", CORTE - dt.timedelta(days=3), CORTE - dt.timedelta(days=1), 0)], CORTE)
    with pytest.raises(ValueError, match="fuso"):
        S.ajustar([], CORTE.replace(tzinfo=None))
    curva = _ajustar([(1, 1)])
    with pytest.raises(ValueError, match="finitos"):
        curva.chance(float("nan"))


def test_cli_sem_dado_e_sem_gravacao(monkeypatch):
    import contextlib

    import typer

    from raiz.aprendizado.cli_sobrevivencia import registrar

    class Con(contextlib.AbstractContextManager):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execution_options(self, **kw):
            assert kw["isolation_level"] == "REPEATABLE READ"
            return self

        def begin(self):
            return contextlib.nullcontext()

    class Engine:
        def connect(self):
            return Con()

    monkeypatch.setattr("raiz.banco.engine", Engine)
    monkeypatch.setattr(S, "historico", lambda con, corte: [])
    app = typer.Typer()
    registrar(app)
    result = CliRunner().invoke(app, ["sobrevivencia-aceite", "--corte", CORTE.isoformat()])
    assert result.exit_code == 0 and "Pouco dado" in result.stdout
    result = CliRunner().invoke(app, ["sobrevivencia-aceite", "--corte", "2020-06-01"])
    assert result.exit_code == 2 and "fuso" in result.output


def _pedido(con, prefixo):
    cliente = con.execute(
        text("""insert into negocio.cliente (rotulo, token_hmac)
                               values ('teste sobrevivencia', :h) returning id"""),
        {"h": prefixo},
    ).scalar_one()
    pedido = uuid.uuid4()
    con.execute(
        text("insert into negocio.pedido (id, cliente_id, campos) values (:p, :c, '{}')"), {"p": pedido, "c": cliente}
    )
    onda = con.execute(
        text("""insert into negocio.onda (pedido_id, numero, fazendas, prazo, criada_em)
                               values (:p, 1, 50, :c, :i) returning id"""),
        {"p": pedido, "c": CORTE, "i": CORTE - dt.timedelta(days=60)},
    ).scalar_one()
    return pedido, onda


def _contato(con, pedido, onda, cod, idade=10, simulado=False):
    con.execute(
        text("""insert into negocio.contato_fila
                        (pedido_id, onda_id, cod_imovel, canal, simulado, enviado_em)
                        values (:p, :o, :c, 'teste', :s, :i)"""),
        {"p": pedido, "o": onda, "c": cod, "s": simulado, "i": CORTE - dt.timedelta(days=idade)},
    )


def _evento(con, pedido, cod, nivel, ocorrido, registrado=None):
    con.execute(
        text("""insert into negocio.interesse_evento
                        (pedido_id, cod_imovel, nivel, ocorrido_em, registrado_em)
                        values (:p, :c, :n, :o, :r)"""),
        {"p": pedido, "c": cod, "n": nivel, "o": ocorrido, "r": registrado or ocorrido},
    )


@pytest.mark.banco
def test_historico_real_por_corte_sem_estado_atual_e_congelamento(con):
    prefixo = f"SOBREV-{uuid.uuid4().hex[:8]}"
    pedido, onda = _pedido(con, prefixo)
    for i in range(40):
        cod = f"{prefixo}-{i}"
        _contato(con, pedido, onda, cod, idade=20 if i != 39 else 2)
        if i < 10:
            _evento(con, pedido, cod, "aceite_fase1", CORTE - dt.timedelta(days=15))
            _evento(con, pedido, cod, "contrato_firme", CORTE - dt.timedelta(days=14))
        elif i < 20:
            _evento(con, pedido, cod, "recusou", CORTE - dt.timedelta(days=16))
    _contato(con, pedido, onda, f"{prefixo}-simulado", simulado=True)
    _evento(con, pedido, f"{prefixo}-simulado", "aceite_fase1", CORTE - dt.timedelta(days=1))
    # O evento já aconteceu, mas só será conhecido depois; tampouco vale evento de outro pedido ou sem pedido.
    _evento(con, pedido, f"{prefixo}-39", "aceite_fase1", CORTE - dt.timedelta(days=1), CORTE + dt.timedelta(days=1))
    outro, _ = _pedido(con, f"{prefixo}-outro")
    _evento(con, outro, f"{prefixo}-39", "recusou", CORTE - dt.timedelta(days=1))
    _evento(con, None, f"{prefixo}-39", "recusou", CORTE - dt.timedelta(days=1))
    _evento(con, pedido, f"{prefixo}-38", "sem_resposta", CORTE - dt.timedelta(days=1))
    con.execute(text("update negocio.contato_fila set estado = 'respondido' where pedido_id = :p"), {"p": pedido})
    observacoes = [o for o in S.historico(con, CORTE) if o.pedido_id == str(pedido)]
    assert len(observacoes) == 40
    assert sum(o.desfecho == 1 for o in observacoes) == 10
    assert sum(o.desfecho == 2 for o in observacoes) == 10
    assert sum(o.desfecho == 0 for o in observacoes) == 20
    assert next(o for o in observacoes if o.cod_imovel.endswith("-39")).dias == 2
    curva = S.ajustar(observacoes, CORTE)
    assert curva is not None and curva.chance(14) == pytest.approx(10 / 39)
    r = S.congelar_pendentes(con, observacoes, curva, 14, "backtest")
    assert r == {"lotes_novos": 1, "previsoes_novas": 1, "sem_suporte": 19}
    r = S.congelar_pendentes(con, observacoes, curva, 14, "backtest")
    assert r["previsoes_novas"] == 0
    gravada = con.execute(
        text("""select * from aprendizado.previsao where modelo = :m and cod_imovel = :c"""),
        {"m": S.MODELO, "c": f"{prefixo}-39"},
    ).one()
    assert gravada.tipo == "backtest" and gravada.modelo_versao == curva.versao
    assert gravada.distribuicao["pedido_id"] == str(pedido)
    assert gravada.distribuicao["recusa_competitiva"] is True
    assert gravada.distribuicao["espera_dias"] == 2
    assert gravada.valor_num == pytest.approx(10 / 39)

    # A aferição cruza o pedido, o envio e o prazo congelados. O evento tardio
    # anterior ao corte é separado, mesmo tendo ocorrido antes da previsão.
    assert not S.avaliar(con, CORTE + dt.timedelta(days=10))["por_versao"]
    medido = S.avaliar(con, CORTE + dt.timedelta(days=15))
    assert medido["desfechos_anteriores_conhecidos_tardiamente"] == 1
    assert not medido["por_versao"]
    for sufixo, dias in (("novo-no-prazo", 5), ("novo-fora-prazo", 20)):
        cod = f"{prefixo}-{sufixo}"
        _contato(con, pedido, onda, cod, idade=2)
        pendente = S.Observacao(str(pedido), cod, CORTE - dt.timedelta(days=2), CORTE, 0)
        S.congelar_pendentes(con, [pendente], curva, 14, "backtest")
        _evento(con, pedido, cod, "aceite_fase1", CORTE + dt.timedelta(days=dias))
    placar = S.avaliar(con, CORTE + dt.timedelta(days=30))["por_versao"][curva.versao]
    assert placar["previsoes"] == 2 and placar["aceites_no_prazo"] == 1
    assert placar["brier"] == pytest.approx(((10 / 39 - 1) ** 2 + (10 / 39) ** 2) / 2)
