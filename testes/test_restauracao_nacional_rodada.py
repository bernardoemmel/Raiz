"""Retomada e publicação privadas; pedido futuro não cancela a fila estadual."""

import json
from types import SimpleNamespace

import pytest

from raiz import restauracao_catalogo as C
from raiz import restauracao_nacional as N
from raiz import restauracao_nacional_rodada as A
from raiz.executor.transferencia_privada import empacotar, extrair
from raiz.pedidos.campos import CamposPedido
from scripts import reservar_lote as V
from testes.test_restauracao_catalogo import criar_fonte, indexar
from testes.test_restauracao_nacional_fontes import Armazem


def transporte(monkeypatch):
    def enviar(nome, arquivo, *, arm, imutavel=False):
        arm._exigir_privado()
        if imutavel and nome in arm.conteudos:
            assert arm.conteudos[nome] == arquivo.read_bytes()
        arm.conteudos[nome] = arquivo.read_bytes()

    monkeypatch.setattr(A.F, "enviar_arquivo", enviar)
    monkeypatch.setattr(A, "enviar_arquivo", enviar)


def test_todas_as_27_ufs_e_territorios_da_base():
    ms = A.municipios()
    assert len(ms) == len(N.UFS) == 27 and all(ms.values())
    assert 1100205 in ms["RO"] and 1400100 in ms["RR"]
    assert N.normalizar_recorte(ufs=["RO", "RR"]).ufs == ("RO", "RR")


def test_indice_e_consulta_sobrevivem_a_outro_diretorio(tmp_path, monkeypatch):
    transporte(monkeypatch)
    arm = Armazem({})
    indice = tmp_path / "indice"
    criar_fonte(tmp_path / "fonte", n=2)
    parte = indexar(tmp_path / "fonte", indice)
    cat = C.consolidar_catalogo([parte], indice, municipios_esperados={"PA": [1500602]})
    pacote = tmp_path / "indice.tar.gz"
    empacotar(indice, pacote, excluir=(".travas",))
    ref = A.F.publicar(arm, pacote, "indice", ".tar.gz")
    atual = {"acesso": "privado", "ufs": {"PA": {"indice": ref, "catalogo": cat.name, "sem_imoveis": []}}}
    novo = A.reunir_catalogo(arm, atual, tmp_path / "novo")
    d, ps = C.abrir_catalogo(novo)
    assert len(ps) == 1 and d["imoveis"] == 2
    assert len(d["cobertura"]) == 27 and d["cobertura"]["RO"]["faltantes"]
    r = N.montar_tres_opcoes(
        novo,
        CamposPedido(meta={"valor": 10}, cronograma="livre"),
        N.normalizar_recorte(brasil=True),
        modelo="modelo-teste",
        cenario="central_r11",
        destino=tmp_path / "resultados",
    )
    pub = A.publicar_consulta(arm, r, tmp_path)
    A.F.baixar(arm, pub["pacote"], tmp_path / "recuperado.tar.gz")
    extrair(tmp_path / "recuperado.tar.gz", tmp_path / "recuperado")
    rel = json.loads((tmp_path / "recuperado/lote.json").read_text())
    assert rel["modelo"] == "modelo-teste" and rel["acesso"] == "privado"
    for op in rel["opcoes"].values():
        arquivo = tmp_path / "recuperado" / op["tabela"]["caminho"]
        assert C.sha256(arquivo) == op["tabela"]["sha256"]
    assert not (tmp_path / "recuperado/resultado.json").exists()


def test_manutencao_incremental_nao_apaga_nem_repete_fonte(tmp_path, monkeypatch):
    transporte(monkeypatch)
    arm, chamadas = Armazem({}), []
    atual = {
        "acesso": "privado",
        "ufs": {
            "RO": {"entrada_id": "antiga", "contagens": {"modelo_incompativel": 3}},
            "PA": {"entrada_id": "congelada", "contagens": {"compativel": 5}},
        },
    }

    def executar(args, **kwargs):
        chamadas.append(args)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(A.subprocess, "run", executar)
    assert A.pedir_manutencao(arm, atual, tmp_path) == ["RO"]
    assert A.pedir_manutencao(arm, atual, tmp_path) == []
    assert len(chamadas) == 1 and "ufs=RO" in chamadas[0] and "refazer=" in chamadas[0]
    assert not any("cancel" in x for x in chamadas[0])
    assert json.loads(arm.conteudos[A.PONTEIRO])["ufs"]["PA"]["entrada_id"] == "congelada"


def test_espera_vaga_sem_confundir_falha_de_api(monkeypatch):
    tentativas = iter([V.SemVagaGlobal("cheio"), 1])
    esperas = []

    def reservar(n):
        r = next(tentativas)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(V, "reservar", reservar)
    monkeypatch.setattr(V.time, "sleep", esperas.append)
    assert V.aguardar(1, 2) == 1 and esperas == [60]
    monkeypatch.setattr(V, "reservar", lambda n: (_ for _ in ()).throw(RuntimeError("API")))
    with pytest.raises(RuntimeError, match="API"):
        V.aguardar(1, 2)
    assert esperas == [60]


def test_preco_diferente_nao_reusa_tir_da_previsao():
    with pytest.raises(ValueError, match="reavaliar a oferta"):
        N.preparar_contrato(CamposPedido(dinheiro={"preco_venda_usd": 40}), A.R.versao(), "central_r11")
