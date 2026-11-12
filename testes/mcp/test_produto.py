"""Fronteiras do adaptador: nunca migrar banco alheio nem herdar integrações reais."""

import json
import os
import shutil
from contextlib import contextmanager
from types import SimpleNamespace

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


@pytest.mark.parametrize("metodo", ["connect", "connect_ex", "sendto", "sendto_com_flags"])
def test_destino_externo_e_bloqueado_antes_de_enviar_pacote(metodo, tmp_path, monkeypatch):
    import socket

    from testes.mcp.servidor import rede_local

    chamadas = []
    nome_metodo = "sendto" if metodo == "sendto_com_flags" else metodo
    monkeypatch.setattr(socket.socket, nome_metodo, lambda *args: chamadas.append(args) or 0)
    arquivo = tmp_path / "rede.txt"
    with rede_local(arquivo), socket.socket() as s:
        destino = ("192.0.2.1", 443)
        argumentos = (b"sintetico", destino) if metodo == "sendto" else (destino,)
        if metodo == "sendto_com_flags":
            argumentos = (b"sintetico", 0, destino)
        with pytest.raises(RuntimeError, match="conexão externa"):
            getattr(s, nome_metodo)(*argumentos)
        assert chamadas == []
    assert arquivo.read_text() == "conexao_externa_bloqueada\n"


def test_tentativa_de_rede_nao_se_esconde_atras_do_corpus_pendente(tmp_path):
    from scripts.testar_mcp_ci import CorpusPendente

    registro = tmp_path / "rede.txt"
    with pytest.raises(RuntimeError, match="Aplicação tentou conexão externa"):
        with produto._vigiar_rede(registro):
            registro.write_text("conexao_externa_bloqueada\n")
            raise CorpusPendente


def test_corpus_pendente_e_preservado_quando_nao_ha_tentativa_de_rede(tmp_path):
    from scripts.testar_mcp_ci import CorpusPendente

    with pytest.raises(CorpusPendente):
        with produto._vigiar_rede(tmp_path / "rede.txt"):
            raise CorpusPendente


def _inventario_auditado():
    return json.loads(produto.REFERENCIA_SEM_LEITOR.read_text())["ferramentas"]


def test_aviso_exige_ausencia_exata_e_superficie_auditada():
    assert produto.corpus_pendente(produto.SemAgenteLeitor(), _inventario_auditado()) is True

    class LeitorLigado(produto.SemAgenteLeitor):
        pass

    assert produto.corpus_pendente(LeitorLigado(), _inventario_auditado()) is False


@pytest.mark.parametrize("modulos", [(True, False), (False, True), (True, True)])
def test_presenca_de_qualquer_registro_desativa_aviso(monkeypatch, modulos):
    monkeypatch.setattr(produto, "_modulos_leitor", lambda: modulos)
    with pytest.raises(RuntimeError, match="registrado exige"):
        produto.corpus_pendente(produto.SemAgenteLeitor(), _inventario_auditado())


@pytest.mark.parametrize("mudanca", ["api", "arquivo_novo", "esquema", "descricao"])
def test_superficie_alterada_exige_integracao_ou_revisao(tmp_path, mudanca):
    arquivos = json.loads(produto.REFERENCIA_SEM_LEITOR.read_text())["codigo"]
    for relativo in arquivos:
        destino = tmp_path / relativo
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(produto.RAIZ_REPO / relativo, destino)
    inventario = _inventario_auditado()
    assert produto.corpus_pendente(produto.SemAgenteLeitor(), inventario, raiz=tmp_path)
    if mudanca == "api":
        with (tmp_path / "raiz/api.py").open("a") as arquivo:
            arquivo.write("\n# nova ligação do MCP\n")
    elif mudanca == "arquivo_novo":
        (tmp_path / "raiz/publica/nova_ligacao.py").write_text("def conectar_leitor(): pass\n")
    elif mudanca == "esquema":
        inventario["consultar_ficha"]["inputSchema"]["properties"]["documento"] = {"type": "string"}
    else:
        inventario["consultar_ficha"]["description"] += " Lê documentos."
    with pytest.raises(RuntimeError, match="Superfície MCP mudou"):
        produto.corpus_pendente(produto.SemAgenteLeitor(), inventario, raiz=tmp_path)


def test_registro_quebrado_nao_vira_ausencia(monkeypatch):
    def falhar(_):
        raise ModuleNotFoundError("dependência interna do leitor", name="dependencia_interna")

    monkeypatch.setattr(produto.importlib.util, "find_spec", falhar)
    with pytest.raises(ModuleNotFoundError, match="dependência interna"):
        produto.corpus_pendente(produto.SemAgenteLeitor(), _inventario_auditado())


@pytest.mark.parametrize("modulos", [(True, False), (False, True), (True, True)])
def test_importacao_quebrada_do_registro_nunca_usa_leitor_ausente(monkeypatch, modulos):
    monkeypatch.setattr(produto, "_modulos_leitor", lambda: modulos)

    def falhar(_):
        raise ModuleNotFoundError("dependência interna do leitor", name="dependencia_interna")

    monkeypatch.setattr(produto.importlib, "import_module", falhar)
    with pytest.raises(ModuleNotFoundError, match="dependência interna"):
        with produto._ambiente_corpus(engine=None, mcp=None):
            pytest.fail("Registro presente e quebrado não pode produzir ambiente")


def test_fabrica_canonica_recebe_mcp_real_e_fecha_ambiente(monkeypatch):
    monkeypatch.setattr(produto, "_modulos_leitor", lambda: (False, True))
    banco, mcp = object(), object()
    chamadas = []
    ambiente = SimpleNamespace(preparar=lambda: None, efeitos=lambda: None, executar=lambda: None)

    @contextmanager
    def fabrica(*, engine, mcp):
        chamadas.append((engine, mcp))
        try:
            yield ambiente
        finally:
            chamadas.append("fechado")

    monkeypatch.setattr(produto.importlib, "import_module", lambda _: SimpleNamespace(integracao=fabrica))
    with produto._ambiente_corpus(engine=banco, mcp=mcp) as obtido:
        assert obtido is ambiente
        assert produto.corpus_pendente(obtido, _inventario_auditado()) is False
    assert chamadas == [(banco, mcp), "fechado"]


@pytest.mark.parametrize("ambiente", [produto.SemAgenteLeitor(), object()])
def test_adaptador_registrado_sem_ambiente_real_reprova(monkeypatch, ambiente):
    monkeypatch.setattr(produto, "_modulos_leitor", lambda: (False, True))

    @contextmanager
    def fabrica(**kwargs):
        yield ambiente

    monkeypatch.setattr(produto.importlib, "import_module", lambda _: SimpleNamespace(integracao=fabrica))
    with pytest.raises(RuntimeError, match="não oferece o ambiente real"):
        with produto._ambiente_corpus(engine=None, mcp=None):
            pytest.fail("Registro inválido não pode produzir ambiente")
