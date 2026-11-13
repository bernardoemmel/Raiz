"""Entradas inválidas falham antes da coleta sem ir para logs do Actions via traceback."""

import json
import os
import subprocess
import sys

import pytest

from raiz import RAIZ_REPO
from raiz.calendario.arquivos import ErroSnapshot, ler

PESSOAL = "pessoa@example.invalid"
NOME = "Pessoa Sintética"


@pytest.mark.parametrize("comando", ["coletar", "importar"])
@pytest.mark.parametrize("entrada", ["pydantic", "json", "ausente"])
def test_cli_nao_imprime_entrada_pessoal_ao_rejeitar_snapshot(tmp_path, comando, entrada):
    arquivo = tmp_path / f"{PESSOAL}.json"
    if entrada == "pydantic":
        arquivo.write_text(json.dumps({"eventos": [{"id": PESSOAL, "nome_dono": NOME}], "fontes": []}))
    elif entrada == "json":
        arquivo.write_text('{"eventos": [' + PESSOAL + NOME)
    saida = tmp_path / "saida"
    argumentos = (
        ["coletar", "--sem-banco", "--anterior", str(arquivo), "--saida", str(saida)]
        if comando == "coletar"
        else ["importar", str(arquivo)]
    )
    resultado = subprocess.run(
        [sys.executable, "-c", "from raiz.cli import app; app()", "calendario", *argumentos],
        cwd=RAIZ_REPO,
        env=os.environ | {"GITHUB_OUTPUT": str(tmp_path / "github-output")},
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert resultado.returncode != 0
    output = resultado.stdout + resultado.stderr
    assert PESSOAL not in output and NOME not in output
    assert "conteúdo omitido" in output
    assert "input_value" not in output and "Traceback" not in output
    assert not (tmp_path / "github-output").exists()
    assert not saida.exists()


def test_leitor_direto_tambem_nao_expoe_validacao_pydantic(tmp_path):
    arquivo = tmp_path / "entrada.json"
    arquivo.write_text(json.dumps({"eventos": [{"id": PESSOAL}], "fontes": []}))
    with pytest.raises(ErroSnapshot, match="conteúdo omitido") as erro:
        ler(arquivo)
    assert PESSOAL not in str(erro.value)


def test_cli_nao_exibe_variaveis_locais_em_falhas_imprevistas():
    codigo = """
from raiz.cli import app
@app.command('falhar-teste')
def falhar():
    dado_do_dono = 'pessoa@example.invalid'
    raise RuntimeError('falha sintética')
app()
"""
    resultado = subprocess.run(
        [sys.executable, "-c", codigo, "falhar-teste"],
        cwd=RAIZ_REPO,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert resultado.returncode != 0
    assert "falha sintética" in resultado.stderr
    assert PESSOAL not in resultado.stderr + resultado.stdout


def test_validacao_compartilhada_com_mcp_nao_expoe_entrada():
    from raiz.calendario.arquivos import validar
    from testes.test_privacidade import CPF

    with pytest.raises(ErroSnapshot) as erro:
        validar({"eventos": [{"id": CPF}], "fontes": []})
    assert CPF not in str(erro.value)
    assert "conteúdo omitido" in str(erro.value)
