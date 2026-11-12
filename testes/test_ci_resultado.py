"""O CI recusa testes pulados e exige prova da execução estadual quando obrigatória."""

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
