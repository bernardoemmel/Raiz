"""Ficha paga: nenhum dado pessoal, quantis preservados e fonte/data sem precisão inventada."""

import json

import pytest

from raiz.imovel_dados import ficha_prospeccao


def _linha(**novos):
    return {
        "cod_imovel": "PA-1504950-" + "A" * 32,
        "cod_municipio_ibge": 1504950,
        "municipio": "Mojuí dos Campos",
        "uf": "PA",
        "bioma": "Amazônia",
        "ha": 20,
        "m_fiscal": 0.2,
        "restauracao_area_ha": 5,
        "credito_liquido_tco2_ha_contrato_p10": 100,
        "credito_liquido_tco2_ha_contrato_p50": 150,
        "credito_liquido_tco2_ha_contrato_p90": 210,
        "restauracao_versao": "restauracao-2026a+abc",
        "tir_alavancada_pct_p10": -100,
        "tir_alavancada_pct_p50": 12.5,
        "tir_alavancada_pct_p90": 22,
        **novos,
    }


def test_credito_liquido_contrato_e_tir_preservam_quantils():
    ficha = ficha_prospeccao(_linha(), {"data_corte": "2026-11-12"})
    assert [ficha["credito"][p]["valor"] for p in ("p10", "p50", "p90")] == [500, 750, 1050]
    assert ficha["credito"]["base"] == "liquido_contrato"
    assert ficha["credito"]["p50"]["unidade"] == "tCO2e/contrato"
    assert ficha["credito"]["versao_modelo"] == "restauracao-2026a+abc"
    assert ficha["tir"]["tipo"] == "com_financiamento"
    assert ficha["tir"]["p10"]["valor"] == -100
    assert ficha["agrupamento"]["pequena"] is True
    assert ficha["agrupamento"]["imoveis"]["valor"] is None


def test_corte_nao_vira_data_da_fonte():
    ficha = ficha_prospeccao(_linha(data_atualizacao="2025-08-03"), {"data_corte": "2026-11-12"})
    assert ficha["area_total"]["data_referencia"] == "2025-08-03"
    medida = ficha["credito"]["p50"]
    assert medida["data_referencia"] is None
    assert medida["data_corte"] == "2026-11-12"
    assert medida["estimado"] is True and medida["fonte"]


def test_sem_medicao_de_terra_nao_inventa_posse_ou_risco():
    ficha = ficha_prospeccao(_linha())
    assert ficha["caminho_terra"]["codigo"] == "sem_dados"
    assert ficha["risco"]["nivel"] is None
    derivada = ficha_prospeccao(_linha(matricula_ha=20, sigef_ha=20))
    assert derivada["caminho_terra"]["origem"] == "derivada"
    assert derivada["caminho_terra"]["codigo"] == "privada_matricula"


def test_nao_cria_credito_a_partir_de_captura_bruta_ou_faixas_provisorias():
    ficha = ficha_prospeccao({"carbono_tco2_ano": 100, "carbono_tco2_ano_p10": 60, "carbono_tco2_ano_p90": 140})
    assert ficha["credito"]["base"] == "nao_calculado"
    assert all(ficha["credito"][p]["valor"] is None for p in ("p10", "p50", "p90"))
    assert all(ficha["tir"][p]["valor"] is None for p in ("p10", "p50", "p90"))


def test_ausente_nao_repete_p50_e_zero_e_valor_valido():
    ficha = ficha_prospeccao(
        _linha(credito_liquido_tco2_ha_contrato_p10=0, credito_liquido_tco2_ha_contrato_p90=None, embargo_ha=0)
    )
    assert ficha["credito"]["p10"]["valor"] == 0
    assert ficha["credito"]["p90"]["valor"] is None
    assert ficha["embargos"]["situacao"] == "sem_sobreposicao_identificada"
    assert ficha["embargos"]["area"]["valor"] == 0
    assert ficha_prospeccao({})["embargos"]["situacao"] == "sem_dado"


def test_credito_anual_antigo_fica_anual_e_sem_prazo_inventado():
    ficha = ficha_prospeccao(
        {"restauracao_area_ha": 2, "credito_liquido_tco2_ha_ano": 3.5, "credito_liquido_tco2_ha_ano_p10": 1}
    )
    assert ficha["credito"]["base"] == "liquido_anual"
    assert ficha["credito"]["p50"]["valor"] == 7
    assert ficha["credito"]["p50"]["unidade"] == "tCO2e/ano"
    assert ficha["credito"]["p90"]["valor"] is None


@pytest.mark.parametrize("total", [0, 875.5])
def test_total_contratual_sozinho_prevalece_sobre_anual_sem_inventar_faixas(total):
    ficha = ficha_prospeccao({"credito_liquido_tco2_contrato": total, "credito_liquido_tco2_ano": 55})
    assert ficha["credito"]["base"] == "liquido_contrato"
    assert ficha["credito"]["p50"]["valor"] == total
    assert ficha["credito"]["p50"]["unidade"] == "tCO2e/contrato"
    assert ficha["credito"]["p10"]["valor"] is None
    assert ficha["credito"]["p90"]["valor"] is None
    assert "método de incerteza não vem identificado" in ficha["credito"]["metodo"]


def test_total_contratual_e_fallback_sem_area_e_nao_sobrescreve_produto_valido():
    sem_area = ficha_prospeccao(_linha(restauracao_area_ha=None, credito_liquido_tco2_contrato=750))
    assert sem_area["credito"]["p50"]["valor"] == 750
    assert sem_area["credito"]["p10"]["valor"] is None
    assert sem_area["credito"]["p90"]["valor"] is None
    com_area = ficha_prospeccao(_linha(credito_liquido_tco2_contrato=751))
    assert com_area["credito"]["p50"]["valor"] == 750


def test_nao_exporta_textos_livres_nem_objetos_pessoais():
    segredo = "conteudo_pessoal_nao_publicar"
    ficha = ficha_prospeccao(
        _linha(
            nome=segredo,
            contato={"nome": segredo},
            proprietarios=[{"documento": segredo}],
            regularizacao_pendencias=segredo,
            matricula_motivo=segredo,
            caminho_terra_motivo=segredo,
            risco_terra_motivo=segredo,
            dados={"telefone": segredo},
        ),
        {"data_corte": "2026-11-12", "operador": segredo},
        {
            "nome": segredo,
            "serie_uso": {"anos": [2024], "mata_pct": [40], "fonte": segredo, "proprietario": {"nome": segredo}},
        },
    )
    assert segredo not in json.dumps(ficha)
    assert "imovel" not in ficha
    assert ficha["serie_uso"][0]["mata"]["valor"] == 40
    assert ficha["serie_uso"][0]["pasto"]["valor"] is None


@pytest.mark.parametrize("sinal", [True, "True", "true", "sim", "1", 1])
def test_pendencias_da_matricula_aceitam_indicadores_booleanos(sinal):
    ficha = ficha_prospeccao(
        _linha(matricula_onus_graves=sinal, matricula_quebra_cadeia=sinal, matricula_precisa_confirmar=sinal)
    )
    codigos = {p["codigo"] for p in ficha["pendencias"]}
    assert {"onus", "cadeia", "confirmacao"} <= codigos


@pytest.mark.parametrize("sinal", [False, "False", "false", "não", "0", 0, None, float("nan")])
def test_indicadores_falsos_nao_inventam_pendencias(sinal):
    ficha = ficha_prospeccao(
        _linha(matricula_onus_graves=sinal, matricula_quebra_cadeia=sinal, matricula_precisa_confirmar=sinal)
    )
    codigos = {p["codigo"] for p in ficha["pendencias"]}
    assert not {"onus", "cadeia", "confirmacao"} & codigos


def test_historico_anual_nao_confunde_janelas_acumuladas():
    ficha = ficha_prospeccao(
        _linha(
            mb_supressao_primaria_2023_ha=2,
            mb_supressao_secundaria_2024_ha=1.5,
            mb_fogo_2024_ha=3,
            desm_pos2020_ha=4,
            desm_pos2008_ha=8,
        ),
        banco={"serie_uso": {"anos": [2024, 2023], "mata_pct": [40, 45], "pasto_pct": [60, 55]}},
    )
    assert [a["ano"] for a in ficha["serie_uso"]] == [2023, 2024]
    assert ficha["serie_uso"][0]["mata"]["data_referencia"] == "2023"
    anuais = [p for p in ficha["perdas"] if p["ano"] is not None]
    assert {p["tipo"] for p in anuais} == {"fogo", "supressao_primaria", "supressao_secundaria"}
    assert all(p["area"]["data_referencia"] == str(p["ano"]) for p in anuais)
    acumuladas = [p for p in ficha["perdas"] if p["ano"] is None]
    assert len(acumuladas) == 2
    assert all(p["area"]["data_referencia"] is None for p in acumuladas)


@pytest.mark.parametrize("valor", [float("nan"), float("inf"), True, {"nome": "reservado"}, "não medido"])
def test_numero_invalido_nao_vira_zero_nem_vaza_dicionario(valor):
    ficha = ficha_prospeccao(_linha(ha=valor, credito_liquido_tco2_ha_contrato_p50=valor))
    assert ficha["area_total"]["valor"] is None
    assert ficha["credito"]["p50"]["valor"] is None
    json.dumps(ficha, allow_nan=False)
