"""Regressões dos critérios que fazem o ensaio Locust reprovar."""

import pytest

from testes.carga.contrato import ROTAS_API, conferir_relatorio, exigir_local, retry_after_valido
from testes.carga.servidor import banco_local


def relatorio(**mudancas):
    return {
        "fase": "normal",
        "requisicoes": 100,
        "falhas": 0,
        "max_ms": 100,
        "sucessos": dict.fromkeys(ROTAS_API, 10),
        **mudancas,
    }


def test_carga_reprova_servidor_sem_limite():
    assert "limite não devolveu 429" in conferir_relatorio(relatorio(fase="limite"), set(ROTAS_API))


def test_carga_reprova_limite_sem_retry_after():
    erros = conferir_relatorio(relatorio(fase="limite", limitadas=30, retry_after_invalidos=1), set(ROTAS_API))
    assert "429 sem Retry-After válido" in erros


def test_carga_reprova_servidor_que_so_bloqueia():
    erros = conferir_relatorio(relatorio(fase="limite", limitadas=100, sucessos={}), set(ROTAS_API))
    assert "nem todas as rotas/ferramentas tiveram resposta válida" in erros


@pytest.mark.parametrize(
    "mudancas, esperado",
    [
        ({"max_ms": 5000}, "resposta demorou 5 segundos ou mais"),
        ({"falhas": 1}, "requisições com erro"),
        ({"requisicoes": 0}, "menos de 20 requisições"),
        ({"limitadas": 1}, "429 inesperado na carga abaixo do orçamento"),
    ],
)
def test_carga_reprova_sobrecarga_e_ensaio_vazio(mudancas, esperado):
    assert esperado in conferir_relatorio(relatorio(**mudancas), set(ROTAS_API))


@pytest.mark.parametrize("valor", [None, "", "0", "-1", "1.1", "61", "١", "NaN"])
def test_retry_after_invalido(valor):
    assert not retry_after_valido(valor)


def test_carga_aprova_contrato_observado():
    assert not conferir_relatorio(relatorio(), set(ROTAS_API))
    assert not conferir_relatorio(relatorio(fase="limite", limitadas=3), set(ROTAS_API))
    assert retry_after_valido("2")


@pytest.mark.parametrize(
    "url",
    ["https://raiz.example", "http://token@localhost:8000", "http://localhost:8000?token=x", "file:///tmp/mcp"],
)
def test_carga_nao_atinge_producao_ou_credencial_na_url(url):
    with pytest.raises(ValueError):
        exigir_local(url)


@pytest.mark.parametrize("banco", ["raiz", "raiz_teste", "raiz_e2e"])
def test_carga_nao_apaga_banco_de_outro_ensaio(banco):
    with pytest.raises(ValueError):
        banco_local(f"postgresql+psycopg://raiz:raiz@localhost:5432/{banco}")


@pytest.mark.parametrize(
    "query", ["host=remoto.example.invalid", "hostaddr=192.0.2.1", "dbname=raiz", "service=producao"]
)
def test_parametros_libpq_nao_podem_redirecionar_banco_descartavel(query, monkeypatch):
    from testes.e2e.servidor import banco

    with pytest.raises(ValueError):
        banco_local(f"postgresql+psycopg://localhost/raiz_carga?{query}")
    monkeypatch.setenv("RAIZ_BANCO_URL_TESTE", f"postgresql+psycopg://localhost/raiz_e2e?{query}")
    with pytest.raises(RuntimeError):
        banco()
