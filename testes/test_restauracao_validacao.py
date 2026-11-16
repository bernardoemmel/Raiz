"""Regressões da comparação de entradas reais e da memória de previsões."""

import json

import pandas as pd
import pytest

from raiz import restauracao_validacao as V


def test_pasto_ausente_nao_e_area_livre_e_pequena_continua():
    base = {"alem_RL_ha": 50, "app_recompor_ha": 2, "ha": 100}
    sem = V.validar_area(base)
    assert sem["area_segura_ha"] is None and not sem["apto_para_previsao"]
    assert "Falta pasto" in sem["pendencias"][0]
    pequena = V.validar_area({**base, "pasto_ha": 0.002, "restauracao_area_ha": 0.002})
    assert pequena["apto_para_previsao"] and pequena["area_segura_ha"] == 0.002
    assert V.validar_area({**base, "pasto_ha": 0.0})["area_segura_ha"] == 0.0


def test_area_inflada_e_nan_com_mapbiomas_por_nome():
    linha = {
        "alem_RL_ha": 50,
        "app_desmatada_ha": 3,
        "ha": 90,
        "pasto_ha": float("nan"),
        "mb_pasto_2024_ha": 40,
        "mb_pasto_2025_ha": 35,
        "restauracao_area_ha": 47,
    }
    resultado = V.validar_area(linha)
    assert resultado["area_segura_ha"] == 35
    assert resultado["pasto_fonte"] == "mb_pasto_2025_ha"
    assert not resultado["apto_para_previsao"] and "excede" in resultado["pendencias"][0]


def test_referencia_distingue_fallback_errado_de_atualizacao_da_colecao():
    quadro = pd.DataFrame({"carbono_tco2_ano": [209708], "pasto_ha": [37736]})
    resultado = V.confrontar_referencia(quadro)
    assert resultado["compatibilidade"] == {"carbono_tco2_ano": "real_corrigido", "pasto_ha": "real_corrigido"}
    assert not resultado["calibracao_captura_autorizada"] and not resultado["contagem_confere"]
    quadro.loc[0, "carbono_tco2_ano"] = 443546
    assert V.confrontar_referencia(quadro)["compatibilidade"]["carbono_tco2_ano"] == "fallback_inflado"
    sem_pasto = V.confrontar_referencia(quadro.drop(columns="pasto_ha"))
    assert sem_pasto["totais_lidos"]["pasto_ha"] is None and "pasto_ha" in sem_pasto["colunas_incompletas"]
    assert V.confrontar_referencia(quadro, 1507300)["situacao"] == "sem_referencia"


def test_comparacao_alinha_car_nao_ordem_ignora_dados_pessoais_e_aceita_coluna_nova(tmp_path):
    antiga, real = tmp_path / "antiga", tmp_path / "real"
    antiga.mkdir()
    real.mkdir()
    pd.DataFrame(
        {
            "cod_imovel": ["PA-A", "PA-B"],
            "ha": [1, 20],
            "carbono_tco2_ano": [5, 60],
            "nome": ["Não publicar", "Não publicar"],
        }
    ).to_csv(antiga / "imoveis_1504950.csv", index=False)
    pd.DataFrame(
        {
            "cod_imovel": ["PA-B", "PA-A", "PA-C"],
            "ha": [20, 1, 3],
            "carbono_tco2_ano": [56, 5, 1],
            "app_recompor_ha": [2, 0, 0],
            "nome": ["Sigiloso"] * 3,
        }
    ).to_csv(real / "imoveis_1504950.csv", index=False)
    resultado = V.comparar_pastas(antiga, real)
    assert resultado["imoveis_comuns"] == 2 and resultado["apenas_real"] == ["PA-C"]
    assert resultado["colunas"]["ha"]["diferentes"] == 0
    assert resultado["colunas"]["app_recompor_ha"]["situacao"] == "ausente_amostra"
    assert resultado["diferencas"] == [{"cod_imovel": "PA-B", "coluna": "carbono_tco2_ano", "amostra": 60, "real": 56}]
    assert "Sigiloso" not in json.dumps(resultado) and "nome" not in resultado["colunas"]
    assert len(resultado["arquivos_sha256"]["real"]["imoveis_1504950.csv"]) == 64


def test_car_duplicado_nao_vira_comparacao_enganosa(tmp_path):
    pd.DataFrame({"cod_imovel": ["PA-A", "PA-A"], "ha": [1, 2]}).to_csv(tmp_path / "imoveis_1504950.csv", index=False)
    with pytest.raises(ValueError, match="duplicada"):
        V.comparar_pastas(tmp_path, tmp_path)


def test_nulos_pandas3_nao_viram_texto_nem_area_observada(tmp_path):
    linha = {"pasto_ha": pd.NA, "alem_RL_ha": 30, "app_recompor_ha": pd.NA}
    assert V.validar_area(linha)["area_segura_ha"] is None
    dados = pd.DataFrame(
        {
            "cod_imovel": pd.Series(["PA-A"], dtype="string"),
            "pasto_ha": pd.Series([pd.NA], dtype="Float64"),
            "carbono_tco2_ano": pd.Series([pd.NA], dtype="Float64"),
        }
    )
    dados.to_csv(tmp_path / "imoveis_1504950.csv", index=False)
    resultado = V.comparar_pastas(tmp_path, tmp_path)
    assert resultado["diferencas"] == []
    assert resultado["referencia_real"]["totais_lidos"] == {"carbono_tco2_ano": None, "pasto_ha": None}
    json.dumps(resultado, allow_nan=False)
    infinito = V.confrontar_referencia(pd.DataFrame({"pasto_ha": [float("inf")]}))
    assert infinito["totais_lidos"]["pasto_ha"] is None


def test_registro_versionado_idempotente_e_imutavel(tmp_path):
    linha = {
        "cod_imovel": "PA-A",
        "restauracao_cenario": "central_r11",
        "restauracao_area_ha": 0.01,
        "credito_liquido_tco2_ha_contrato_p50": 200,
        "tir_projeto_pct_p50": float("nan"),
        "modo_restauracao": "regeneracao_assistida",
        "nome": "Não guardar",
        "cpf": "Não guardar",
        "preco_cpf": 11111111111,
    }
    primeiro = V.registrar_previsoes(tmp_path, [linha], "modelo-v1", "entradas-v1")
    segundo = V.registrar_previsoes(tmp_path, pd.DataFrame([linha]), "modelo-v1", "entradas-v1")
    assert primeiro["novo"] and not segundo["novo"] and primeiro["sha256"] == segundo["sha256"]
    gravado = json.loads((tmp_path / f"previsoes_{primeiro['identidade']}.jsonl").read_text())
    assert gravado["modelo_versao"] == "modelo-v1" and gravado["entradas_versao"] == "entradas-v1"
    assert gravado["tir_projeto_pct_p50"] is None and "nome" not in gravado and "cpf" not in gravado
    assert "preco_cpf" not in gravado
    with pytest.raises(ValueError, match="registro preservado"):
        V.registrar_previsoes(tmp_path, [{**linha, "restauracao_area_ha": 1}], "modelo-v1", "entradas-v1")
    novo = V.registrar_previsoes(tmp_path, [{**linha, "restauracao_area_ha": 1}], "modelo-v2", "entradas-v1")
    assert novo["arquivo"] != primeiro["arquivo"]
    with pytest.raises(ValueError, match="obrigatórias"):
        V.registrar_previsoes(tmp_path, [linha], "", "entradas-v1")
    with pytest.raises(ValueError, match="único"):
        V.registrar_previsoes(tmp_path, [linha, linha], "modelo-v3", "entradas-v1")
    for car in (pd.NA, float("nan"), None, ""):
        with pytest.raises(ValueError, match="CAR"):
            V.registrar_previsoes(tmp_path, [{**linha, "cod_imovel": car}], "modelo-v3", "entradas-v1")
    with pytest.raises(ValueError, match="diverge"):
        V.registrar_previsoes(tmp_path, [{**linha, "restauracao_versao": "v0"}], "modelo-v3", "entradas-v1")


def test_amostra_versionada_confrontada_consigo_mesma():
    from testes.conftest import AMOSTRA

    resultado = V.comparar_pastas(AMOSTRA, AMOSTRA)
    assert resultado["imoveis_comuns"] == 880 and resultado["diferencas"] == []
    assert resultado["referencia_amostra"]["totais_lidos"]["carbono_tco2_ano"] == 222694
    assert resultado["referencia_amostra"]["compatibilidade"]["pasto_ha"] == "amostra_antiga"
