import copy
import json

import pytest

from raiz.restauracao_validacao_arr import (
    REFERENCIAS,
    avaliar_referencias,
    comparar,
    diagnosticar_janela_inicial,
    gravar_comparacao,
    normalizar_emissoes,
    reconciliar_creditos,
    sha256,
)


def evento(**novos):
    return {
        "Project ID": 1317,
        "Vintage Start +": "2017-01-01",
        "Vintage End +": "2017-12-31",
        "Issuance Date": "2024-05-31",
        "Total Vintage Quantity +": 606,
        "Units": 126,
        "Serial Number": "serial-a",
        **novos,
    }


def par():
    comuns = {
        "projeto_id": "VCS3743",
        "instancia_id": "PAI001",
        "periodo_inicio": "2022-10-04",
        "periodo_fim": "2025-06-15",
        "bioma": "Mata Atlântica",
        "metodo": "plantio_total",
        "area_ha": 342.27,
        "coortes_sha256": sha256({"coorte": "teste"}),
        "pools": ["arvores", "raizes", "solo"],
        "alvo": "remocao_adicional_pre_buffer",
        "base_contabil": "delta_estoque_menos_baseline_vazamento_emissoes",
    }
    previsao = {
        **comuns,
        "modelo_versao": "restauracao-teste+abc",
        "entradas_sha256": sha256(comuns),
        "p10": 8,
        "p50": 10,
        "p90": 13,
    }
    observado = {
        **comuns,
        "fonte_versao": "MR teste v1",
        "fonte_sha256": "a" * 64,
        "natureza": "monitorado",
        "valor_tco2e": 12,
        "conjunto": "validacao_independente",
    }
    return copy.deepcopy(previsao), copy.deepcopy(observado)


def test_vintage_historico_usa_total_sem_somar_repeticoes_ou_units():
    linhas = [evento(), evento(**{"Serial Number": "serial-b", "Units": 100}), evento()]
    [r] = normalizar_emissoes(linhas)
    assert r["emitido_tco2e"] == 606
    assert r["soma_units"] == 226
    assert r["eventos_distintos"] == 2
    assert r["periodo_fim"] == "2017-12-31"
    assert r["primeira_emissao"] == "2024-05-31"


def test_vintage_novo_soma_fracoes_por_serial_uma_vez_e_tolerenovas_colunas():
    a = evento(**{"Total Vintage Quantity +": None, "coluna_futura": "aceita"})
    b = evento(**{"Total Vintage Quantity +": None, "Serial Number": "serial-b", "Units": 10})
    [r] = normalizar_emissoes([a, a, b])
    assert r["emitido_tco2e"] == 136


@pytest.mark.parametrize(
    "alteracao",
    [
        {"Units": float("nan")},
        {"Units": True},
        {"Units": -1},
        {"Total Vintage Quantity +": None, "Serial Number": None},
        {"Vintage End +": "2016-12-31"},
    ],
)
def test_eventos_invalidos_nao_entram_silenciosamente(alteracao):
    with pytest.raises(ValueError):
        normalizar_emissoes([evento(**alteracao)])


def test_serial_conflitante_e_mistura_de_totais_exigem_reconciliacao():
    with pytest.raises(ValueError, match="conflitantes"):
        normalizar_emissoes([evento(), evento(**{"Units": 1})])
    with pytest.raises(ValueError, match="misturados"):
        normalizar_emissoes([evento(), evento(**{"Total Vintage Quantity +": None, "Serial Number": "novo"})])


def test_reconciliacao_nao_confunde_emitivel_com_emissao_parcial():
    r = reconciliar_creditos(128049.54460461545, 31117.62151215743, 0, 0, 11631.830771094961, 65274)
    assert r["adicional_pre_buffer_tco2e"] == pytest.approx(96931.92309245802)
    assert r["emitivel_pos_buffer_tco2e"] == pytest.approx(85300.09232136306)
    assert r["diferenca_emitivel_emitido_tco2e"] == pytest.approx(20026.09232136306)
    assert r["diferenca_nao_mede_erro_crescimento"]


def test_buffer_acumulado_incompativel_e_observacao_ausente():
    with pytest.raises(ValueError, match="buffer excede"):
        reconciliar_creditos(100, 20, 0, 0, 200, None)
    assert reconciliar_creditos(100, 20, 0, 0, 16, None)["emitido_tco2e"] is None


def test_par_compativel_gera_metricas_sem_autorizar_calibracao():
    p, o = par()
    r = comparar(p, o)
    assert r["status"] == "comparavel"
    assert r["metricas"]["erro_tco2e"] == -2
    assert r["metricas"]["cobertura_p10_p90"]
    assert r["validacao_independente"]
    assert not r["calibracao_autorizada"]


@pytest.mark.parametrize(
    ("campo", "valor", "motivo"),
    [
        ("area_ha", 343, "area_ha_divergente_ou_invalida"),
        ("coortes_sha256", "b" * 64, "coortes_sha256_divergente"),
        ("periodo_fim", "2025-06-16", "periodo_fim_divergente"),
        ("pools", ["arvores"], "pools_divergente"),
        ("base_contabil", "estoque_bruto", "base_contabil_divergente"),
        ("natureza", "emitido", "observacao_nao_e_monitoramento_harmonizado"),
        ("valor_tco2e", None, "observado_ausente_nao_e_zero"),
    ],
)
def test_incomparabilidade_tem_motivo_e_nao_gera_fator(campo, valor, motivo):
    p, o = par()
    o[campo] = valor
    r = comparar(p, o)
    assert r["status"] == "incomparavel"
    assert motivo in r["motivos"]
    assert r["metricas"] is None
    assert not r["calibracao_autorizada"]


def test_reserva_historica_nao_vira_vinte_por_cento_retroativamente():
    p, o = par()
    for r in (p, o):
        r["alvo"] = "credito_emitivel_pos_buffer"
    p["reserva_fracao"], o["reserva_fracao"] = 0.20, 0.12
    assert "reserva_historica_divergente_ou_ausente" in comparar(p, o)["motivos"]


@pytest.mark.parametrize("id", ["VCS665", "VCS5709"])
def test_fontes_ja_usadas_nao_sao_validacao_independente(id):
    p, o = par()
    p["projeto_id"] = o["projeto_id"] = id
    assert not comparar(p, o)["validacao_independente"]


def test_zero_previsto_nao_divide_por_zero_e_area_pequena_compara():
    p, o = par()
    p["area_ha"] = o["area_ha"] = 0.01
    p.update(p10=0, p50=0, p90=0)
    r = comparar(p, o)
    assert r["status"] == "comparavel"
    assert r["metricas"]["razao_observado_previsto"] is None
    assert not r["metricas"]["cobertura_p10_p90"]


def test_registro_imutavel_idempotente_e_versionado(tmp_path):
    p, o = par()
    r = comparar(p, o)
    caminho, novo = gravar_comparacao(r, tmp_path)
    assert novo
    assert gravar_comparacao(r, tmp_path) == (caminho, False)
    p["modelo_versao"] = "nova"
    assert r["previsao"]["modelo_versao"] != "nova"
    outro, novo = gravar_comparacao(comparar(p, o), tmp_path)
    assert novo and outro != caminho
    caminho.write_text("adulterado")
    with pytest.raises(ValueError, match="não será sobrescrito"):
        gravar_comparacao(r, tmp_path)


def test_hash_e_versao_obrigatorios_e_alteracao_detectada(tmp_path):
    p, o = par()
    p.pop("modelo_versao")
    with pytest.raises(ValueError, match="modelo_versao"):
        comparar(p, o)
    p, o = par()
    r = comparar(p, o)
    r["metricas"]["erro_tco2e"] = 999
    with pytest.raises(ValueError, match="conteúdo foi alterado"):
        gravar_comparacao(r, tmp_path)


def test_diagnostico_janela_inteira_nao_trata_rateio_anual_como_medicao(tmp_path):
    r = diagnosticar_janela_inicial(
        {
            "projeto_id": "VCS3772",
            "intervencao_inicio": "2023-09-28",
            "periodo_fim": "2025-05-31",
            "valor_tco2e": 96931.92309245802,
            "fonte_sha256": "a" * 64,
        }
    )
    assert r["curva_zero_na_janela"]
    assert r["incompatibilidade_temporal_de_escopo"]
    assert r["previsao_pareada"] is None
    assert not r["calibracao_autorizada"]
    assert gravar_comparacao(r, tmp_path)[1]


def test_referencias_reais_reconciliam_baseline_buffer_e_emissao_atual(tmp_path):
    referencias = json.loads(REFERENCIAS.read_text())
    casos = referencias["monitoramentos"]
    for caso in casos:
        r = reconciliar_creditos(
            caso["bruto_tco2e"],
            caso["linha_base_tco2e"],
            caso["vazamento_tco2e"],
            caso["emissoes_projeto_tco2e"],
            caso["buffer_periodo_tco2e"],
            None,
        )
        assert r["adicional_pre_buffer_tco2e"] == pytest.approx(caso["adicional_pre_buffer_tco2e"])
        assert r["emitivel_pos_buffer_tco2e"] == pytest.approx(caso["emitivel_pos_buffer_tco2e"])
    atual = referencias["verra_atual"][0]
    amazonia = next(c for c in casos if c["projeto_id"] == "VCS3772")
    assert round(amazonia["emitivel_pos_buffer_tco2e"]) == atual["emitido_tco2e"] == 85300
    assert atual["emitido_tco2e"] == atual["ativo_tco2e"] + atual["aposentado_tco2e"]
    primeira = avaliar_referencias(referencias, tmp_path)
    assert len(primeira) == 5
    assert all(not x["registro"]["calibracao_autorizada"] for x in primeira)
    assert all(not x["novo"] for x in avaliar_referencias(referencias, tmp_path))
    cortes = primeira[-1]["registro"]
    assert cortes["corte_anterior"]["emitido_tco2e"] == 65274
    assert cortes["corte_atual"]["emitido_tco2e"] == 85300
    assert cortes["corte_atual"]["aposentado_tco2e"] == 65274
    assert cortes["previsao_pareada"] is None
