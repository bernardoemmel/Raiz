import numpy as np
import pytest

from raiz import restauracao as R
from raiz import restauracao_evidencias as E


def test_5511_reproduz_verificacao_e_guarda_cada_denominador():
    r = E.descontos(
        329303.66, 0.1657553, 0.0481216, 0, 0.12, historico=True, fonte_historica=E.fontes()["vcs5511"]["url"]
    )
    assert r["liquido_tco2e"] == pytest.approx(230120, abs=1)
    assert r["liquido_tco2e"] == pytest.approx(230119.90, abs=0.02)
    b, u, v, s = r["etapas"]
    assert b["denominador_tco2e"] == 329303.66
    assert u["denominador_tco2e"] == pytest.approx(274719.833045602)
    assert v["denominador_tco2e"] == pytest.approx(261499.875127715)
    assert s["denominador_tco2e"] == v["saldo_tco2e"]
    assert s["fracao"] == 0.12


def test_5511_historico_nao_baixa_reserva_do_novo_lote():
    historico = E.cenario_contabil("verificado_5511", 329303.66, planejamento=False)
    novo = E.cenario_contabil("verificado_5511", 329303.66)
    assert historico["fracao_liquida"] == pytest.approx(0.6988, abs=0.00001)
    assert novo["reserva_aplicada"] == 0.20
    assert novo["liquido_tco2e"] == pytest.approx(209199.90, abs=0.02)
    assert not novo["habilita_comercializacao"]
    assert E.cenario_contabil("conservador_plantio_pasto", 100)["liquido_tco2e"] == pytest.approx(57)


@pytest.mark.parametrize("entrada", [float("nan"), -1, 1.01, True])
def test_percentual_invalido_nao_vira_credito(entrada):
    with pytest.raises(ValueError):
        E.descontos(100, entrada, 0, 0, 0.2)


def test_vazamento_absoluto_nao_pode_exceder_adicional_e_historico_exige_fonte():
    with pytest.raises(ValueError, match="excede"):
        E.descontos(100, 0.5, 0, 51, 0.2)
    with pytest.raises(ValueError, match="fonte"):
        E.descontos(100, 0, 0, 0, 0.12, historico=True)


def test_mombak_confronta_acumulado_periodo_e_preserva_total_curva():
    original = R.forma_curva() * 588.8
    anual, rel = E.calibrar_inicio_plantio(original)
    assert anual.sum() == pytest.approx(original.sum())
    assert anual[:8].sum() == pytest.approx(original[:8].sum())
    assert np.all(anual >= 0)
    np.testing.assert_allclose(anual[8:], original[8:])
    candiru, irmaos = rel["comparacoes"]
    assert candiru["remocao_tco2e_ha"] == pytest.approx(26.3573988289)
    assert irmaos["remocao_tco2e_ha"] == pytest.approx(32.2641618497)
    assert candiru["mitigacao_calculada_tco2e"] == pytest.approx(105.336)
    assert irmaos["mitigacao_calculada_tco2e"] == pytest.approx(35.568)
    # Observações são do período inteiro, não taxas anuais de 26–32 t/ha.
    assert 2 < candiru["idade_projeto_anos"] < 3
    assert 2 < irmaos["idade_projeto_anos"] < 3
    assert anual[1] > 0 and anual[2] > 0
    assert not rel["validacao_independente"]
    assert rel["rotulo"] == "estimativa regional, não medida na fazenda"
    for comparacao in rel["comparacoes"]:
        assert abs(comparacao["diferenca_ajustada_tco2e_ha"]) < abs(comparacao["diferenca_anterior_tco2e_ha"])


def test_zero_de_carbono_nao_vira_remocao_por_calibracao():
    anual, _ = E.calibrar_inicio_plantio(np.zeros(41))
    assert anual.sum() == 0
