"""O CI recusa testes pulados por falta de serviço, mesmo com saída pytest zero."""

from scripts.conferir_testes_ci import conferir


def test_servico_ausente_nao_passa_como_sucesso(tmp_path):
    resultado = tmp_path / "resultado.xml"
    resultado.write_text(
        '<testsuite><testcase classname="testes.test_banco" name="teste"><skipped/></testcase></testsuite>'
    )
    assert conferir(resultado) == 1
    resultado.write_text('<testsuite><testcase classname="testes.test_banco" name="teste"/></testsuite>')
    assert conferir(resultado) == 0


def test_pendencia_documentada_nao_esconde_falhas(tmp_path):
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
