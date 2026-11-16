"""O portão combina os jobs sem perder casos, falhas nem a execução estadual."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.conferir_testes_ci import conferir


@pytest.fixture(autouse=True)
def ambiente_do_portao(monkeypatch):
    monkeypatch.delenv("RAIZ_TESTE_PA_OBRIGATORIO", raising=False)


def test_servico_ausente_nao_passa_como_sucesso(tmp_path):
    resultado = tmp_path / "resultado.xml"
    resultado.write_text(
        '<testsuite><testcase classname="testes.test_banco" name="teste"><skipped/></testcase></testsuite>'
    )
    assert conferir(resultado) == 1
    resultado.write_text('<testsuite><testcase classname="testes.test_banco" name="teste"/></testsuite>')
    assert conferir(resultado) == 0


def test_estadual_pulado_nao_esconde_falhas(tmp_path):
    resultado = tmp_path / "resultado.xml"
    resultado.write_text(
        '<testsuite><testcase classname="testes.test_lote" '
        'name="test_lote_do_para_inteiro_fecha_ou_diz_o_que_falta"><skipped/></testcase>'
        '<testcase classname="testes.test_banco" name="teste"><failure/></testcase></testsuite>'
    )
    assert conferir(resultado) == 1
    resultado.write_text("<testsuite/>")
    assert conferir(resultado) == 1


def test_falha_esperada_precisa_executar_o_teste(tmp_path):
    resultado = tmp_path / "resultado.xml"
    corpo = (
        '<testsuite><testcase classname="testes.test_restauracao" '
        'name="test_plantio_da_7_a_9_pct_no_central_r11"><skipped type="{}"/></testcase></testsuite>'
    )
    resultado.write_text(corpo.format("pytest.xfail"))
    assert conferir(resultado) == 0
    resultado.write_text(corpo.format("pytest.skip"))
    assert conferir(resultado) == 1


def _caso_estadual(conteudo=""):
    return (
        '<testcase classname="testes.test_lote" '
        f'name="test_lote_do_para_inteiro_fecha_ou_diz_o_que_falta">{conteudo}</testcase>'
    )


@pytest.mark.parametrize("obrigatorio", [None, "0", "1"])
def test_estadual_pulado_falha_mesmo_sem_exigir_presenca_no_xml(tmp_path, capsys, monkeypatch, obrigatorio):
    resultado = tmp_path / "resultado.xml"
    resultado.write_text(f"<testsuite>{_caso_estadual('<skipped/>')}</testsuite>")
    if obrigatorio is not None:
        monkeypatch.setenv("RAIZ_TESTE_PA_OBRIGATORIO", obrigatorio)
    assert conferir(resultado) == 1
    saida = capsys.readouterr().out
    assert "FALHA: teste pulado:" in saida and "PENDENTE:" not in saida


@pytest.mark.parametrize("quantidade", [0, 1, 2])
def test_modo_obrigatorio_exige_um_unico_teste_estadual(tmp_path, quantidade):
    resultado = tmp_path / "resultado.xml"
    resultado.write_text(
        '<testsuites><testsuite><testcase classname="testes.test_banco" name="teste"/>'
        f"{_caso_estadual() * quantidade}</testsuite></testsuites>"
    )
    assert conferir(resultado, pa_obrigatorio=True) == int(quantidade != 1)


@pytest.mark.parametrize(
    "resultado_estadual", ["<skipped/>", '<skipped type="pytest.xfail"/>', "<failure/>", "<error/>"]
)
def test_modo_obrigatorio_recusa_teste_estadual_sem_aprovacao(tmp_path, resultado_estadual, capsys):
    resultado = tmp_path / "resultado.xml"
    resultado.write_text(f"<testsuite>{_caso_estadual(resultado_estadual)}</testsuite>")
    assert conferir(resultado, pa_obrigatorio=True) == 1
    saida = capsys.readouterr().out
    assert "FALHA:" in saida and "PENDENTE:" not in saida


def test_ambiente_liga_execucao_obrigatoria(tmp_path, monkeypatch):
    resultado = tmp_path / "resultado.xml"
    resultado.write_text(f"<testsuite>{_caso_estadual('<skipped/>')}</testsuite>")
    monkeypatch.setenv("RAIZ_TESTE_PA_OBRIGATORIO", "1")
    assert conferir(resultado) == 1
    resultado.write_text(f"<testsuite>{_caso_estadual()}</testsuite>")
    assert conferir(resultado) == 0


@pytest.mark.parametrize("conteudo", [None, "<testsuite>"])
def test_resultado_ausente_ou_invalido_falha_sem_imprimir_caminho(tmp_path, conteudo, capsys):
    resultado = tmp_path / "contato-sintetico-privado.xml"
    if conteudo is not None:
        resultado.write_text(conteudo)
    assert conferir(resultado, pa_obrigatorio=True) == 1
    assert capsys.readouterr().out == "FALHA: resultado de testes ausente ou inválido.\n"


def _resultado(pasta, nome, casos):
    arquivo = pasta / nome
    arquivo.write_text(f"<testsuites><testsuite>{casos}</testsuite></testsuites>")
    return arquivo


def _caso_geral(conteudo=""):
    return f'<testcase classname="testes.test_banco" name="teste">{conteudo}</testcase>'


def test_relatorios_complementares_equivalem_a_suite_completa(tmp_path, capsys):
    tir = (
        '<testcase classname="testes.test_restauracao" name="test_plantio_da_7_a_9_pct_no_central_r11">'
        '<skipped type="pytest.xfail" message="divergência conhecida"/></testcase>'
    )
    geral = _resultado(tmp_path, "geral.xml", _caso_geral() + tir)
    privado = _resultado(tmp_path, "privado.xml", _caso_estadual())
    completo = _resultado(tmp_path, "completo.xml", _caso_geral() + tir + _caso_estadual())
    assert conferir(geral, privado) == conferir(completo, pa_obrigatorio=True) == 0
    assert capsys.readouterr().out.count("PENDENTE: divergência conhecida da TIR") == 2


@pytest.mark.parametrize("quantidade", [0, 2])
def test_relatorios_divididos_sempre_exigem_um_unico_estadual(tmp_path, quantidade, capsys):
    geral = _resultado(tmp_path, "geral.xml", _caso_geral())
    privado = _resultado(tmp_path, "privado.xml", _caso_geral().replace('name="teste"', 'name="outro"'))
    if quantidade:
        geral = _resultado(tmp_path, "geral.xml", _caso_geral() + _caso_estadual())
        privado = _resultado(tmp_path, "privado.xml", _caso_estadual())
    assert conferir(geral, privado, pa_obrigatorio=False) == 1
    assert "exatamente uma vez" in capsys.readouterr().out


@pytest.mark.parametrize("em_arquivos_distintos", [False, True])
def test_caso_geral_duplicado_nao_passa(tmp_path, em_arquivos_distintos, capsys):
    geral = _resultado(tmp_path, "geral.xml", _caso_geral())
    privado = _resultado(tmp_path, "privado.xml", _caso_estadual() + _caso_geral())
    if em_arquivos_distintos:
        assert conferir(geral, privado) == 1
    else:
        completo = _resultado(tmp_path, "completo.xml", _caso_estadual() + _caso_geral() * 2)
        assert conferir(completo) == 1
    assert "FALHA: teste duplicado:" in capsys.readouterr().out


def test_repetir_o_mesmo_relatorio_na_cli_nao_duplica_prova(tmp_path):
    resultado = _resultado(tmp_path, "completo.xml", _caso_estadual() + _caso_geral())
    assert conferir(resultado, resultado) == 1


@pytest.mark.parametrize("falha", ["<skipped/>", '<skipped type="pytest.xfail"/>', "<failure/>", "<error/>"])
@pytest.mark.parametrize("no_estadual", [False, True])
def test_um_relatorio_aprovado_nao_esconde_falha_do_outro(tmp_path, falha, no_estadual):
    geral = _resultado(tmp_path, "geral.xml", _caso_geral("" if no_estadual else falha))
    privado = _resultado(tmp_path, "privado.xml", _caso_estadual(falha if no_estadual else ""))
    assert conferir(geral, privado) == 1


@pytest.mark.parametrize(
    "conteudo",
    [
        None,
        "<testsuite>",
        "<testsuite/>",
        f"<outro>{_caso_estadual()}</outro>",
        '<testsuite><testcase name="teste"/></testsuite>',
    ],
)
def test_qualquer_relatorio_ausente_ou_invalido_falha_com_erro_fixo(tmp_path, conteudo, capsys):
    completo = _resultado(tmp_path, "completo.xml", _caso_estadual() + _caso_geral())
    invalido = tmp_path / "contato-sintetico-privado.xml"
    if conteudo is not None:
        invalido.write_text(conteudo)
    for arquivos in [(completo, invalido), (invalido, completo)]:
        assert conferir(*arquivos) == 1
        assert capsys.readouterr().out == "FALHA: resultado de testes ausente ou inválido.\n"


@pytest.mark.parametrize("executar", [False, True])
def test_xfail_real_so_e_aceito_quando_pytest_executa_o_corpo(tmp_path, executar, capsys):
    pasta = tmp_path / "testes"
    pasta.mkdir()
    (pasta / "__init__.py").touch()
    teste = pasta / "test_restauracao.py"
    teste.write_text(
        "import pytest\n"
        f'@pytest.mark.xfail(run={executar}, reason="divergência conhecida")\n'
        "def test_plantio_da_7_a_9_pct_no_central_r11():\n"
        "    assert False\n"
    )
    resultado = tmp_path / "resultado.xml"
    processo = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(teste), f"--junitxml={resultado}"],
        cwd=tmp_path,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_ADDOPTS": ""},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert processo.returncode == 0, processo.stdout + processo.stderr
    assert conferir(resultado) == int(not executar)
    assert ("PENDENTE:" in capsys.readouterr().out) == executar


@pytest.mark.parametrize("modo", ["dividido", "completo", "ausente", "sem_argumentos"])
def test_cli_aceita_um_ou_varios_arquivos_e_falha_sem_todos_os_resultados(tmp_path, modo):
    geral = _resultado(tmp_path, "geral.xml", _caso_geral())
    privado = _resultado(tmp_path, "privado.xml", _caso_estadual())
    completo = _resultado(tmp_path, "completo.xml", _caso_geral() + _caso_estadual())
    arquivos = {
        "dividido": [geral, privado],
        "completo": [completo],
        "ausente": [completo, tmp_path / "contato-sintetico-privado.xml"],
        "sem_argumentos": [],
    }[modo]
    processo = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/conferir_testes_ci.py"), *arquivos],
        env={**os.environ, "RAIZ_TESTE_PA_OBRIGATORIO": "1"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert processo.returncode == int(modo in {"ausente", "sem_argumentos"})
    assert processo.stderr == ""
    if processo.returncode:
        assert processo.stdout == "FALHA: resultado de testes ausente ou inválido.\n"
