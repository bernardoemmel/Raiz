"""Entradas administrativas não aceitam fontes, UFs ou hipóteses ambíguas."""

import json

import typer
from typer.testing import CliRunner

from raiz.prospeccao_operacao import registrar

app = typer.Typer()
registrar(app)
runner = CliRunner()


def test_simulador_sem_preco_nao_inventa_receita():
    r = runner.invoke(app, ["simular-receita"])
    assert r.exit_code == 0
    dados = json.loads(r.stdout)
    assert set(dados) == {"por_ficha", "por_lote", "assinatura"}
    assert all(x["por_cliente"]["mes"]["receita_bruta_rs"] is None for x in dados.values())


def test_uf_e_fonte_invalidas_falham_antes_de_abrir_banco(monkeypatch):
    def nao_abrir():
        raise AssertionError("Não deveria abrir banco")

    monkeypatch.setattr("raiz.banco.engine", nao_abrir)
    for args in (
        ["atualizar-base", "--ufs", "PA,ZZ"],
        ["coletar-compromissos", "--fonte", "fonte-desconhecida"],
        ["coletar-compromissos", "--bbox", "NaN,0,1,1"],
        ["coletar-compromissos", "--retomar-desde", "ontem"],
    ):
        r = runner.invoke(app, args)
        assert r.exit_code == 1 and not isinstance(r.exception, AssertionError)


def test_ufs_novas_por_padrao_e_falha_de_checkpoint_tem_exit_code(monkeypatch):
    monkeypatch.setattr("raiz.banco.engine", lambda: object())
    recebidos = []

    def atualizar(_eng, **kwargs):
        recebidos.append(kwargs)
        return {"falhas": 0, "fichas": {"pendente": True}}

    monkeypatch.setattr("raiz.prospeccao_cobertura.atualizar_base", atualizar)
    r = runner.invoke(app, ["atualizar-base"])
    assert r.exit_code == 1 and recebidos[0]["ufs"] is None
