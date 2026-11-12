"""A CLI administrativa nunca imprime retorno privado, nomes de arquivos ou exceções."""

import io
import json
import tarfile

import pytest

from raiz.executor import publicar_entrada as cli

CANARIO = "Pessoa Sintética contato@example.invalid token=segredo-de-teste"


def test_sucesso_emite_somente_resumo_fechado(monkeypatch, capsys, tmp_path):
    pasta = tmp_path / CANARIO
    chamadas = []

    def publicar(recebida):
        chamadas.append(recebida)
        return {"nome": CANARIO, "contato": CANARIO, "token": CANARIO, "assets": [{"nome": CANARIO}]}

    monkeypatch.setattr(cli, "publicar_pacotes", publicar)
    assert cli.main([str(pasta)]) == 0
    saida = capsys.readouterr()
    assert chamadas == [pasta]
    assert json.loads(saida.out) == {"estado": "publicado"}
    assert saida.err == "" and CANARIO not in saida.out


@pytest.mark.parametrize("erro", [ValueError, OSError, tarfile.ReadError])
def test_erro_emite_mensagem_fixa_sem_traceback(monkeypatch, capsys, erro):
    def falhar(_):
        raise erro(CANARIO)

    monkeypatch.setattr(cli, "publicar_pacotes", falhar)
    assert cli.main([CANARIO]) == 1
    saida = capsys.readouterr()
    assert saida.out == ""
    assert saida.err == "Publicação interrompida. Confira a configuração e os pacotes de entrada.\n"
    assert CANARIO not in saida.err and "Traceback" not in saida.err


@pytest.mark.parametrize("argumentos", [[], [CANARIO, CANARIO]])
def test_uso_invalido_nao_publica_nem_ecoa_argumentos(monkeypatch, capsys, argumentos):
    monkeypatch.setattr(cli, "publicar_pacotes", lambda _: pytest.fail("não deve publicar"))
    assert cli.main(argumentos) == 2
    saida = capsys.readouterr()
    assert saida.out == ""
    assert saida.err == "uso: python -m raiz.executor.publicar_entrada <pasta-dos-pacotes>\n"


@pytest.mark.parametrize("caso", ["pacote", "membro", "tipo"])
def test_validacao_nao_inclui_nomes_arbitrarios_na_excecao(monkeypatch, tmp_path, caso):
    class ArmazemLocal:
        def verificar_publicacao(self):
            pass

        def por_bytes(self, *_):
            pytest.fail("entrada inválida não deve ser gravada")

    monkeypatch.setattr(cli, "ArmazemRelease", ArmazemLocal)
    monkeypatch.setattr(cli, "do_config", ArmazemLocal)
    pacote = tmp_path / (f"{CANARIO}.tar.gz" if caso == "pacote" else "raiz_PA.tar.gz")
    if caso == "pacote":
        pacote.touch()
    else:
        with tarfile.open(pacote, "w:gz") as tar:
            nome = f"{CANARIO}/arquivo.csv" if caso == "membro" else f"PA/{CANARIO}.txt"
            membro = tarfile.TarInfo(nome)
            tar.addfile(membro, io.BytesIO())
    with pytest.raises(ValueError) as capturada:
        cli.publicar_pacotes(tmp_path)
    assert CANARIO not in str(capturada.value)
    assert "contrato de entrada" in str(capturada.value)
