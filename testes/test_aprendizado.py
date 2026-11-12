"""Previsões congeladas e previsão contra gabarito (E8 passo 1)."""

import datetime as dt

import pandas as pd
import pytest
import sqlalchemy.exc
from sqlalchemy import create_engine, text

from raiz.aprendizado.congelar import ALVOS_MOTOR
from raiz.aprendizado.registro import (
    Previsao,
    Versoes,
    conferir_lote,
    hash_lote,
    placar,
    registrar_gabarito,
    registrar_lote,
)
from raiz.carga import carregar_pasta
from testes.conftest import AMOSTRA

CORTE = dt.date(2026, 11, 12)


def test_hash_do_lote_nao_depende_da_ordem():
    v = Versoes("m", "m-1", "e-1", CORTE)
    a = [Previsao("A", "x", 30, valor_num=1.5), Previsao("B", "x", 30, valor_texto="sim")]
    assert hash_lote(a, v) == hash_lote(list(reversed(a)), v)
    assert hash_lote(a, v) != hash_lote([Previsao("A", "x", 30, valor_num=1.6), a[1]], v)
    assert hash_lote(a, v) != hash_lote(a, Versoes("m", "m-2", "e-1", CORTE))


@pytest.mark.banco
class TestNoBanco:
    @pytest.fixture
    def engine(self, banco_url):
        eng = create_engine(banco_url)
        with eng.begin() as c:
            c.execute(text("truncate funil.rodada, funil.imovel cascade"))
        yield eng
        eng.dispose()

    def test_carga_congela_previsoes_do_motor(self, engine):
        # data de corte só deste teste: o mesmo arquivo com a mesma data daria o mesmo lote (já congelado)
        corte = CORTE + dt.timedelta(days=1)
        res = carregar_pasta(engine, AMOSTRA, corte)
        r = next(x for x in res if x.tipo == "municipio")
        df = pd.read_csv(AMOSTRA / "imoveis_1504950.csv")
        esperado = sum(df[a.coluna if a.coluna in df else a.coluna.replace("_rl", "_RL")].notna().sum()
                       for a in ALVOS_MOTOR if a.tabela == "resultado"
                       and (a.coluna in df or a.coluna.replace("_rl", "_RL") in df))  # fmt: skip
        esperado += 880  # filtro_territorial
        with engine.connect() as c:
            n = c.execute(text("select count(*) from aprendizado.previsao where lote_hash = :h"),
                          {"h": r.lote_previsoes}).scalar()  # fmt: skip
            assert n == esperado == r.previsoes_novas
            assert conferir_lote(c, r.lote_previsoes)
            versao, dc, horizonte = c.execute(text(
                "select modelo_versao, data_corte, horizonte_em from aprendizado.previsao "
                "where alvo = 'frente' and lote_hash = :h limit 1"), {"h": r.lote_previsoes}).one()  # fmt: skip
            assert versao.endswith("-suposta")  # saída pronta: não foi a Raíz que rodou o motor
            assert dc == corte and horizonte == corte + dt.timedelta(days=365)
            # booleano vira sim/não; frente vira texto
            assert set(c.execute(text("select distinct valor_texto from aprendizado.previsao where alvo='problema'")
                                 ).scalars()) <= {"sim", "não"}  # fmt: skip
        # recarregar não congela de novo
        res2 = carregar_pasta(engine, AMOSTRA, corte)
        assert next(x for x in res2 if x.tipo == "municipio").previsoes_novas == 0

    def test_previsao_congelada_nao_muda(self, engine):
        v = Versoes("teste", "t-1", "e-congelada", CORTE)
        with engine.begin() as c:
            lh, novo = registrar_lote(c, [Previsao("PA-X-1", "frente", 365, valor_texto="carbono")], v)
            assert novo
        for sql in ("update aprendizado.previsao set valor_texto = 'outra' where lote_hash = :h",
                    "delete from aprendizado.previsao where lote_hash = :h",
                    "delete from aprendizado.lote_previsao where lote_hash = :h",
                    "truncate aprendizado.previsao cascade"):  # fmt: skip
            with pytest.raises(sqlalchemy.exc.DBAPIError, match="congelada"), engine.begin() as c:
                c.execute(text(sql), {"h": lh})
        with engine.begin() as c:
            assert registrar_lote(c, [Previsao("PA-X-1", "frente", 365, valor_texto="carbono")], v) == (lh, False)

    def test_previsao_contra_gabarito(self, engine):
        v = Versoes("teste", "t-2", "e-gab", CORTE)
        ps = [
            Previsao("PA-G-1", "frente", 365, valor_texto="carbono"),
            Previsao("PA-G-1", "carbono_tco2_ano", 365, valor_num=900.0, p10=600.0, p50=900.0, p90=1200.0),
            Previsao("PA-G-2", "frente", 365, valor_texto="carbono"),
        ]
        with engine.begin() as c:
            registrar_lote(c, ps, v)
            # gabarito anterior à data de corte não vale (já era conhecido)
            registrar_gabarito(c, "PA-G-1", "frente", CORTE - dt.timedelta(days=10), "aceite", valor_texto="recusa")
            registrar_gabarito(c, "PA-G-1", "frente", CORTE + dt.timedelta(days=200), "aceite", valor_texto="carbono")
            # entre dois gabaritos válidos vale o mais perto do horizonte
            registrar_gabarito(c, "PA-G-1", "carbono_tco2_ano", CORTE + dt.timedelta(days=30), "campo", valor_num=100)
            registrar_gabarito(c, "PA-G-1", "carbono_tco2_ano", CORTE + dt.timedelta(days=360), "campo", valor_num=1000)
            registrar_gabarito(c, "PA-G-2", "frente", CORTE + dt.timedelta(days=100), "aceite", valor_texto="recusa")
        with engine.connect() as c:
            rows = {(r.cod_imovel, r.alvo): r for r in c.execute(text(
                "select * from aprendizado.previsao_contra_gabarito where modelo_versao = 't-2'"))}  # fmt: skip
            assert rows[("PA-G-1", "frente")].acertou is True
            g = rows[("PA-G-1", "carbono_tco2_ano")]
            assert g.real_num == 1000 and g.erro == 100 and g.dentro_p10_p90 is True
            assert rows[("PA-G-2", "frente")].acertou is False
            pl = {r.alvo: r for r in placar(c) if r.modelo_versao == "t-2"}
            assert pl["frente"].taxa_acerto == 0.5 and pl["frente"].com_gabarito == 2
