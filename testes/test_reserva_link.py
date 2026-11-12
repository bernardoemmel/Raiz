"""A pessoa segue exatamente o link recebido, incluindo domínio, caminho e token."""

import re
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient

from raiz.pedidos.servico import mensagem_confirmacao_reserva
from raiz.publica.api import criar


def test_link_da_notificacao_abre_formulario_correto_e_preserva_token():
    token = "XyZ-Token_X_Para_Pessoa"
    mensagem = mensagem_confirmacao_reserva(
        "pedido-de-teste", 1234.56, 12000, 60, "https://api.raiz.example/v1/", token
    )
    link = re.search(r"https://\S+", mensagem).group(0)
    assert link == f"https://api.raiz.example/v1/reservas/confirmar/{token}"
    assert "R$ 1.234,56, 12.000 ha" in mensagem
    app = FastAPI()
    app.mount("/v1", criar(lambda _: None))
    with TestClient(app) as cl:
        pagina = cl.get(urlsplit(link).path)
    assert pagina.status_code == 200
    assert f"const base='/v1/reservas/confirmar/{token}'" in pagina.text
    assert 'id="aprovar"' in pagina.text
    assert "Aprovar e gerar Pix" in pagina.text
    assert pagina.headers["Cache-Control"] == "no-store"
    assert pagina.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in pagina.headers["Content-Security-Policy"]
