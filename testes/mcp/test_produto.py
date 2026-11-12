"""Fronteiras do adaptador: nunca migrar banco alheio nem herdar integrações reais."""

import os

import pytest

from raiz.config import config
from testes.mcp import produto


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://localhost/raiz",
        "postgresql://localhost/raiz_teste",
        "postgresql://banco.example.invalid/raiz_mcp_teste",
        "postgresql://localhost/raiz_mcp_teste?host=banco.example.invalid",
        "postgresql://localhost/raiz_mcp_teste?dbname=raiz",
        "",
    ],
)
def test_adaptador_recusa_banco_alheio_antes_de_qualquer_migracao(url, monkeypatch):
    monkeypatch.setenv("RAIZ_BANCO_URL_MCP_TESTE", url)
    chamadas = []
    monkeypatch.setattr(produto, "_criar_banco", lambda _: chamadas.append(True))
    with pytest.raises(RuntimeError):
        with produto.integracao():
            pytest.fail("Não poderia criar a integração com esse banco")
    assert chamadas == []


def test_configuracao_de_provedor_nao_chega_ao_adaptador(monkeypatch):
    monkeypatch.setenv("RAIZ_BANCO_URL_MCP_TESTE", "postgresql://localhost/raiz_mcp_teste")
    monkeypatch.setenv("RAIZ_ABACATEPAY_CHAVE", "credencial-sintetica-nao-utilizavel")
    monkeypatch.setenv("RAIZ_GLITCHTIP_DSN", "https://teste@erros.example.invalid/1")
    monkeypatch.setenv("RAIZ_API_LIMIT_STORAGE_URI", "redis://remoto.example.invalid:6379/0")

    class AntesDeMigrar(Exception):
        pass

    def verificar_antes_de_migrar(_):
        assert "RAIZ_ABACATEPAY_CHAVE" not in os.environ
        assert "RAIZ_API_LIMIT_STORAGE_URI" not in os.environ
        assert config().glitchtip_dsn is None
        raise AntesDeMigrar

    monkeypatch.setattr(produto, "_criar_banco", verificar_antes_de_migrar)
    with pytest.raises(AntesDeMigrar):
        with produto.integracao():
            pytest.fail("O teste não deve alcançar serviços ou migrações")
    assert os.environ["RAIZ_ABACATEPAY_CHAVE"] == "credencial-sintetica-nao-utilizavel"


def test_dns_externo_e_bloqueado_antes_do_resolvedor(tmp_path, monkeypatch):
    import socket

    from testes.mcp.servidor import rede_local

    consultas = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: consultas.append(a) or [])
    arquivo = tmp_path / "rede.txt"
    with rede_local(arquivo):
        with pytest.raises(RuntimeError, match="DNS externo"):
            socket.getaddrinfo("coletor.example.invalid", 443)
        assert consultas == []
        socket.getaddrinfo("127.0.0.1", 80)
        assert consultas == [("127.0.0.1", 80)]
    assert arquivo.read_text() == "dns_externo_bloqueado\n"
