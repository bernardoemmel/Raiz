"""O aviso inicial é um rascunho rastreável; gerar não registra o envio."""

import datetime as dt
from email import policy
from email.parser import Parser

import pytest

from raiz.vigilancia import aviso_verra
from raiz.vigilancia.projetos import Projeto

HOJE = dt.date(2026, 11, 12)
PRAZO = dt.date(2026, 11, 15)


def test_urtx_sem_estado_nao_inventa_descoberta_ou_area(regras):
    projeto = Projeto("URTX", {"nome_projeto": "URTX"})
    d = aviso_verra.preparar(projeto, "URTX_LE1", regras, HOJE, prazo_informado=PRAZO)
    assert d["prazo"] == "2026-11-15" and d["dias_restantes"] == 3
    assert d["origem_prazo"] == "informado_pelo_operador"
    assert d["enviado"] is False and len(d["pendencias"]) == 3
    assert "2026-10-16" not in d["corpo"]  # a descoberta não é deduzida do prazo
    mensagem = Parser(policy=policy.default).parsestr(aviso_verra.eml(d))
    assert mensagem["To"] == "registry@verra.org" and mensagem["X-Unsent"] == "1"
    assert mensagem["From"] is None and "URTX_LE1" in mensagem.get_content()
    with pytest.raises(ValueError, match="evento indisponível"):
        aviso_verra.preparar(projeto, "URTX_LE1", regras, HOJE)
    with pytest.raises(ValueError, match="não é deste projeto"):
        aviso_verra.preparar(projeto, "OUTRO_LE1", regras, HOJE, prazo_informado=PRAZO)
