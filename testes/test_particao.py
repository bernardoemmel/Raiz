"""A divisão da suíte em partes do CI cobre todos os arquivos uma vez e o juntador recusa parte faltando."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.juntar_partes_pytest import juntar
from testes.particao import DURACOES, dividir, ler_parte

RAIZ = Path(__file__).parents[1]


def test_divisao_cobre_cada_arquivo_exatamente_uma_vez_e_equilibra():
    duracoes = json.loads(DURACOES.read_text(encoding="utf-8"))
    arquivos = [*duracoes, "testes/test_arquivo_novo_sem_medida.py"]
    destino = dividir(arquivos, duracoes, 4)
    assert set(destino) == set(arquivos)
    assert set(destino.values()) == {1, 2, 3, 4}
    carga = [0.0] * 4
    for arquivo, parte in destino.items():
        carga[parte - 1] += duracoes.get(arquivo, 0)
    maior_arquivo = max(duracoes.values())
    assert max(carga) - min(carga) <= maior_arquivo
    # Mesma entrada em qualquer ordem dá a mesma divisão em todas as máquinas.
    assert dividir(list(reversed(arquivos)), duracoes, 4) == destino


def test_tabela_de_duracoes_aponta_para_arquivos_que_existem():
    duracoes = json.loads(DURACOES.read_text(encoding="utf-8"))
    ausentes = [a for a in duracoes if not (RAIZ / a).is_file()]
    # Arquivo removido só deixa de pesar; poucos ausentes não quebram nada, muitos indicam tabela velha.
    assert len(ausentes) <= len(duracoes) // 10


@pytest.mark.parametrize("texto", ["", "0/4", "5/4", "2", "a/b"])
def test_parte_invalida_e_recusada(texto):
    with pytest.raises(ValueError):
        ler_parte(texto)


def _junit(caminho: Path, parte: str, suite: int, casos: list[str]) -> Path:
    linhas = "".join(f'<testcase classname="testes.test_x" name="{c}" time="0"/>' for c in casos)
    caminho.write_text(
        f'<testsuites><testsuite name="pytest" tests="{len(casos)}"><properties>'
        f'<property name="raiz_parte" value="{parte}"/><property name="raiz_testes_na_suite" value="{suite}"/>'
        f"</properties>{linhas}</testsuite></testsuites>",
        encoding="utf-8",
    )
    return caminho


def test_juntador_aceita_partes_completas(tmp_path):
    a = _junit(tmp_path / "a.xml", "1/2", 3, ["t1", "t2"])
    b = _junit(tmp_path / "b.xml", "2/2", 3, ["t3"])
    saida = tmp_path / "junto.xml"
    assert juntar([a, b], 2, saida) == 0
    assert "t3" in saida.read_text(encoding="utf-8")


def test_juntador_recusa_parte_faltando_repetida_ou_teste_esquecido(tmp_path):
    a = _junit(tmp_path / "a.xml", "1/2", 3, ["t1", "t2"])
    b = _junit(tmp_path / "b.xml", "2/2", 3, ["t3"])
    curta = _junit(tmp_path / "c.xml", "2/2", 3, [])
    outra = _junit(tmp_path / "d.xml", "2/2", 4, ["t3"])
    saida = tmp_path / "junto.xml"
    assert juntar([a], 2, saida) == 1
    assert juntar([a, a], 2, saida) == 1
    assert juntar([a, curta], 2, saida) == 1
    assert juntar([a, outra], 2, saida) == 1
    assert juntar([a, b], 3, saida) == 1
    assert not saida.exists()


def test_parte_real_grava_tamanho_da_suite_no_junit(tmp_path):
    saida = tmp_path / "parte.xml"
    resultado = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "testes.particao",
            "--parte=1/1",
            "-p",
            "no:cacheprovider",
            "testes/test_particao.py::test_parte_invalida_e_recusada",
            f"--junitxml={saida}",
        ],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stdout[-2000:]
    texto = saida.read_text(encoding="utf-8")
    assert 'name="raiz_parte" value="1/1"' in texto
    assert 'name="raiz_testes_na_suite" value="5"' in texto
