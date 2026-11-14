"""URLs entram no banco, na API e no feed; contatos codificados não podem passar."""

import datetime as dt
from urllib.parse import quote

import pytest

from raiz.calendario.modelos import Evento, identificador, url_publica
from testes.test_privacidade import CPF

URL = "https://www.in.gov.br/web/dou/-/edital"


@pytest.mark.parametrize(
    "url",
    [
        URL + "?contato=pessoa%40example.invalid",
        URL + "/pessoa%40example.invalid.pdf",
        URL + "?p=pessoa%2540example.invalid",
        URL + "?p=%2B55%20%2811%29%2091234-5678",
        URL + "?telefone=indisponivel",
        URL + "?nome_proprietario=Pessoa+Teste",
        URL + "?access_token=valor-de-teste",
        URL + "/" + quote(quote(CPF, safe=""), safe=""),
    ],
    ids=[
        "contato_query",
        "email_arquivo",
        "email_duplo",
        "telefone_codificado",
        "campo_telefone",
        "campo_nome",
        "credencial_url",
        "documento_codificado",
    ],
)
def test_url_pessoal_e_recusada_antes_de_formar_evento_persistivel(url):
    with pytest.raises(ValueError):
        url_publica(url)
    with pytest.raises(ValueError):
        Evento(
            id=identificador("dou", "teste", "leilao_imovel", "1"),
            tipo="leilao_imovel",
            data=dt.date(2026, 12, 1),
            fonte_id="dou",
            fonte_nome="Diário Oficial da União",
            fonte_url=url,
            coletado_em=dt.datetime(2026, 11, 12, tzinfo=dt.UTC),
            confianca=0.9,
        )


def test_url_oficial_preserva_identificador_do_ato_e_remove_fragmento():
    publico = URL + "?id=1234&ano=2026"
    assert url_publica(publico + "#:~:text=Pessoa%20Teste") == publico
