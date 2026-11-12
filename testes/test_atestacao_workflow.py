"""Um passo always() nunca publica nomes privados deixados por um executor antigo."""

import hashlib
from pathlib import Path

import pytest
import yaml

from scripts.conferir_atestacao_privada import main


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
    workflow = Path(__file__).parents[1] / ".github/workflows" / nome
    jobs = yaml.safe_load(workflow.read_text())["jobs"]
    passos = [p for job in jobs.values() for p in job["steps"] if p.get("id") == "atestar"]
    assert len(passos) == 1
    comando = passos[0]["run"]
    assert comando.index("python3 scripts/conferir_atestacao_privada.py") < comando.index('echo "privado=1"')
    assert "|| true" not in comando
