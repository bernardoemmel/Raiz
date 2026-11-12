"""A exceção autorizada é ausência de implementação, nunca falha da integração."""

import json

from scripts import testar_mcp_ci as ci


def test_ausencia_gera_aviso_sem_alegar_ensaio(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ci, "disponivel", lambda: False)
    assert ci.main(["--resultado", str(tmp_path)]) == 0
    assert "::warning" in capsys.readouterr().out
    assert json.loads((tmp_path / "integracao.json").read_text())["ensaios_executados"] is False


def test_implementacao_ou_sdk_nao_podem_ser_tratados_como_ausentes(tmp_path):
    assert ci.disponivel(tmp_path) is False
    p = tmp_path / "raiz/publica/servidor_mcp.py"
    p.parent.mkdir(parents=True)
    p.write_text("raise RuntimeError('servidor quebrado')")
    assert ci.disponivel(tmp_path) is True
    p.unlink()
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["mcp>=2"]')
    assert ci.disponivel(tmp_path) is True


def test_mcp_presente_com_erro_reprova_sem_vazar(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ci, "disponivel", lambda: True)

    def falhar(_):
        raise RuntimeError("contato@exemplo.invalid")

    monkeypatch.setattr(ci, "executar", falhar)
    assert ci.main(["--resultado", str(tmp_path)]) == 1
    saida = capsys.readouterr().out
    assert "::error" in saida and "contato@" not in saida
    assert json.loads((tmp_path / "integracao.json").read_text())["estado"] == "falha"


def test_detecao_presente_nao_executa_nem_aprova(tmp_path, monkeypatch):
    monkeypatch.setattr(ci, "disponivel", lambda: True)
    assert ci.main(["--detectar", "--resultado", str(tmp_path)]) == 0
    dado = json.loads((tmp_path / "integracao.json").read_text())
    assert dado["estado"] == "presente" and dado["ensaios_executados"] is False
