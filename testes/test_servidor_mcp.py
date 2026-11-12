"""A migração não deixa o adaptador grátis como desvio da API paga."""

import pytest

from raiz.publica.servidor_mcp import ApiRaiz, criar_servidor


def test_mcp_antigo_fechado():
    with pytest.raises(RuntimeError, match="OAuth"):
        ApiRaiz(chave="raiz_teste")
    with pytest.raises(RuntimeError, match="OAuth"):
        criar_servidor()
