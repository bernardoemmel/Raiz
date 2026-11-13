"""A CLI distingue verificação completa, diagnóstico parcial e falhas."""

import json
import subprocess
import sys

import pytest

from scripts import verificar_release_dados as V


def test_ajuda_independe_do_diretorio_atual(tmp_path):
    processo = subprocess.run(
        [sys.executable, str(V.CODIGO / "scripts/verificar_release_dados.py"), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "--cache" in processo.stdout and "--gh" in processo.stdout
    assert "/workspace/" not in processo.stdout and "--codigo" not in processo.stdout


@pytest.mark.parametrize("sem_atestacao,falha,saida", [(False, False, 0), (True, False, 2), (False, True, 1)])
def test_main_portatil_so_retorna_zero_para_verificacao_completa(tmp_path, monkeypatch, sem_atestacao, falha, saida):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setenv("PYTHONPATH", "")
    monkeypatch.setattr(V.sys, "path", list(sys.path))
    monkeypatch.setattr(V.logging, "disable", lambda *a: None)
    monkeypatch.setattr(V.warnings, "simplefilter", lambda *a: None)
    monkeypatch.setattr(V.os, "umask", lambda *a: 0)
    vistos = []

    def escopo(args, qual, cache, relatorio, publicador, metadados):
        assert args.gh == "gh"
        assert cache.pasta == tmp_path / "raiz" / "verificacao-release"
        vistos.append(qual)
        relatorio["escopos"][qual] = {"integridade_ok": True, "snapshot_estavel": True}

    def finais(args, cache, relatorio, publicador):
        for dados in relatorio["escopos"].values():
            dados["snapshot_final_estavel"] = not falha

    monkeypatch.setattr(V, "executar_escopo", escopo)
    monkeypatch.setattr(V, "conferir_snapshots_finais", finais)
    assert V.main(["--sem-atestacao"] if sem_atestacao else []) == saida
    assert vistos == ["publico", "privado"]
    relatorio = json.loads((tmp_path / "raiz/verificacao-release/relatorio.json").read_text())
    assert relatorio["verificacao_completa"] is (not falha and not sem_atestacao)
    assert relatorio["integridade_ok"] is (not falha)
    assert len(relatorio["validador_sha256"]) == 64
