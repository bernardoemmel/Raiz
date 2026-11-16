"""Cálculos derivados não sobrevivem a nova sugestão, composição ou critério."""

import copy

import pytest

from raiz.pedidos.revisao import revisao_lote
from raiz.publica.apresentacao import pedido as pedido_publico


@pytest.fixture
def retrato():
    opcoes = [
        {
            "id": "barata",
            "itens": [{"cod_imovel": "FICTICIO-1", "papel": "lote"}, {"cod_imovel": "FICTICIO-2", "papel": "reserva"}],
        }
    ]
    return {
        "id": 10,
        "base": {"fazendas": 2},
        "opcoes": opcoes,
        "premissas_versao": "v1",
        "otimizador_versao": "solver-v1",
    }


def test_revisao_estavel_sem_depender_de_autorizacao_de_geometria(retrato):
    primeira = revisao_lote("pedido", {"meta": 100}, retrato, retrato["opcoes"])
    visiveis = copy.deepcopy(retrato["opcoes"])
    visiveis[0]["itens"][0].update(geometria={"type": "Polygon"}, ficha_liberada=True)
    assert revisao_lote("pedido", {"meta": 100}, retrato, visiveis) == primeira
    assert len(primeira) == 64
    assert revisao_lote("pedido", {}, {}, []) is None


def test_mutacoes_invalidam_revisao_mesmo_sem_mudar_modelo(retrato):
    primeira = revisao_lote("pedido", {"meta": 100}, retrato, retrato["opcoes"])
    for campo, valor in [("id", 11), ("premissas_versao", "v2"), ("otimizador_versao", "solver-v2")]:
        novo = {**retrato, campo: valor}
        assert revisao_lote("pedido", {"meta": 100}, novo, novo["opcoes"]) != primeira
    assert revisao_lote("pedido", {"meta": 200}, retrato, retrato["opcoes"]) != primeira
    for acao in ("tirar", "trocar"):
        novo = copy.deepcopy(retrato)
        novo["opcoes"][0]["itens"].pop(0)
        if acao == "trocar":
            novo["opcoes"][0]["itens"][0]["papel"] = "lote"
        assert revisao_lote("pedido", {"meta": 100}, novo, novo["opcoes"]) != primeira
    # Reserva por outra conta: composição disponível muda antes de nova sugestão.
    assert revisao_lote("pedido", {"meta": 100}, retrato, []) != primeira


def test_apresentacao_so_aceita_digest_sem_identificadores_livres():
    assert pedido_publico({"revisao_lote": "a" * 64})["revisao_lote"] == "a" * 64
    assert pedido_publico({"revisao_lote": "conteudo indevido"})["revisao_lote"] is None
