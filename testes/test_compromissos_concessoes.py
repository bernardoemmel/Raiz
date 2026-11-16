"""Fontes reais têm contratos e polígonos publicados separadamente."""

import json

import pytest
import requests
from shapely.geometry import box, mapping

from raiz.coleta.compromissos_concessoes import (
    SFB_CONTRATOS,
    catalogo_art,
    coletar_sfb,
    contratos_sfb,
)


def _html(linhas=None):
    linhas = linhas or [
        ["Jamari (RO)", "I", "DADO_PROIBIDO", "17.176,36", "16/10/2008", "02/2008", "2010"],
        ["", "IV", "DADO_PROIBIDO", "32.294,99", "19/08/2019", "01/2019", "2020"],
        ["Humaitá (AM)", "II", "DADO_PROIBIDO", "63.343,41", "09/09/2026", "01/2026", "não iniciadas"],
    ]
    cabecalhos = [
        "Flona",
        "UMF",
        "Concessionários",
        "Área (em ha)",
        "Data de assinatura do contrato",
        "Número do contrato",
        "Início das operações",
    ]
    return (
        "<table>"
        + "".join("<tr>" + "".join(f"<td>{v}</td>" for v in linha) + "</tr>" for linha in [cabecalhos, *linhas])
        + "</table>"
    ).encode()


class Resposta:
    def __init__(self, dado):
        self.dado = dado if isinstance(dado, bytes) else json.dumps(dado).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    def iter_content(self, tamanho):
        yield self.dado


class Sessao:
    def __init__(self, respostas):
        self.respostas = iter(respostas)
        self.chamadas = []

    def get(self, url, **kwargs):
        self.chamadas.append((url, kwargs))
        dado = next(self.respostas)
        if isinstance(dado, Exception):
            raise dado
        return Resposta(dado)


def _indice():
    return {
        "features": [
            {"attributes": {"nome": "Jamari UMF 1", "umf": "UMF I", "fid": 11}},
            {"attributes": {"nome": "Jamari UMF 4", "umf": "UMF IV", "fid": 12}},
        ]
    }


def _geometria():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"nome": "Jamari UMF 1", "umf": "UMF I", "cpf": "DADO_PROIBIDO"},
                "geometry": mapping(box(-63, -10, -62, -9)),
            }
        ],
    }


def test_tabela_so_retem_terra_com_fonte_e_datas_distintas():
    dados = contratos_sfb(_html(), observado_em="2026-11-12")
    assert len(dados) == 3
    assert "DADO_PROIBIDO" not in json.dumps(dados)
    assert dados["jamari:iv"]["uf"] == "RO"
    assert dados["jamari:i"]["inicio"] == "2008-10-16"
    assert dados["jamari:i"]["data_referencia"] is None
    assert dados["humaita:ii"]["situacao"] == "ativo"
    assert all(d["evidencia_status_url"] == SFB_CONTRATOS for d in dados.values())


def test_chave_lote_sul_nao_confunde_umf_ii():
    linhas = [["Saracá-Taquera Lote Sul (PA)", "IA", "", "1", "25/03/2014", "", ""]]
    dados = contratos_sfb(_html(linhas), observado_em="2026-11-12")
    assert set(dados) == {"saracataquera:ia"}


def test_bbox_baixa_so_geometria_local_e_nao_cria_indicio_fora_recorte():
    sessao = Sessao([_html(), _indice(), _geometria()])
    dado = coletar_sfb((-64, -11, -61, -8), sessao=sessao, observado_em="2026-11-12")
    assert len(dado["registros"]) == 2  # UMF IV existe, mas está fora deste recorte.
    confirmada = next(d for d in dado["registros"] if d["geometry"] is not None)
    assert confirmada["certeza"] == "poligono_oficial"
    assert confirmada["geometry"].area == 1
    assert set(confirmada) == set(next(iter(contratos_sfb(_html(), observado_em="2026-11-12").values())))
    assert dado["cobertura"]["estado"] == "parcial"  # Humaitá II não tem limite no serviço.
    assert dado["cobertura"]["bbox"] == [-64, -11, -61, -8]
    assert sessao.chamadas[1][1]["params"]["returnGeometry"] == "false"
    assert sessao.chamadas[2][1]["params"]["outFields"] == "fid,umf,nome"
    assert sessao.chamadas[2][1]["params"]["geometry"] == "-64,-11,-61,-8"


@pytest.mark.parametrize(
    "falha",
    [
        {"error": {"code": 500}},
        {"features": [], "exceededTransferLimit": True},
        requests.ConnectionError("indisponível"),
    ],
)
def test_falha_geografica_preserva_catalogo_e_cobertura_parcial(falha):
    dado = coletar_sfb((-64, -11, -61, -8), sessao=Sessao([_html(), falha]))
    assert dado["cobertura"]["estado"] == "parcial"
    assert len(dado["registros"]) == 3
    assert all(d["geometry"] is None for d in dado["registros"])


def test_falha_tabela_nao_declara_cobertura_vazia_concluida():
    dado = coletar_sfb((-64, -11, -61, -8), sessao=Sessao([b"<html>indisponivel</html>"]))
    assert dado["registros"] == []
    assert dado["cobertura"]["estado"] == "indisponivel"


def test_poligono_sem_contrato_nao_confirma_compromisso():
    geom = _geometria()
    geom["features"][0]["properties"]["nome"] = "Flona sem contrato UMF 1"
    dado = coletar_sfb((-64, -11, -61, -8), sessao=Sessao([_html(), _indice(), geom]))
    assert all(r["geometry"] is None for r in dado["registros"])
    assert dado["cobertura"]["estado"] == "parcial"


@pytest.mark.parametrize("erro", ["crs", "duplicada"])
def test_geometria_inconsistente_nao_vira_ausencia_de_sobreposicao(erro):
    geom = _geometria()
    if erro == "crs":
        geom["features"][0]["geometry"] = mapping(box(-6000000, -1000000, -5000000, -900000))
    else:
        geom["features"] *= 2
    dado = coletar_sfb((-64, -11, -61, -8), sessao=Sessao([_html(), _indice(), geom]))
    assert dado["cobertura"]["estado"] == "parcial"
    assert len(dado["registros"]) == 3
    assert all(r["geometry"] is None for r in dado["registros"])


def test_art_e_contexto_estadual_sem_transformar_area_uf_em_compromisso():
    dado = catalogo_art()
    assert {r["uf"] for r in dado["registros"]} == {"AC", "AP", "MA", "MT", "PA", "TO"}
    assert all(r["geometry"] is None and r["certeza"] == "contexto_jurisdicional" for r in dado["registros"])
    assert all(r["inicio"] is None and r["fim"] is None for r in dado["registros"])
    assert all(r["observado_em"] == "2026-11-12" for r in dado["registros"])
    assert dado["cobertura"]["recorte"] == "BR"


@pytest.mark.parametrize("bbox", [(-181, 0, 0, 1), (1, 0, 0, 1), (0, 0, float("nan"), 1)])
def test_bbox_invalido_nao_acessa_fonte(bbox):
    with pytest.raises(ValueError, match="Recorte"):
        coletar_sfb(bbox, sessao=Sessao([]))
