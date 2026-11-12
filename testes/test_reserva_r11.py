"""Piso de integridade e preço mínimo verificados contra o fluxo financeiro completo."""

import copy
import math

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from raiz import restauracao as R
from testes.test_restauracao import PERTO, R11, _linha


@pytest.mark.parametrize("cenario", list(R.regra()["cenarios"]["cenarios"]))
def test_piso_vinte_em_todos_cenarios_e_overrides(cenario):
    c = R.cenario(cenario, reserva_risco=0.01)
    assert c["reserva_risco"] == 0.20
    for medir in (True, False):
        bruto = {**c, "reserva_risco": 0.12, "reserva_por_fazenda": medir}
        assert R.nao_permanencia({}, bruto)["reserva"] == 0.20
        assert R.nao_permanencia({"fogo_anos_media": 0.0}, bruto)["reserva"] == 0.20


def test_teto_nao_reduz_piso_nem_reserva_pedida():
    r = copy.deepcopy(R.regra())
    r["nao_permanencia"]["teto"] = 0.10
    c = R.cenario()
    assert R.nao_permanencia({"fogo_anos_media": 40}, c, r)["reserva"] == 0.20
    assert R.nao_permanencia({"fogo_anos_media": 0}, {**c, "reserva_risco": 0.7}, r)["reserva"] == 0.7


@pytest.mark.parametrize("invalida", [math.nan, math.inf, -0.1, 1.1])
def test_reserva_invalida_nao_vira_credito(invalida):
    with pytest.raises(ValueError, match="reserva_risco"):
        R.cenario(reserva_risco=invalida)
    with pytest.raises(ValueError, match="reserva_risco"):
        R.nao_permanencia({}, {**R.cenario(), "reserva_risco": invalida})


def test_desconto_usa_piso_e_risco_maior_sobe_reserva():
    c = {**R.cenario(), "reserva_risco": 0.12}
    base, risco = R.por_imovel(_linha(fogo_anos_media=0), c), R.por_imovel(_linha(fogo_anos_media=10), c)
    assert base["reserva_risco_pct"] == 20
    assert risco["reserva_risco_pct"] > 20
    assert risco["credito_liquido_tco2_contrato"] < base["credito_liquido_tco2_contrato"]


@pytest.mark.parametrize("perto", [False, True])
def test_preco_minimo_remunera_fluxo_completo_ao_alvo(perto):
    li, c = _linha(**(PERTO if perto else {})), R.cenario(**R11)
    out, _ = R.calcular(li, c)
    for alvo in (12, 15):
        for tipo in ("projeto", "alavancada"):
            p = out[f"preco_minimo_tir_{alvo}_{tipo}_usd_t"]
            assert p is not None and p > 0
            # Refaz a receita, o pagamento ao dono e o ICSD pelo preço encontrado: não reaproveita a aproximação.
            alto = R.calcular(li, {**c, "preco_usd_t": p})[1]["sim"]
            baixo = R.calcular(li, {**c, "preco_usd_t": p - 0.02})[1]["sim"]
            desconto = (1 + alvo / 100) ** -alto["anos"].astype(float)
            fluxo = "F" if tipo == "projeto" else "L"
            assert alto[fluxo][0] @ desconto >= -1e-6
            assert baixo[fluxo][0] @ desconto < 0
            assert alto[f"tir_{tipo}"][0] == pytest.approx(alvo / 100, abs=0.0001)
    assert out["preco_minimo_tir_15_projeto_usd_t"] > out["preco_minimo_tir_12_projeto_usd_t"]


def test_preco_minimo_respeita_duas_fases_com_venda_na_fase_um():
    c = R.cenario(**R11, pagamento_dono="duas_fases", fase1_anos=8)
    li = _linha(**PERTO)
    out, _ = R.calcular(li, c)
    p = out["preco_minimo_tir_12_alavancada_usd_t"]
    assert R.calcular(li, {**c, "preco_usd_t": p})[1]["sim"]["tir_alavancada"][0] == pytest.approx(0.12, abs=0.0001)


def test_sem_credito_preco_alvo_indisponivel():
    out = R.por_imovel(_linha(pasto_ha=0, alem_RL_ha=0))
    assert all(v is None for k, v in out.items() if k.startswith("preco_minimo_tir_"))


def test_pasto_desconhecido_nao_usa_toda_area_livre():
    li = _linha(pasto_ha=np.nan)
    out = R.por_imovel(li)
    assert out["restauracao_area_ha"] == 0
    assert out["restauracao_area_situacao"] == "pendente_pasto"
    assert "pasto_ha" in out["restauracao_faltou"].split(",")
    assert R.por_imovel({**li, "mb_pasto_2025_ha": 40})["restauracao_area_ha"] == 40
    assert R.por_imovel(_linha(pasto_ha=1))["restauracao_area_ha"] == 1  # pequenas permanecem


@pytest.mark.parametrize("ha", [0, 0.01, 1, 100])
def test_area_fisica_limita_previsao_sem_descartar_pequenas(ha):
    out = R.por_imovel(_linha(ha=ha, pasto_ha=100, alem_RL_ha=100))
    assert out["restauracao_area_ha"] == ha
    assert sum(out[f"restauracao_{m}_ha"] for m in R.regra()["modos"]) == pytest.approx(ha)
    if ha < 100:
        assert "area_imovel_inconsistente" in out["restauracao_faltou"].split(",")
    if ha > 0:
        assert out["credito_liquido_tco2_contrato"] > 0


@given(ha=st.floats(0, 1000), pasto=st.floats(0, 1000), livre=st.floats(0, 1000))
def test_area_nunca_excede_imovel_pasto_ou_area_livre(ha, pasto, livre):
    area = R.area_restauravel(_linha(ha=ha, pasto_ha=pasto, alem_RL_ha=livre))
    assert 0 <= area <= min(ha, pasto, livre)


def test_area_fisica_ausente_e_invalida_sao_explicitas():
    sem = R.por_imovel(_linha())
    assert sem["restauracao_area_ha"] == 100
    assert "area_imovel" in sem["restauracao_faltou"].split(",")
    invalida = R.por_imovel(_linha(ha=-1))
    assert invalida["restauracao_area_ha"] == 0
    assert "area_imovel_invalida" in invalida["restauracao_faltou"].split(",")
