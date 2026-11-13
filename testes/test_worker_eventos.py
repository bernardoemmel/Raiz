"""O comando operacional fornece o cofre e encerra a exportação dos spans."""

from types import SimpleNamespace

from raiz import banco, cli, pessoal
from raiz.publica import telemetria, trabalhos, webhooks


def test_worker_fornece_cofre_a_entrega(monkeypatch):
    chamadas = []

    class Conexao:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, *args):
            return SimpleNamespace(scalars=lambda: [42])

    eng = SimpleNamespace(connect=lambda: Conexao())
    cofre = object()
    monkeypatch.setattr(banco, "engine", lambda: eng)
    monkeypatch.setattr(pessoal, "Cofre", lambda: cofre)
    monkeypatch.setattr(
        telemetria, "configurar_telemetria", lambda: SimpleNamespace(shutdown=lambda: chamadas.append("fim"))
    )
    monkeypatch.setattr(trabalhos, "executar_proximo", lambda e: chamadas.append("trabalho"))
    monkeypatch.setattr(webhooks, "entregar_proximo", lambda e, cid, *, cofre: chamadas.append((e, cid, cofre)))
    cli.api_worker(uma=True)
    assert chamadas == ["trabalho", (eng, 42, cofre), "fim"]


def test_worker_nao_imprime_excecao_com_dado_privado(monkeypatch, capsys):
    import pytest
    import typer

    monkeypatch.setattr(banco, "engine", lambda: object())
    monkeypatch.setattr(pessoal, "Cofre", lambda: object())
    monkeypatch.setattr(telemetria, "configurar_telemetria", lambda: SimpleNamespace(shutdown=lambda: None))

    def falhar(*args):
        raise RuntimeError("token privado que não pode ir ao terminal")

    monkeypatch.setattr(trabalhos, "executar_proximo", falhar)
    with pytest.raises(typer.Exit):
        cli.api_worker(uma=True)
    saida = capsys.readouterr().err
    assert "RuntimeError" in saida and "privado" not in saida
