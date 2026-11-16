"""Pacote "lote pronto": ZIP por opção com CARs, reservas, tabela, mapa, Raio-X em PDF e sobreposição."""

import hashlib
import json
import zipfile

import pandas as pd
import pytest

from raiz import lote_pronto as LP
from raiz import restauracao_catalogo as C
from raiz import restauracao_nacional as N
from raiz import restauracao_selecao as S
from raiz.pedidos.campos import CamposPedido
from testes.test_restauracao_catalogo import criar_fonte, indexar


@pytest.fixture
def resultado(tmp_path):
    destino = tmp_path / "indice"
    criar_fonte(tmp_path / "pa", n=4)
    ps = [indexar(tmp_path / "pa", destino)]
    cat = C.consolidar_catalogo(ps, destino, municipios_esperados={"PA": [1500602]})
    return N.montar_tres_opcoes(
        cat,
        CamposPedido(meta={"valor": 20}, cronograma="livre"),
        N.normalizar_recorte(ufs=["PA"]),
        modelo="modelo-teste",
        cenario="central_r11",
        destino=tmp_path / "saida",
        limites=S.LimitesSelecao(2, 10, 1),
    )


def test_pacote_tem_tudo_e_nenhum_dado_pessoal(resultado, tmp_path):
    info = LP.montar_pacote(resultado, "barata", tmp_path / "lote.zip")
    with zipfile.ZipFile(tmp_path / "lote.zip") as z:
        nomes = set(z.namelist())
        assert {"LEIAME.md", "resumo.json", "cars.csv", "reservas.csv", "tabela_lote.csv", "sobreposicao.csv",
                "mapa.svg", "mapa.geojson", "manifesto.json"} <= nomes  # fmt: skip
        cars = pd.read_csv(z.open("cars.csv"))
        assert len(cars) == info["fazendas"] == resultado["opcoes"]["barata"]["fazendas"] > 0
        pdfs = {n for n in nomes if n.startswith("raio-x/")}
        assert pdfs == {f"raio-x/{c}.pdf" for c in cars.cod_imovel}  # um Raio-X por CAR, pequenas incluídas
        assert all(z.read(n)[:5] == b"%PDF-" for n in pdfs)
        sob = pd.read_csv(z.open("sobreposicao.csv"))
        assert set(sob.sobreposicao) == {"nao_verificada"}  # camada ainda ausente: nunca "sem sobreposição"
        manifesto = json.loads(z.read("manifesto.json"))
        for nome, sha in manifesto["arquivos"].items():
            assert hashlib.sha256(z.read(nome)).hexdigest() == sha
        resumo = json.loads(z.read("resumo.json"))
        assert resumo["sobreposicao"]["situacao"] == "nao_verificada"
        texto = z.read("LEIAME.md").decode() + z.read("tabela_lote.csv").decode()
        assert "Sobreposição" in texto and "não libera venda" in texto.lower()
        assert not any(p in z.read("tabela_lote.csv").decode().lower() for p in ("cpf", "cnpj", "telefone", "email"))
        assert b"<svg" in z.read("mapa.svg") and json.loads(z.read("mapa.geojson"))["type"] == "FeatureCollection"


def test_mesmo_lote_gera_o_mesmo_zip(resultado, tmp_path):
    a = LP.montar_pacote(resultado, "segura", tmp_path / "a.zip")
    b = LP.montar_pacote(resultado, "segura", tmp_path / "b.zip")
    assert a["sha256"] == b["sha256"]


def test_situacao_de_sobreposicao_e_status_por_fazenda():
    assert LP.situacao_sobreposicao({}) == "nao_verificada"
    assert LP.situacao_sobreposicao({"ja_comprometida": False, "risco_sobreposicao": False}).startswith("sem_indicio")
    assert LP.situacao_sobreposicao({"ja_comprometida": False, "risco_sobreposicao": True}) == "risco_sobreposicao"
    assert LP.situacao_sobreposicao({"ja_comprometida": True}) == "ja_comprometida"


def test_marca_do_lote_e_valida_e_estavel():
    from raiz.prospeccao_protecao import validar_marca

    m = LP.marca_do_lote("abc", "barata")
    validar_marca(m)
    assert m == LP.marca_do_lote("abc", "barata") and m != LP.marca_do_lote("abc", "segura")
