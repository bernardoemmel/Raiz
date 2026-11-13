"""Conferência real da expressão em dois bancos, inclusive vazio e recusa de nulos."""

import pytest

from raiz.conferencia.ibis_contagem import conferir, ler_csvs


@pytest.mark.parametrize("codigos", [[], ["1400100"], ["1500107", "1400100", "1400100"]])
def test_mesma_consulta_nos_dois_mecanismos(codigos):
    r = conferir(codigos)
    assert r["iguais"]
    assert r["linhas"] == len(codigos)
    assert sum(r["contagens"]["duckdb"].values()) == len(codigos)
    assert set(r["consultas"]) == {"duckdb", "sqlite"}
    assert all("COUNT(*)" in sql for sql in r["consultas"].values())
    assert r["versoes"]["ibis-framework"] == "12.0.0"


@pytest.mark.parametrize("valor", [None, "", "1400100.0", "' OR 1=1", "Pessoa Sintética"])
def test_codigo_invalido_nao_e_omitido_ou_exposto(valor):
    with pytest.raises(ValueError, match="nenhuma linha foi descartada") as erro:
        conferir(["1400100", valor])
    assert repr(valor) not in str(erro.value)


def test_csv_exige_coluna_por_nome_e_le_todas_as_linhas(tmp_path):
    arquivo = tmp_path / "imoveis_1400100.csv"
    arquivo.write_text("cod_imovel,cod_municipio_ibge\nsintetico,1400100\nsintetico2,1400100\n")
    assert ler_csvs(tmp_path, "cod_municipio_ibge") == ["1400100", "1400100"]
    with pytest.raises(ValueError, match="coluna municipal ausente"):
        ler_csvs(tmp_path, "inexistente")
