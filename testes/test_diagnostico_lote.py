"""O Actions precisa da causa/local da falha mesmo sem banco e sem Healthchecks."""

import logging

import pytest

from raiz.operacao.healthchecks import Healthchecks
from raiz.operacao.lotes import lote


@pytest.mark.parametrize("embargo", [False, True])
def test_diagnostico_sem_banco_preserva_excecao_sem_expor_dados(caplog, embargo):
    mensagem = (
        "embargo ativo sem geometria poligonal válida; cálculo bloqueado"
        if embargo
        else "nome pessoal e credencial privada não devem aparecer"
    )
    erro = ValueError(mensagem)
    with caplog.at_level(logging.WARNING), pytest.raises(ValueError) as levantado:
        with lote(None, Healthchecks(""), "funil", "RN", 2400109) as reg:
            reg.nota("conteúdo pessoal capturado")
            raise erro
    assert levantado.value is erro
    assert "ValueError" in caplog.text and "test_diagnostico_lote.py" in caplog.text
    assert "embargo_ativo_sem_geometria_utilizavel" in caplog.text if embargo else '"motivo": null' in caplog.text
    assert mensagem not in caplog.text and "conteúdo pessoal capturado" not in caplog.text
