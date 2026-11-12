import pytest
from sqlalchemy import create_engine, text

from raiz import contrato
from raiz.banco import desfazer, migrar

pytestmark = pytest.mark.banco


def _colunas(con, esquema, tabela):
    q = text("select column_name from information_schema.columns where table_schema=:e and table_name=:t")
    return {r[0] for r in con.execute(q, {"e": esquema, "t": tabela})}


def test_esquemas_criados(con):
    esquemas = {r[0] for r in con.execute(text("select schema_name from information_schema.schemata"))}
    assert {"coleta", "bruto", "funil", "regras", "titulo", "negocio", "aprendizado", "pessoal", "operacao"} <= esquemas


def test_contrato_tem_coluna_tipada(con):
    """Toda coluna do contrato tem coluna tipada no banco (com nome em minúsculas)."""
    for tabela, contr in [("resultado_imovel", contrato.IMOVEIS), ("filtro_imovel", contrato.FILTROS)]:
        faltam = {contrato.coluna_banco(c) for c in contr} - _colunas(con, "funil", tabela)
        assert not faltam, (tabela, faltam)
    faltam = (
        {contrato.coluna_banco(c) for c in contrato.RESUMO} - {"cod_ibge"} - _colunas(con, "funil", "resumo_municipio")
    )
    assert not faltam


def test_migracao_desce_e_sobe(banco_url):
    desfazer(banco_url)
    eng = create_engine(banco_url)
    with eng.connect() as c:
        assert not c.execute(text("select to_regclass('funil.rodada')")).scalar()
    migrar(banco_url)
    with eng.connect() as c:
        assert c.execute(text("select to_regclass('funil.rodada')")).scalar()
    eng.dispose()
