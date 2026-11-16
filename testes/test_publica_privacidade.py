"""Identificadores de protocolo sobrevivem ao filtro sem abrir exceção para texto pessoal."""

from raiz.publica.privacidade import limpar


def test_uuid_com_trecho_numerico_preservado_e_texto_pessoal_removido():
    pedido = "9a432ea5-eb43-4784-b691-" + "1234567890" + "b7"
    telefone = "(11) " + "91234-5678"
    corpo = {
        "id": pedido,
        "itens": [{"pedido": pedido.upper(), "email": "pessoa@example.test"}],
        "explicacao": f"Pessoa em pessoa@example.test ou {telefone}",
    }
    assert limpar(corpo) == {
        "id": pedido,
        "itens": [{"pedido": pedido.upper()}],
        "explicacao": "Pessoa em <EMAIL> ou <TELEFONE>",
    }


def test_uuid_no_texto_nao_desliga_filtro_de_contato():
    pedido = "9a432ea5-eb43-4784-b691-" + "1234567890" + "b7"
    resposta = limpar(f"{pedido} pessoa@example.test")
    assert "pessoa@example.test" not in resposta
    assert resposta.endswith("<EMAIL>")
