"""Parâmetros legais versionados: consulta por data e rótulos, e conferência com as regras que hoje estão no motor."""

import sys

import pytest

from raiz import MOTOR_DIR
from raiz.regras import ParametroAusente, parametros

P = parametros()
UFS = [
    "AC",
    "AL",
    "AM",
    "AP",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MG",
    "MS",
    "MT",
    "PA",
    "PB",
    "PE",
    "PI",
    "PR",
    "RJ",
    "RN",
    "RO",
    "RR",
    "RS",
    "SC",
    "SE",
    "SP",
    "TO",
]
BIOMAS = ["Amazônia", "Cerrado", "Caatinga", "Mata Atlântica", "Pampa", "Pantanal"]


@pytest.fixture(scope="module")
def motor(tmp_path_factory):
    import os

    antes = os.getcwd()
    os.chdir(tmp_path_factory.mktemp("motor"))  # o motor cria cache/ ao ser importado
    sys.path.insert(0, str(MOTOR_DIR))
    import raiz_estado

    yield raiz_estado
    os.chdir(antes)


def test_versao_nomeada():
    assert P.versao.startswith("regras-2026b+") and len(P.versao.split("+")[1]) == 8


def test_reserva_legal_igual_ao_motor(motor):
    for uf in UFS:
        for b in BIOMAS:
            assert P.rl_percentual(uf, b) == motor.pct_rl(uf, b), (uf, b)


def test_escadinha_e_teto_iguais_ao_motor():
    # motor (raiz_estado/raiz_app): até 1 MF 5 m, até 2 MF 8 m, até 4 MF 15 m, até 10 MF 20 m, acima 30 m (sem largura)
    casos = [(0.5, 5), (1, 5), (1.01, 8), (2, 8), (3.9, 15), (4, 15), (4.5, 20), (10, 20), (10.5, 30), (50, 30)]
    for mf, m in casos:
        assert P.escadinha_m(mf) == m, mf
    assert P.escadinha_m(12, largura_rio_m=120) == 60 and P.escadinha_m(12, largura_rio_m=400) == 100
    assert (P.teto_61b(1.5), P.teto_61b(3), P.teto_61b(4.1)) == (0.10, 0.20, None)


def test_vigencia_e_pendente():
    assert P.valor("rl_percentual", "2026-11-12", amazonia_legal=True, vegetacao="floresta") == 80
    with pytest.raises(ParametroAusente):  # antes da lei não há valor
        P.valor("rl_percentual", "2010-01-01", amazonia_legal=True, vegetacao="floresta")
    with pytest.raises(ParametroAusente):  # valor pendente nunca é devolvido
        P.valor("marco_temporal", corte="segundo_corte_do_plano")
    r = P.registro("app_teto_61b", mf_ate=2)
    assert r.urn == "urn:lex:br:federal:lei:2012-05-25;12651!art61b_inc1" and r.artigo == "art. 61-B, I"


@pytest.mark.banco
def test_publicar_no_banco(banco_url):
    from sqlalchemy import create_engine, text

    from raiz.regras import publicar

    eng = create_engine(banco_url)
    with eng.begin() as c:
        c.execute(text("truncate regras.parametro, regras.versao"))
        v, nova = publicar(c)
        assert nova and publicar(c) == (v, False)
        assert c.execute(text("select count(*) from regras.parametro where versao = :v"), {"v": v}).scalar() == len(
            P.valores
        )
        assert (
            c.execute(
                text(
                    "select valor from regras.parametro where parametro = 'app_teto_61b' "
                    "and rotulos = '{\"mf_ate\": 2}'"
                )
            ).scalar()
            == 10
        )
    eng.dispose()
