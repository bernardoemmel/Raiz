"""Sinal do catálogo PRODES: mudanças reais, remoções e estado aceito preservado."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from types import SimpleNamespace

import pytest
import requests

from raiz.coleta import prodes


def item(dataset="amz-prodes", arquivo="anual_v20261016.zip", **campos):
    return {
        "id": "1",
        "name": "Desmatamento anual",
        "lang": "pt-br",
        "link": f"/download/dataset/{dataset}/vector/{arquivo}",
        "created": "2026-10-16 14:33:02",
        "enabled": True,
        **campos,
    }


class Sessao:
    def __init__(self, catalogo, erro=None):
        self.catalogo = catalogo
        self.erro = erro
        self.chamadas = []

    def get(self, url, **kwargs):
        self.chamadas.append((url, kwargs))
        return self

    def raise_for_status(self):
        if self.erro:
            raise self.erro

    def json(self):
        return self.catalogo


class Conexao:
    def __init__(self, estados=()):
        self.estados = estados
        self.consultas = []

    def execute(self, sql, params):
        self.consultas.append((str(sql), params))
        return self

    def all(self):
        return self.estados


@pytest.fixture
def gravacoes(monkeypatch):
    atualizacoes, eventos = [], []
    monkeypatch.setattr(prodes.replicacao, "atualizar", lambda *a, **kw: atualizacoes.append((a, kw)))
    monkeypatch.setattr(prodes.replicacao, "evento", lambda *a, **kw: eventos.append((a, kw)))
    return atualizacoes, eventos


def test_assinatura_independe_da_ordem_idioma_e_colunas_novas():
    a, b = item(), item("cerrado-prodes")
    catalogo = [a, b]
    antes = deepcopy(catalogo)
    esperada = prodes.assinaturas(catalogo)
    traduzido = {**a, "id": "2", "lang": "en", "name": "Annual deforestation", "coluna_nova": 1}
    assert prodes.assinaturas([b, traduzido, a]) == esperada
    assert catalogo == antes
    assert list(esperada) == ["amz-prodes", "cerrado-prodes"]
    assert len(esperada["amz-prodes"]) == 64


@pytest.mark.parametrize(
    "alteracao",
    [
        [item(), item(arquivo="outro.zip")],
        [item(created="2026-11-01 00:00:00")],
        [item(enabled=False)],
        [item(arquivo="anual_v20261101.zip")],
        [],
    ],
    ids=["arquivo_novo", "revisao_mesmo_ano", "desabilitado", "link_novo", "dataset_removido"],
)
def test_detecta_criacao_revisao_desativacao_e_remocao(alteracao):
    anterior = prodes.assinaturas([item()])
    assert prodes.assinaturas(alteracao, anterior)["amz-prodes"] != anterior["amz-prodes"]


def test_remocao_de_um_arquivo_altera_hash_e_preserva_outro_dataset():
    antes = prodes.assinaturas([item(), item(arquivo="outro.zip"), item("cerrado-prodes")])
    depois = prodes.assinaturas([item(), item("cerrado-prodes")], antes)
    assert depois["amz-prodes"] != antes["amz-prodes"]
    assert depois["cerrado-prodes"] == antes["cerrado-prodes"]


def test_hash_vazio_para_dataset_removido_e_produto_alheio_ignorado():
    obtido = prodes.assinaturas([item("deter-amz")], ["amz-prodes"])
    assert obtido == {"amz-prodes": hashlib.sha256(b"[]").hexdigest()}
    assert prodes.assinaturas([]) == {}


def test_dataset_extraido_do_link_absoluto_e_nomes_sem_colisao():
    a = item("legal-amz-prodes")
    a["link"] = "https://terrabrasilis.dpi.inpe.br" + a["link"]
    assert set(prodes.assinaturas([a, item(), item("brasil-prodes")])) == {
        "legal-amz-prodes",
        "amz-prodes",
        "brasil-prodes",
    }


@pytest.mark.parametrize(
    "catalogo",
    [
        {"erro": "indisponível"},
        None,
        [None],
        [{}],
        [item(link=None)],
        [item(created="")],
        [item(created="data inválida")],
        [item(enabled="false")],
        [item(enabled=None)],
        [item(link="/download/amz-prodes/arquivo.zip")],
    ],
)
def test_catalogo_malformado_nao_vira_remocao(catalogo, gravacoes):
    con = Conexao()
    with pytest.raises(ValueError):
        prodes.verificar(Sessao(catalogo), con)
    assert not con.consultas
    assert gravacoes == ([], [])


def test_falha_http_propagada_sem_gravacao(gravacoes):
    con = Conexao()
    with pytest.raises(requests.HTTPError):
        prodes.verificar(Sessao([], requests.HTTPError("503")), con)
    assert not con.consultas
    assert gravacoes == ([], [])


def test_leitor_usa_um_get_e_timeout_sem_baixar_arquivos():
    s = Sessao([item()])
    assert prodes.ler_catalogo(s, timeout=7) == [item()]
    assert s.chamadas == [(prodes.URL_CATALOGO, {"timeout": 7})]


def test_verificacao_marca_sujo_sem_aceitar_assinatura(gravacoes):
    anterior = prodes.assinaturas([item()])["amz-prodes"]
    estado = SimpleNamespace(recorte="amz-prodes", assinatura=anterior, sujo=False)
    con = Conexao([estado])
    [r] = prodes.verificar(Sessao([item(enabled=False)]), con)
    assert r.mudou and r.sujo and not r.removido
    assert r.anterior == anterior and r.assinatura != anterior
    assert r.arquivos == 1
    assert estado.assinatura == anterior
    atualizacoes, eventos = gravacoes
    assert set(atualizacoes[0][1]) == {"sujo", "verificado_em"}
    assert atualizacoes[0][0][1:] == ("prodes", "amz-prodes")
    assert atualizacoes[0][1]["sujo"] is True
    assert eventos[0][0][1:5] == ("prodes", "amz-prodes", "mudaram", 1)


@pytest.mark.parametrize("sujo", [False, True])
def test_assinatura_igual_preserva_sujo_anterior(sujo, gravacoes):
    ass = prodes.assinaturas([item()])["amz-prodes"]
    e = SimpleNamespace(recorte="amz-prodes", assinatura=ass, sujo=sujo)
    [r] = prodes.verificar(Sessao([item()]), Conexao([e]))
    assert not r.mudou and r.sujo is sujo
    assert gravacoes[0][0][1]["sujo"] is sujo
    assert not gravacoes[1]


def test_novo_dataset_e_remocao_total_detectados_do_estado(gravacoes):
    e = SimpleNamespace(recorte="cerrado-prodes", assinatura="assinatura_aceita", sujo=False)
    antigo = SimpleNamespace(recorte="GO", assinatura="outro_recorte", sujo=False)
    resultados = prodes.verificar(Sessao([item()]), Conexao([e, antigo]))
    assert [r.dataset for r in resultados] == ["amz-prodes", "cerrado-prodes"]
    assert all(r.sujo and r.mudou for r in resultados)
    novo, removido = resultados
    assert novo.anterior is None and novo.arquivos == 1 and not novo.removido
    assert removido.arquivos == 0 and removido.removido
    assert removido.assinatura == hashlib.sha256(b"[]").hexdigest()
    assert all("assinatura" not in kw for _, kw in gravacoes[0])
