"""O Actions precisa da causa/local da falha mesmo sem banco e sem Healthchecks."""

import json
import logging

import pytest

from raiz.operacao.healthchecks import Healthchecks
from raiz.operacao.lotes import lote
from raiz.privacidade import FormatadorJSON


@pytest.mark.parametrize("embargo", [False, True])
@pytest.mark.parametrize("json_no_log", [False, True])
def test_diagnostico_sem_banco_preserva_excecao_sem_expor_dados(caplog, monkeypatch, embargo, json_no_log):
    formatador = FormatadorJSON() if json_no_log else logging.Formatter("%(message)s")
    monkeypatch.setattr(caplog.handler, "formatter", formatador)
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
    registro = next(r for r in caplog.records if r.name == "raiz.operacao.lotes")
    diagnostico = json.loads(registro.getMessage().split(": ", 1)[1])
    assert diagnostico["tipo"] == "ValueError"
    assert any(q["arquivo"] == "testes/test_diagnostico_lote.py" for q in diagnostico["quadros"])
    assert diagnostico["motivo"] == ("embargo_ativo_sem_geometria_utilizavel" if embargo else None)
    for texto in (registro.getMessage(), caplog.text):
        assert mensagem not in texto and "conteúdo pessoal capturado" not in texto
