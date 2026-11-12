"""Um passo always() nunca publica nomes privados deixados por um executor antigo."""

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts.conferir_atestacao_privada import main


def _passo_atestar(nome):
    workflow = Path(__file__).parents[1] / ".github/workflows" / nome
    jobs = yaml.safe_load(workflow.read_text())["jobs"]
    passos = [p for job in jobs.values() for p in job["steps"] if p.get("id") == "atestar"]
    assert len(passos) == 1
    return passos[0]


@pytest.mark.parametrize(
    "conteudo",
    [
        "",
        "Nome Particular contato@example.invalid",
        "a" * 64 + "  nome-privado.csv",
        "a" * 64 + "  privado-sha256-" + "b" * 64,
        "a" * 256_001,
    ],
)
def test_recusa_lista_legada_ou_invalida_sem_ecoa_la(tmp_path, capsys, conteudo):
    arquivo = tmp_path / "atestar-privado.txt"
    arquivo.write_text(conteudo)
    assert main([str(arquivo)]) == 1
    saida = capsys.readouterr()
    assert saida.out == ""
    assert saida.err == "::error::Atestação privada bloqueada: lista ausente, inválida ou com subject legado.\n"


def test_aceita_somente_subjects_derivados_dos_bytes(tmp_path, capsys):
    digest = hashlib.sha256(b"bytes sinteticos").hexdigest()
    arquivo = tmp_path / "atestar-privado.txt"
    arquivo.write_text(f"{digest}  privado-sha256-{digest}\n")
    assert main([str(arquivo)]) == 0
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("nome", ["processar-estados.yml", "publicar-metadados.yml"])
def test_workflow_valida_antes_de_liberar_atestacao_privada(nome):
    comando = _passo_atestar(nome)["run"]
    assert comando.index("python3 scripts/conferir_atestacao_privada.py") < comando.index('echo "privado=1"')
    assert "|| true" not in comando


@pytest.mark.parametrize(
    ("checkout_atual", "lista_valida", "aceita"),
    [("success", True, True), ("success", False, False), ("skipped", True, True), ("failure", True, False)],
)
def test_gate_usa_checkout_atual_e_mantem_falha_fechada(tmp_path, checkout_atual, lista_valida, aceita):
    passo = _passo_atestar("processar-estados.yml")
    assert passo["working-directory"] == (
        "${{ steps.publicador_checkout.outcome == 'success' && 'publicador-atual' || '.' }}"
    )
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    diretorio = checkout / "publicador-atual" if checkout_atual == "success" else checkout
    if checkout_atual != "failure":
        (diretorio / "scripts").mkdir(parents=True)
        shutil.copyfile(
            Path(__file__).parents[1] / "scripts/conferir_atestacao_privada.py",
            diretorio / "scripts/conferir_atestacao_privada.py",
        )
    if checkout_atual == "success":
        # O executor preservado na fila não tem o verificador novo na raiz.
        assert not (checkout / "scripts/conferir_atestacao_privada.py").exists()

    temporario = tmp_path / "runner-temp"
    temporario.mkdir()
    digest = hashlib.sha256(b"bytes sinteticos").hexdigest()
    subject = f"privado-sha256-{digest}" if lista_valida else "arquivo-privado-legado.csv"
    (temporario / "atestar-privado.txt").write_text(f"{digest}  {subject}\n")
    saida = tmp_path / "github-output"
    saida.touch()
    resultado = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", passo["run"]],
        cwd=diretorio,
        env=os.environ | {"RUNNER_TEMP": str(temporario), "GITHUB_OUTPUT": str(saida)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (resultado.returncode == 0) is aceita
    assert saida.read_text() == ("privado=1\n" if aceita else "")
    if not lista_valida:
        assert subject not in resultado.stdout + resultado.stderr
        assert "Atestação privada bloqueada" in resultado.stderr
