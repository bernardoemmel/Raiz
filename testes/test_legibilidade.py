"""Medidor de legibilidade (raiz/legibilidade.py): contagem do ALT, as três versões do Flesch e a preparação do
texto (números, datas e reais por extenso). As contagens esperadas foram feitas à mão, seguindo as regras do ALT."""

import json

import pytest
from typer.testing import CliRunner

from raiz import legibilidade as L
from raiz.agentes import textos


@pytest.mark.parametrize(
    ("texto", "letras", "palavras", "silabas", "frases"),
    [
        ("Olá mundo.", 8, 2, 4, 1),
        # o primeiro ditongo do texto ("ão") sempre desconta
        ("A casa é bonita. O pão é bom.", 20, 8, 11, 2),
        # depois do primeiro, o ditongo só desconta depois de consoante: "ou" de "ouro" fica com duas sílabas
        ("Pão, mãe, ouro.", 10, 3, 5, 1),
        ("Ai ui", 4, 2, 3, 1),
        # ";" fecha frase e a quebra de linha depois dele conta de novo, como no ALT
        ("a;\nb", 2, 1, 1, 3),
        # reticências contam uma vez; hífen no fim da linha não fecha palavra
        ("Será... talvez.", 10, 2, 4, 2),
        ("- item um\n- item dois", 14, 4, 6, 1),
        # tritongo desconta mais uma
        ("Uruguai", 7, 1, 3, 1),
    ],
)
def test_contagem_do_alt(texto, letras, palavras, silabas, frases):
    assert L.contar_letras(texto) == letras
    assert L.contar_palavras(texto) == palavras
    assert L.contar_silabas(texto) == silabas
    assert L.contar_frases(texto) == frases


def test_frases_sem_ponto_e_virgula_nem_dois_pontos():
    assert L.contar_frases("Prazo: 30 anos; pagamento anual.") == 3
    assert L.contar_frases("Prazo: 30 anos; pagamento anual.", ponto_e_virgula=False, dois_pontos=False) == 1


@pytest.mark.parametrize(
    ("n", "falado"),
    [
        (0, "zero"),
        (16, "dezesseis"),
        (21, "vinte e um"),
        (100, "cem"),
        (101, "cento e um"),
        (1000, "mil"),
        (1005, "mil e cinco"),
        (1200, "mil e duzentos"),
        (1250, "mil duzentos e cinquenta"),
        (2026, "dois mil e vinte e seis"),
        (21000, "vinte e um mil"),
        (1_000_000, "um milhão"),
        (1_500_000, "um milhão e quinhentos mil"),
        (1_200_300, "um milhão duzentos mil e trezentos"),
        (7_300_000_000, "sete bilhões e trezentos milhões"),
    ],
)
def test_extenso(n, falado):
    assert L.extenso(n) == falado


@pytest.mark.parametrize(
    ("texto", "preparado"),
    [
        ("R$ 1.200 por hectare.", "mil e duzentos reais por hectare."),
        ("R$ 1", "um real"),
        ("R$ 2,5 milhões", "dois vírgula cinco milhões de reais"),
        ("R$ 1.000.000", "um milhão de reais"),
        ("US$ 15 por crédito", "quinze dólares por crédito"),
        ("12,5% da área", "doze vírgula cinco por cento da área"),
        ("0,05 ha", "zero vírgula zero cinco hectares"),
        ("30 km", "trinta quilômetros"),
        ("em 1/3/2027", "em primeiro de março de dois mil e vinte e sete"),
        ("Prazo: 25 anos.", "Prazo: vinte e cinco anos."),
        ("o art. 5º e o Sr. Silva", "o artigo 5º e o senhor Silva"),
        # código do CAR e número com barra ficam como estão
        ("imóvel PA-1500107-0030", "imóvel PA-1500107-0030"),
        ("Lei 15.263/2025", "Lei 15.263/2025"),
    ],
)
def test_preparar(texto, preparado):
    assert L.preparar(texto) == preparado


def test_preparar_tira_o_ponto_do_milhar_da_conta_de_frases():
    t = "A área tem 1.234 hectares e vale R$ 2.500 por ano."
    assert L.contar_frases(t) == 3  # o ALT conta os pontos do milhar
    assert L.medir(t)["frases"] == 1
    assert L.medir(t, preparar_texto=False)["frases"] == 3


def test_tres_versoes_do_flesch_com_a_mesma_contagem():
    m = L.medir("A casa é bonita. O pão é bom.", preparar_texto=False)
    asl, asw = 8 / 2, 11 / 8
    assert m["flesch_alt"] == round(226 - 1.04 * asl - 72 * asw, 1)
    assert m["flesch_martins"] == round(248.835 - 1.015 * asl - 84.6 * asw, 1)
    assert m["flesch_languagetool"] == round(206.84 - 1.02 * asl - 60 * asw, 1)
    assert m["flesch_kincaid"] == round(0.36 * asl + 10.4 * asw - 18, 1)
    assert m["gulpease"] == round(89 + (300 * 2 - 10 * 20) / 8, 1)
    assert m["versao"] == L.VERSAO and m["preparado"] is False


def test_faixas():
    assert [L.faixa_martins(x) for x in (80, 60, 30, 10)] == ["muito fácil", "fácil", "difícil", "muito difícil"]
    assert [L.nivel_languagetool(x) for x in (10, 30, 55, 65, 75, 85, 95)] == [0, 1, 2, 3, 4, 5, 6]
    assert [L.faixa_alt(x) for x in (12.9, 13, 16.9, 17)] == ["alta", "média", "média", "baixa"]


def test_palavras_complexas_pela_lista_ou_pelas_silabas(tmp_path, monkeypatch):
    t = "Hoje a Raíz analisou a documentação do INCRA."
    # sem lista: complexa é a de quatro sílabas ou mais; nome próprio e sigla não contam
    assert L.contar_complexas(t) == (2, "silabas>=4")  # analisou e documentação
    lista = tmp_path / "comuns.txt"
    lista.write_text("hoje\na\ndo\ndocumentação\n", encoding="utf-8")
    monkeypatch.setenv("RAIZ_PALAVRAS_COMUNS", str(lista))
    m = L.medir(t)
    assert m["complexas_criterio"] == "lista" and m["complexas"] == 1  # analisou


def test_texto_vazio():
    assert L.medir("  \n")["palavras"] == 0
    assert L.resumo(L.medir("")) == "texto vazio"


def test_modelos_ao_dono_sao_faceis():
    """Os modelos de hoje ficam em "fácil" ou melhor pelo Martins. A nota mínima calibrada com cartas reais é o
    passo 3 do E9; esta é só a guarda contra um modelo novo muito difícil."""
    for nome, texto in textos.exemplos().items():
        m = L.medir(texto)
        assert m["flesch_martins"] >= 50, (nome, m)
        assert m["palavras_por_frase"] <= 15, (nome, m)


def test_comando():
    from raiz.cli import app

    r = CliRunner().invoke(app, ["legibilidade", "medir", "--json"], input="R$ 1.200 por hectare, em 12/11/2026.")
    assert r.exit_code == 0, r.output
    m = json.loads(r.output)
    assert m["palavras"] == 17 and m["silabas"] == 26 and m["frases"] == 1
    r = CliRunner().invoke(app, ["legibilidade", "modelos"])
    assert r.exit_code == 0 and "convite" in r.output
