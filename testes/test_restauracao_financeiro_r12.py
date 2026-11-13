import numpy as np
import pytest

from raiz import restauracao_divida as D
from raiz import restauracao_financeiro as F


def test_aluguel_reproduz_censo_corrigido_sem_chamar_preco_de_mercado():
    r = F.aluguel_sfx()
    assert r["brl_ha_ano"] == pytest.approx(842.83, abs=0.005)
    assert r["rotulo"] == "Censo 2017 corrigido"
    assert r["nao_e_preco_mercado_2026"]


def test_operacoes_reais_separam_taxa_fixa_tlp_e_estresse():
    for nome, juros, car, amo in (
        ("regreen_jequitiba", 0.012, 36, 264),
        ("mombak_angico_branco", 0.023, 36, 264),
        ("symbiosis", 0.023, 60, 240),
    ):
        r = F.operacao(nome)
        assert (r["juros_ano"], r["carencia_meses"], r["amortizacao_meses"]) == (juros, car, amo)
        assert F.operacao(nome, estresse=True)["juros_ano"] == 0.0494
    with pytest.raises(ValueError, match="universal"):
        F.operacao("fundo_clima")


def test_preco_ponderado_pelo_volume_e_faixa_hectares():
    r = F.referencias_comprador()
    assert r["profloresta_1"]["media_ponderada_usd_t"] == pytest.approx(59.20)
    assert r["hectares_por_milhao"]["min"] == 4400
    assert r["hectares_por_milhao"]["max"] == pytest.approx(5076.9230769)


def test_certidao_conjunta_nao_soma_inteiro_teor_e_area_geo_e_explicita():
    r = F.custos_terra(matriculas=2, tipo_certidao="conjunta", area_georreferenciar_ha=100)
    assert r["certidoes_brl"] == pytest.approx(392.5)
    assert r["georreferenciamento_brl"] == pytest.approx(10478)
    assert F.orcamento_mudas(1)["min_brl"] == pytest.approx(5834.5)
    assert F.orcamento_mudas(1)["max_brl"] == pytest.approx(34273.52)
    assert not F.orcamento_mudas(1)["somar_ao_sfb"]


def test_verra_abate_adiantamento_sem_usar_credito_de_verificacao_futura():
    r = F.taxas_verra([0, 1000, 100000], [1, 2])
    assert r["fluxo_usd"][0] == 5250
    assert r["fluxo_usd"][1] == 5000
    assert r["memoria"][1]["adiantamento_abatido_usd"] == pytest.approx(230)
    assert r["fluxo_usd"][2] == pytest.approx(5000 + 23000 - 4770)
    with pytest.raises(ValueError, match="sem verificação"):
        F.taxas_verra([1000, 0], [1])


def test_divida_mensal_respeita_icsd_quita_e_preserva_conta_reserva():
    capex = np.zeros(301)
    capex[0] = 100000
    caixa = np.full(301, 1000.0)
    caixa[:37] = 0
    r = D.dimensionar(capex, caixa, juros_ano=0.023, carencia_meses=36, amortizacao_meses=264)
    assert r["fracao"] == pytest.approx(0.5, abs=1e-6)
    assert max(r["servico"][:37]) == 0
    assert r["saldo_devedor"][-1] == pytest.approx(0, abs=0.01)
    assert min(x for x in r["icsd"] if x is not None) >= 1.3 - 1e-5
    assert max(r["conta_reserva"]) > 0
    assert sum(r["movimento_reserva"]) == pytest.approx(0, abs=1e-5)
    assert sum(r["fluxo_financiamento"]) == pytest.approx(r["valor_financiado"] - sum(r["servico"]), abs=0.01)
    saldo = np.array(r["saldo_devedor"])
    np.testing.assert_allclose(saldo[1:], saldo[:-1] * (1.023 ** (1 / 12)) + 0.5 * capex - r["servico"], atol=0.02)


def test_nao_esconde_juros_fora_da_carencia_quando_primeira_venda_e_ano_sete():
    k = np.zeros(26)
    k[0] = 1000
    caixa = np.zeros(26)
    caixa[[7, 12, 17, 22, 25]] = 1000
    r = D.dimensionar(k, caixa, juros_ano=0.023, carencia_meses=36, amortizacao_meses=264, periodos_ano=1)
    assert r["valor_financiado"] == 0
    assert r["motivo_sem_divida"]


def test_classe_medida_ou_emitida_exige_evidencia_e_contrato_nao_certifica():
    r = D.classificar_volume(100, "modelado", "contratado", modelo_versao="teste")
    assert r["classe_volume"] == "modelado" and not r["habilita_comercializacao"]
    with pytest.raises(ValueError, match="evidência"):
        D.classificar_volume(100, "medido", "sem_contrato", modelo_versao="teste")
    with pytest.raises(ValueError, match="emissão"):
        D.classificar_volume(100, "modelado", "entregue", modelo_versao="teste")


def test_motor_r12_preserva_estoque_e_registra_curva_custos_e_classe():
    import json

    from raiz import restauracao as R
    from testes.test_restauracao import _linha

    li = _linha(cod_municipio_ibge=1507300, area_ha=150, vazamento_mitigacao=True)
    r = R.regra()
    c = R.cenario("central_r12", cambio_brl_usd=5.4)
    m = R.modos(li, r)
    a = R.captura(li, m, r, R.cenario("central_r11"))
    b = R.captura(li, m, r, c)
    assert b["bruto_ano"][:4].sum() > a["bruto_ano"][:4].sum()
    assert b["bruto_ano"][:8].sum() == pytest.approx(a["bruto_ano"][:8].sum())
    assert b["bruto_ano"].sum() == pytest.approx(a["bruto_ano"].sum())
    out = R.por_imovel(li, c, r)
    assert out["divida_fracao"] == 0
    assert out["vazamento_pct"] == 10  # booleano antigo não prova destino
    assert out["arrendamento_referencia_rs_ha_ano"] == pytest.approx(842.83, abs=0.005)
    assert out["credito_classe"] == "modelado"
    terra = json.loads(out["provisao_terra_json"])
    assert terra["georreferenciamento_brl"] == pytest.approx(150 * 104.78)
    assert terra["pendencias"]
    curva = R._curva_p50(out, c, r)
    assert curva["bruto_tco2_ha"][1] > 0
    assert c["juros_ano"] == 0.023 and c["carencia_anos"] == 3


def test_lote_cobra_taxas_verra_uma_vez_e_nao_duplica_emissao():
    from raiz import restauracao as R

    c = R.cenario("central_r12", cambio_brl_usd=1)
    vendidos = np.zeros(41)
    vendidos[7] = 10000
    f = -vendidos * 0.23
    parte = dict(area_ha=1, F=f, K=np.zeros(41), B=np.zeros(41), vendidos=vendidos)
    lote = R.fluxo_lote([parte, parte], c)
    assert lote["F"][0] == -5250
    assert lote["F"][7] == pytest.approx(-5000 - 4600 + 2500)
    assert lote["taxas_verra"]["memoria"][7]["toneladas_liquidas_buffer"] == 20000
