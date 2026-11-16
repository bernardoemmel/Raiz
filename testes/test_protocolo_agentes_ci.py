"""A conferência falha fechada e não propaga tokens na linha de comando, nos erros ou no relatório."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts import verificar_protocolo_agentes as conferencia


def test_registro_oficial_renderiza_sem_publicar():
    teste = conferencia.manifesto()
    assert teste["remotes"] == [{"type": "streamable-http", "url": "https://raiz.invalid/mcp/"}]
    real = conferencia.manifesto("https://api.raiz.example/")
    assert real["name"] == "io.github.bernardoemmel/raiz"
    assert real["remotes"][0]["url"] == "https://api.raiz.example/mcp/"
    assert "publicar somente" in real["_meta"]["io.modelcontextprotocol.registry/publisher-provided"]["publication"]


@pytest.mark.parametrize(
    "base",
    [
        "http://api.raiz.example",
        "https://usuario:segredo@api.raiz.example",
        "https://api.raiz.example?token=segredo",
        "https://api.raiz.example#segredo",
        "https://api.raiz.example/mcp",
        "https://localhost",
        "https://api.raiz.example:8000",
    ],
)
def test_manifesto_recusa_origem_invalida(base):
    with pytest.raises(ValueError):
        conferencia.manifesto(base)


def test_esquema_oficial_nao_muda_sem_conferencia(tmp_path, monkeypatch):
    adulterado = tmp_path / "schema.json"
    adulterado.write_text("{}")
    monkeypatch.setattr(conferencia, "SCHEMA", adulterado)
    with pytest.raises(ValueError, match="hash conferido"):
        conferencia.manifesto()


def test_erro_externo_nao_copia_saida_ou_credencial(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 3, "corpo privado", "Bearer segredo-sintetico"),
    )
    with pytest.raises(RuntimeError) as exc:
        conferencia.executar(["mcp-inspector", "--cli"])
    assert "segredo" not in str(exc.value) and "privado" not in str(exc.value)


def test_diagnostico_do_inspector_preserva_apenas_codigos_conhecidos():
    comando = ["mcp-inspector", "--method", "initialize"]
    r = subprocess.CompletedProcess(
        comando, 3, "Bearer segredo", '{"error":{"code":"auth_required","message":"Bearer segredo"}}'
    )
    erro = conferencia.FalhaFerramenta(comando, r)
    assert erro.diagnostico == {
        "programa": "mcp-inspector",
        "codigo_saida": 3,
        "metodo": "initialize",
        "motivo": "auth_required",
    }
    assert "segredo" not in json.dumps(erro.diagnostico)


def test_inspector_tem_config_privada_e_reporta_somente_metadados(monkeypatch):
    from raiz.publica.contrato import RESUMO
    from raiz.publica.servidor_mcp import ESCOPOS_FERRAMENTAS

    configuracoes = []
    token = "oauth-sintetico-sem-credencial-real"

    def executar(comando, *, ambiente):
        assert token not in " ".join(comando)
        arquivo = Path(comando[comando.index("--config") + 1])
        assert os.stat(arquivo).st_mode & 0o777 == 0o600
        config = json.loads(arquivo.read_text())["mcpServers"]["raiz"]
        assert config["headers"]["Authorization"] == "Bearer " + token
        assert ambiente["MCP_INSPECTOR_SECRET_STORE"] == "memory"
        assert config["protocolEra"] == "modern"
        configuracoes.append(arquivo)
        metodo = comando[comando.index("--method") + 1]
        if metodo == "tools/call":
            argumentos = json.loads(comando[comando.index("--tool-args-json") + 1])
            assert argumentos.get("idempotency_key"), "Inspector deve preservar a chave da intenção"
        resposta = {
            "initialize": {"protocolVersion": conferencia.PROTOCOLO, "instructions": RESUMO},
            "tools/list": {"tools": [{"name": n} for n in ESCOPOS_FERRAMENTAS]},
            "tools/call": {"structuredContent": {"pedido_id": "uuid-sintetico", "estado": "submitted"}},
        }[metodo]
        if "acompanhar_contato" in comando:
            resposta = {"structuredContent": {"pedido_id": "uuid-sintetico", "estado": "completed"}}
        return subprocess.CompletedProcess(comando, 0, json.dumps({"result": resposta}), "")

    monkeypatch.setattr(conferencia, "executar", executar)
    resultado = conferencia.conferir_mcp("http://localhost:18000/mcp/", token)
    assert token not in json.dumps(resultado)
    assert resultado["protocolo"] == conferencia.PROTOCOLO
    assert resultado["estado"] == "completed"
    assert not any(p.exists() for p in configuracoes)


def test_inspector_rejeita_negociacao_que_regrediu(monkeypatch):
    monkeypatch.setattr(
        conferencia,
        "executar",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, '{"result":{"protocolVersion":"2025-11-25"}}', ""),
    )
    with pytest.raises(ValueError, match="protocolo"):
        conferencia.conferir_mcp("http://localhost:18000/mcp/", "sintetico")
