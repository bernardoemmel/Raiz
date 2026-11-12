import datetime as dt

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from raiz.coleta import manifesto as M
from raiz.coleta import ppm
from raiz.coleta.replicacao import atualizar, devidas, estado, evento, sincronizar_fontes


def test_manifesto_valido():
    m = M.carregar()
    assert m.fonte("sicar_imoveis").tipo == "wfs"
    assert m.fonte("ibama_embargos").descartar_na_entrada == ["nome", "cpf", "cnpj"]
    # Heinrich 2021 é não comercial: só comparação
    assert m.pode_treinar("heinrich_2021") is False and m.pode_treinar("groa") is True
    # fonte sem endereço não é coletada, só fica a pendência
    assert not m.fonte("sigmine").ativa and m.fonte("sigmine").pendente


def test_licenca_nao_comercial_nao_treina():
    with pytest.raises(ValidationError, match="não comercial"):
        M.Fonte(id="x", nome="x", orgao="x", tipo="cog", url="u", recorte="brasil", sinal={}, calendario="diario",
                licenca="CC BY-NC 4.0, não comercial", pode_treinar=True)  # fmt: skip


def test_rodizio_cobre_todas_as_ufs_sem_sobrecarregar():
    semana = [M.ufs_do_dia(dt.date(2026, 11, 16) + dt.timedelta(days=i)) for i in range(7)]
    todas = [uf for dia in semana for uf in dia]
    assert sorted(todas) == sorted(M.UFS)
    assert all(3 <= len(d) <= 4 for d in semana)
    # as duas maiores não caem no mesmo dia
    assert M.dia_da_uf("BA") != M.dia_da_uf("MG")


def test_calendario():
    m = M.carregar()
    seg, sab = dt.date(2026, 11, 16), dt.date(2026, 11, 21)
    ids_seg = dict(devidas(m, seg))
    assert "ibama_embargos" in ids_seg and ids_seg["sicar_imoveis"] == M.ufs_do_dia(seg)
    assert "deter" not in ids_seg
    assert "deter" in dict(devidas(m, sab))  # DETER no sábado
    assert m.fonte("prodes").devida(dt.date(2026, 10, 1)) and not m.fonte("prodes").devida(dt.date(2026, 10, 2))
    assert m.fonte("ibge_ppm").devida(seg) is False  # quem decide é o calendário do IBGE


PAGINAS = {
    1: {"items": [{"produto_id": 9107, "tipo_id": 1, "ano_referencia_inicio": 2024, "mes_referencia_inicio": 1,
                   "data_divulgacao": "18/09/2025 10:00:00"},
                  {"produto_id": 9107, "tipo_id": 2, "ano_referencia_inicio": 2024, "mes_referencia_inicio": 1,
                   "data_divulgacao": "01/01/2025 10:00:00"}], "nextPage": 2},
    2: {"items": [{"produto_id": 9107, "tipo_id": 1, "ano_referencia_inicio": 2025, "mes_referencia_inicio": 1,
                   "data_divulgacao": "17/09/2026 10:00:00"}], "nextPage": 0},
}  # fmt: skip


def test_gatilho_ppm():
    cli = httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json=PAGINAS[int(req.url.params["page"])])))  # fmt: skip
    divs = ppm.divulgacoes(ppm.buscar_paginas(cli))
    assert [(d.ano_referencia, d.data) for d in divs] == [(2024, dt.date(2025, 9, 18)), (2025, dt.date(2026, 9, 17))]
    assert ppm.deve_coletar(divs, 2024, dt.date(2026, 9, 16)) is None  # 2025 ainda não saiu
    assert ppm.deve_coletar(divs, 2024, dt.date(2026, 9, 17)).ano_referencia == 2025
    assert ppm.deve_coletar(divs, 2025, dt.date(2026, 12, 1)) is None


@pytest.mark.banco
def test_replicacao_no_banco(banco_url):
    eng = create_engine(banco_url)
    with eng.begin() as c:
        c.execute(text("truncate coleta.replicacao, coleta.evento, coleta.fonte cascade"))
        assert sincronizar_fontes(c) == len(M.carregar().fontes)
        assert sincronizar_fontes(c) == len(M.carregar().fontes)  # idempotente
        atualizar(c, "sicar_imoveis", "PA/1504950", contagem=880, assinatura="880|2026-07-20", sujo=False)
        atualizar(c, "sicar_imoveis", "PA/1504950", etag='W/"x"')
        r = estado(c, "sicar_imoveis", "PA/1504950")
        assert (r.contagem, r.etag, r.sujo) == (880, 'W/"x"', False)
        with pytest.raises(ValueError):
            atualizar(c, "sicar_imoveis", "PA/1", campo_errado=1)
        evento(c, "sicar_imoveis", "PA/1504950", "mudaram", 3, {"exemplo": ["PA-1504950-X"]})
        assert (
            c.execute(text("select pode_treinar from coleta.fonte where id = 'mapbiomas_plataforma'")).scalar() is False
        )
    eng.dispose()
