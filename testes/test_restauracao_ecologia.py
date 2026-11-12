import copy

import pytest

from raiz import restauracao_ecologia as E


def _local():
    return {
        "cod_imovel": "PA-teste",
        "restauracao_area_ha": 0.25,
        "modo_restauracao": "plantio_total",
        "ecologia_projecao": {
            "fonte": "inventário e modelo local, documento de teste",
            "data_corte": "2026-11-12",
            "modelo_versao": "local-1",
            "tipo": "cenario_planejamento",
            "populacao": "árvores vivas com DAP maior ou igual a 5 cm",
            "riqueza_unidade": "especies_distintas_na_area_restaurada",
            "incerteza": "Faixa de cenário do responsável técnico; ainda sem calibração de cobertura.",
            "horizontes": {
                "3": {
                    "densidade_arvores_ha": {"p10": 500, "p50": 1000, "p90": 2000},
                    "numero_especies": {"p10": 5, "p50": 10, "p90": 20},
                }
            },
        },
    }


def test_sem_inventario_nao_inventa_previsoes_a_partir_de_carbono():
    p = E.projetar({"cod_imovel": "pequena", "restauracao_area_ha": 0.001, "captura_total_tco2_ha_p50": 588}, "r11")
    assert [h["ano"] for h in p["horizontes"]] == [3, 5, 10, 15]
    assert p["area_restaurada_ha"] == 0.001
    for h in p["horizontes"]:
        assert h["situacao"] == "sem_previsao_local"
        for campo in ("densidade_arvores_ha", "numero_especies", "numero_arvores_area_restaurada"):
            assert h[campo] == dict.fromkeys(E.Q)
    assert "não significam zero" in p["incerteza"]
    assert p["ecologia_versao"].startswith("ecologia-2026a+")


def test_referencia_normativa_nao_e_quantil_ou_arvore_adulta():
    p = E.projetar({"cod_imovel": "a", "restauracao_area_ha": 1}, "r11")
    refs = [h["referencia_monitoramento"] for h in p["horizontes"]]
    assert [x["regenerantes_ha_adequado_acima_de"] for x in refs] == [200, 1000, 2000, 2500]
    assert [x["especies_adequado_acima_de"] for x in refs] == [3, 10, 20, 25]
    assert all("nao_previsao_pa" in x["tipo"] and "CAP menor que 15 cm" in x["populacao"] for x in refs)
    assert p["referencias"][1]["densidades_usuais_ha"] == [1667, 2500]


def test_projecao_documentada_escala_individuos_mas_nao_especies():
    li = _local()
    antes = copy.deepcopy(li)
    p = E.projetar(li, "r11")
    h = p["horizontes"][0]
    assert h["numero_arvores_area_restaurada"] == {"p10": 125, "p50": 250, "p90": 500}
    assert h["numero_especies"] == {"p10": 5, "p50": 10, "p90": 20}
    assert h["situacao"] == "cenario_planejamento"
    assert p["projecao_versao"] == "local-1" and p["modelo_versao"] == "r11"
    assert p["horizontes"][1]["situacao"] == "sem_previsao_local"
    assert li == antes


@pytest.mark.parametrize("campo", ["fonte", "modelo_versao", "populacao", "incerteza", "data_corte"])
def test_projecao_sem_rastreabilidade_e_recusada(campo):
    li = _local()
    del li["ecologia_projecao"][campo]
    with pytest.raises(ValueError, match=campo):
        E.projetar(li, "r11")


@pytest.mark.parametrize("valor", [-1, float("nan"), float("inf"), True])
def test_faixas_invalidas_nao_sao_publicadas(valor):
    li = _local()
    li["ecologia_projecao"]["horizontes"]["3"]["densidade_arvores_ha"]["p10"] = valor
    with pytest.raises(ValueError, match="finito"):
        E.projetar(li, "r11")


def test_quantis_invertidos_e_riqueza_por_hectare_sao_recusados():
    li = _local()
    li["ecologia_projecao"]["horizontes"]["3"]["numero_especies"]["p50"] = 30
    with pytest.raises(ValueError, match="p10"):
        E.projetar(li, "r11")
    li = _local()
    li["ecologia_projecao"]["riqueza_unidade"] = "especies_por_hectare"
    with pytest.raises(ValueError, match="nunca por hectare"):
        E.projetar(li, "r11")


def test_tabela_tem_quatro_horizontes_por_car_sem_dados_pessoais():
    li = {**_local(), "nome": "pessoa", "cpf": "12345678901"}
    tab = E.tabela([li], "r11")
    assert len(tab) == 4 and {x["cod_imovel"] for x in tab} == {"PA-teste"}
    assert all("cpf" not in x and "nome" not in x for x in tab)
    assert tab[0]["numero_especies_p50"] == 10
    assert tab[1]["numero_especies_p50"] is None
    assert "não foi quantificada" in tab[1]["incerteza"]


def test_versao_obrigatoria_e_area_total_nao_substitui_restauracao():
    with pytest.raises(ValueError, match="versão"):
        E.projetar({"cod_imovel": "a"}, "")
    p = E.projetar({"cod_imovel": "a", "ha": 1000}, "r11")
    assert p["area_restaurada_ha"] is None


@pytest.mark.parametrize("cod", [None, float("nan"), "", "   "])
def test_car_ausente_nao_vira_identificador_de_fazenda(cod):
    with pytest.raises(ValueError, match="cod_imovel"):
        E.projetar({"cod_imovel": cod}, "r11")
