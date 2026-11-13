"""Regressões de associação e limites; dados sintéticos só para testar o contrato."""

import datetime as dt
import sys

import pytest

from raiz.calendario import coleta, leiloes_abertos
from raiz.calendario.processo_limitado import executar
from testes.test_calendario_fontes_http_pdf import AGORA, CAR, FONTE, OUTRO
from testes.test_calendario_leiloes_abertos import DETALHE, PDF, detalhe


def test_car_de_confrontante_nao_prova_matricula():
    f = {"modo": "caixa_csv"}
    for texto in [
        f"MATRÍCULA 5178\nConfrontante: outro imóvel, CAR {CAR}",
        f"MATRÍCULA 5178\nLimites e confrontações\nAo norte, CAR {CAR}",
    ]:
        assert leiloes_abertos.complemento_matricula(detalhe(), DETALHE, texto, PDF, f) is None


def test_editais_homonimos_do_mesmo_pdf_preservam_imoveis_e_datas():
    texto = (
        f"EDITAL DE LEILÃO Nº 01/2026\nImóvel rural CAR {CAR}. Leilão em 30/11/2026.\n"
        f"EDITAL DE LEILÃO Nº 01/2026\nImóvel rural CAR {OUTRO}. Leilão em 01/12/2026."
    )
    eventos, _ = coleta.extrair(texto, FONTE, FONTE["urls"][0] + "/edicao.pdf", AGORA, "pdf")
    assert len({e.id for e in eventos}) == 2
    assert {(e.data, tuple(e.codigos_car)) for e in eventos} == {
        (dt.date(2026, 11, 30), (CAR,)),
        (dt.date(2026, 12, 1), (OUTRO,)),
    }


def test_ocr_sintaticamente_valido_nao_vincula_imovel():
    texto = f"EDITAL DE LEILÃO Nº 01/2026\nImóvel rural CAR {CAR}. Leilão em 30/11/2026."
    eventos, estado = coleta.coletar_fonte({**FONTE, "max_paginas": 1}, AGORA, obter=lambda *_: (texto, "pdf_ocr"))
    assert len(eventos) == 1 and not eventos[0].codigos_car
    assert eventos[0].vinculo == "pendente" and eventos[0].car_fonte_url is None
    assert estado.situacao == "parcial"


def test_worker_limita_saida_memoria_e_tempo_sem_expor_stderr():
    assert (
        executar([sys.executable, "-c", "import sys;sys.stderr.write('descartar');print('ok')"], None, 5, 10) == b"ok\n"
    )
    with pytest.raises(ValueError, match="saída"):
        executar([sys.executable, "-c", "print('x'*1000000)"], None, 5, 100)
    with pytest.raises(ValueError, match="limites"):
        executar([sys.executable, "-c", "bytearray(2*1024**3)"], None, 5, 100)
    with pytest.raises(ValueError, match="tempo"):
        executar([sys.executable, "-c", "import time;time.sleep(5)"], None, 0.1, 100)
