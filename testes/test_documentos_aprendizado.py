"""Aprendizado: gabarito da certidão real, placar por modelo e versão, fila de revisão e exportação para a E8."""

import csv
import datetime as dt

import pytest

from raiz.documentos import aprendizado
from raiz.documentos.armazem import Armazem
from raiz.documentos.certidao.leitor import ler_certidao
from raiz.documentos.claude import LeitorClaude
from raiz.documentos.cli import principal
from raiz.documentos.config import REPO
from raiz.documentos.simulacao import ClienteSimulado, leitura_exemplo, pdf_exemplo

HOJE = dt.date(2026, 11, 12)
IMOVEL = "PA-1504950-0E3B6098A40D44F7B85CFB563EB6A45A"


@pytest.fixture(autouse=True)
def pastas(tmp_path, monkeypatch):
    monkeypatch.setenv("RAIZ_DOCUMENTOS_DIR", str(tmp_path / "docs"))
    monkeypatch.setenv("RAIZ_DOCUMENTOS_ENTRADA", str(REPO / "dados" / "amostra"))


def _ler(dados, modelo="claude-opus-5-5", texto="x"):
    cli = ClienteSimulado([dados], modelo=modelo)
    return ler_certidao(
        pdf_exemplo(texto), cod_imovel=IMOVEL, leitor=LeitorClaude(modelo=modelo, cliente=cli), hoje=HOJE
    )


def test_marcar_confirma_desmente_e_placar():
    a = _ler(leitura_exemplo(), texto="a").leitura.id
    b = _ler(leitura_exemplo(area_valor=100), texto="b").leitura.id  # leu área errada: divergente
    c = _ler(leitura_exemplo(), modelo="claude-sonnet-5-5", texto="c").leitura.id
    g = aprendizado.marcar(a, fonte="cartorio", confirma=True, campos={"area_ha": "290", "onus_ativos": "1"})
    assert g["situacao"] == {"lida": "conferida", "real": "conferida", "confirma": True}
    assert g["area_ha"]["confirma"] is True and g["onus_ativos"]["confirma"] is False
    g = aprendizado.marcar(b, fonte="onr", situacao_real="conferida", campos={"area_ha": "290,0"})
    assert g["situacao"]["confirma"] is False and g["area_ha"]["confirma"] is False
    aprendizado.marcar(c, fonte="cartorio", confirma=True)
    placar = {p["modelo"]: p for p in aprendizado.placar()}
    opus = placar["claude-opus-5-5"]
    assert opus["leituras"] == 2 and opus["com_gabarito"] == 2
    assert opus["acerto"]["situacao"] == {"certos": 1, "total": 2, "taxa": 0.5}
    assert opus["acerto"]["campo:area_ha"]["taxa"] == 0.5
    assert placar["claude-sonnet-5-5"]["acerto"]["situacao"]["taxa"] == 1.0
    assert opus["custo_medio_usd"] > 0


def test_marcar_recusa_entrada_sem_sentido():
    a = _ler(leitura_exemplo()).leitura.id
    with pytest.raises(ValueError):
        aprendizado.marcar(a, fonte="x")
    with pytest.raises(ValueError):
        aprendizado.marcar(a, fonte="x", situacao_real="talvez")
    with pytest.raises(ValueError):
        aprendizado.marcar(a, fonte="x", campos={"nome_do_dono": "x"})
    with pytest.raises(ValueError):
        aprendizado.marcar(999, fonte="x", confirma=True)


def test_correcao_vale_a_ultima():
    a = _ler(leitura_exemplo()).leitura.id
    aprendizado.marcar(a, fonte="conferencia_humana", situacao_real="divergente")
    aprendizado.marcar(a, fonte="cartorio", situacao_real="conferida")
    [g] = Armazem().gabaritos(a)
    assert g["valor_real"] == "conferida" and g["fonte"] == "cartorio"


def test_fila_poe_divergente_antes_e_tira_quem_ja_tem_gabarito():
    ok = _ler(leitura_exemplo(), texto="ok").leitura.id
    ruim = _ler(leitura_exemplo(area_valor=50), texto="ruim").leitura.id
    fila = aprendizado.fila_revisao()
    assert [f["leitura_id"] for f in fila] == [ruim, ok]
    aprendizado.marcar(ruim, fonte="cartorio", situacao_real="divergente")
    assert [f["leitura_id"] for f in aprendizado.fila_revisao()] == [ok]


def test_exportar_no_formato_da_e8(tmp_path):
    a = _ler(leitura_exemplo(), texto="a").leitura.id
    _ler(leitura_exemplo(), texto="sem gabarito")
    aprendizado.marcar(a, fonte="cartorio", confirma=True)
    p, g = aprendizado.exportar(tmp_path / "e8")
    prevs = list(csv.DictReader(p.open(encoding="utf-8")))
    gabs = list(csv.DictReader(g.open(encoding="utf-8")))
    assert set(aprendizado.COLS_PREVISAO) == set(prevs[0])
    assert {r["alvo"] for r in prevs} == {"titulo_matricula_situacao", "motor_matricula_valida"}
    assert all(r["modelo_versao"] for r in prevs) and all(r["data_corte"] == prevs[0]["data_corte"] for r in prevs)
    # o motor só ganha gabarito de leitura confirmada por gente
    motor = [r for r in gabs if r["alvo"] == "motor_matricula_valida"]
    assert len(motor) == 1 and motor[0]["valor_texto"] == "sim" and motor[0]["referencia"] == f"leitura:{a}"


def test_cli_le_certidao_manual_e_mostra_placar(tmp_path, capsys):
    import json

    pdf, js = tmp_path / "c.pdf", tmp_path / "c.json"
    pdf.write_bytes(pdf_exemplo("cli"))
    js.write_text(json.dumps(leitura_exemplo()), encoding="utf-8")
    assert principal(["certidao", "ler", str(pdf), "--imovel", IMOVEL, "--manual", str(js)]) == 0
    saida = capsys.readouterr().out
    assert "CONFERIDA" in saida and "humano" in saida and str(pdf) not in saida
    assert principal(["certidao", "saida", "1504950"]) == 0
    assert principal(["aprendizado", "placar"]) == 0
    assert '"modelo": "humano"' in capsys.readouterr().out
