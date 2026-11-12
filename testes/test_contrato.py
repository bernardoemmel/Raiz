"""Contrato com o motor: ler pelo nome e tolerar colunas novas (CLAUDE.md)."""

import pandas as pd
import pytest

from raiz import contrato
from testes.conftest import AMOSTRA

IMOVEIS = AMOSTRA / "imoveis_1504950.csv"


def test_le_amostra_pelo_nome():
    lt = contrato.ler(IMOVEIS)
    assert lt.tipo == "imoveis" and len(lt) == 880
    assert lt.colunas_novas == []
    # a amostra foi gerada antes da escadinha da APP entrar no funil: falta, mas não quebra
    assert set(lt.colunas_faltando) == {"app_escadinha_ha", "app_recompor_ha"}
    t = lt.tipadas
    assert t["pct_rl"].dtype == float and "pct_RL" not in t
    assert set(t["problema"].dropna().unique()) <= {True, False}
    assert str(t["dat_criacao"].dtype).startswith("datetime64") and t["dat_criacao"].dt.tz is not None
    assert t["cod_municipio_ibge"].dropna().eq(1504950).all()
    assert all(a == {} for a in lt.atributos)


def test_ordem_das_colunas_nao_importa(tmp_path):
    df = pd.read_csv(IMOVEIS, dtype=str)
    f = tmp_path / "imoveis_1.csv"
    df[list(reversed(df.columns))].to_csv(f, index=False)
    a, b = contrato.ler(IMOVEIS).tipadas, contrato.ler(f).tipadas
    pd.testing.assert_frame_equal(a, b)


def test_coluna_nova_vai_para_atributos(tmp_path):
    df = pd.read_csv(IMOVEIS, dtype=str)
    df.insert(5, "coluna_inventada_ha", "12.5")
    df["frente_nova_texto"] = "x"
    f = tmp_path / "imoveis_1504950.csv"
    df.to_csv(f, index=False)
    lt = contrato.ler(f)
    assert lt.colunas_novas == ["coluna_inventada_ha", "frente_nova_texto"]
    assert lt.atributos[0] == {"coluna_inventada_ha": 12.5, "frente_nova_texto": "x"}


def test_coluna_que_nao_converte_nao_derruba(tmp_path):
    df = pd.read_csv(IMOVEIS, dtype=str)
    df.loc[0, "eudr_ok"] = "talvez"
    f = tmp_path / "imoveis_1504950.csv"
    df.to_csv(f, index=False)
    lt = contrato.ler(f)
    assert lt.tipadas["eudr_ok"].isna().all()
    assert lt.atributos[0]["eudr_ok"] == "talvez"
    assert any("eudr_ok" in a for a in lt.avisos)


def test_coluna_pessoal_e_removida(tmp_path):
    df = pd.read_csv(IMOVEIS, dtype=str).head(3)
    df["nome_proprietario"] = "Fulano"
    df["cpf_cnpj"] = "000"
    f = tmp_path / "imoveis_9.csv"
    df.to_csv(f, index=False)
    lt = contrato.ler(f)
    assert set(lt.colunas_pessoais_removidas) == {"nome_proprietario", "cpf_cnpj"}
    assert "nome_proprietario" not in lt.atributos[0] and "cpf_cnpj" not in lt.colunas_novas


def test_sem_chave_falha(tmp_path):
    f = tmp_path / "imoveis_9.csv"
    pd.read_csv(IMOVEIS, dtype=str).drop(columns="cod_imovel").to_csv(f, index=False)
    with pytest.raises(ValueError, match="cod_imovel"):
        contrato.ler(f)


def test_resumo_frentes_em_atributos():
    lt = contrato.ler(AMOSTRA / "resumo_PA.csv")
    assert len(lt) == 144 and lt.colunas_novas == []
    assert "frente_carbono" in lt.atributos[0]


def test_mapbiomas_por_nome_e_opcional(tmp_path):
    f = tmp_path / "mapbiomas_1504950.csv"
    pd.DataFrame(
        {
            "cod_imovel": ["A", "B"],
            "mb_floresta_2025_ha": ["10.5", "0"],
            "mb_classe_principal_2025": ["3", "15"],
            "mb_pasto_vigor_principal": ["2", None],
            "mb_floresta_2026_ha": ["11", "1"],
            "mb_indicador_novo_2025": ["x", "y"],
            "sobra": ["1", "2"],
        }
    ).to_csv(f, index=False)
    lt = contrato.ler_mapbiomas(f)
    t = lt.longa.set_index(["cod_imovel", "indicador", "ano"], drop=False)
    assert t.loc[("A", "floresta_ha", 2025)].valor_num == 10.5 and t.loc[("A", "floresta_ha", 2026)].valor_num == 11
    vigor = lt.longa[lt.longa.indicador == "pasto_vigor_principal"]
    assert list(vigor.cod_imovel) == ["A"] and vigor.ano.isna().all()  # nulo não vira linha; sem ano fica nulo
    assert lt.indicadores_novos == ["mb_indicador_novo_2025"]
    assert lt.longa[lt.longa.indicador == "indicador_novo"].valor_texto.tolist() == ["x", "y"]
    assert any("sobra" in a for a in lt.avisos)
    # arquivo sem nenhuma coluna mb_ é aceito (todas opcionais)
    pd.DataFrame({"cod_imovel": ["A"]}).to_csv(tmp_path / "mapbiomas_1.csv", index=False)
    assert len(contrato.ler_mapbiomas(tmp_path / "mapbiomas_1.csv").longa) == 0
