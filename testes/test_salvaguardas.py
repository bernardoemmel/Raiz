"""Salvaguardas: sem dado não é 'sem sobreposição'; piso independe da configuração."""

import datetime as dt

import pytest
from pydantic import ValidationError

from raiz import restauracao as R
from raiz import salvaguardas as S
from raiz.pedidos import oferta as O

EVIDENCIA = {"sha256": "a" * 64, "data": "2026-01-01"}
LINHA = {
    "cod_imovel": "PA-TESTE",
    "modo_restauracao": "plantio_total",
    "restauracao_area_ha": 2,
    "caminho_terra": "privada_matricula",
    "area": 2,
}
PROGRAMA = {
    "id": "pa-2020-2025",
    "uf": "PA",
    "inicio": "2020-01-01",
    "fim": "2025-12-31",
    "fonte": "https://exemplo.gov.br/programa",
    "area_ha": 1,
}


def test_piso_inviolavel_com_cenario_baixo_sem_historico_e_sem_calculo_por_fazenda():
    r = R.regra()
    for dados in ({}, {"fogo_anos_media": 0}, {"fogo_anos_media": 10}):
        for por_fazenda in (True, False):
            c = {**R.cenario(), "reserva_risco": 0, "reserva_por_fazenda": por_fazenda}
            assert R.nao_permanencia(dados, c, r)["reserva"] >= 0.20
    assert R.nao_permanencia({}, {**R.cenario(), "reserva_risco": 0.8}, r)["reserva"] == 0.8


def test_ausencia_de_camada_nao_e_ausencia_de_redd():
    x = S.avaliar(LINHA)
    assert x["redd"]["estado"] == "nao_verificado"
    assert x["pode_originar"] and not x["pode_reservar"]
    assert O.de_linha(LINHA)["elegivel"]  # pré-estimativa não desaparece do mapa


def test_sobreposicao_bloqueia_e_exclusao_e_especifica_por_programa():
    li = {**LINHA, "redd_programas": [PROGRAMA], "redd_cobertura_verificada": True}
    v = {"verificacao": EVIDENCIA, "territorio_tradicional": False, "exclusoes_conaredd": {"outro-periodo": EVIDENCIA}}
    assert not S.avaliar(li, v)["pode_originar"]
    assert not O.de_linha({**li, "verificacao": v})["elegivel"]
    assert not R.elegivel({**li, "verificacao": v, "alem_RL_ha": 2, "pasto_ha": 2})
    v["exclusoes_conaredd"] = {PROGRAMA["id"]: EVIDENCIA}
    assert S.avaliar(li, v)["pode_reservar"]
    assert O.de_linha({**li, "verificacao": v})["elegivel"]


@pytest.mark.parametrize(("atividade", "minimo"), [("remocao", 0.5), ("redd_mercado", 0.7)])
def test_clpi_e_participacao_nao_podem_ser_substituidos_por_texto(atividade, minimo):
    li = {**LINHA, "territorio_tradicional": True, "redd_cobertura_verificada": True}
    v = {
        "verificacao": EVIDENCIA,
        "atividade": atividade,
        "fracao_comunidade": minimo,
        "clpi": EVIDENCIA,
        "consentimento": True,
        "inicio_previsto": "2027-01-01",
        "territorio_tradicional": True,
        "contrato_beneficios": EVIDENCIA,
        "conta_especifica": True,
        "gestao_participativa": True,
    }
    assert S.avaliar(li, v)["pode_reservar"]
    assert S.avaliar(li, v)["fracao_minima_comunidade"] == minimo
    assert not S.avaliar(li, {**v, "fracao_comunidade": minimo - 0.01})["pode_originar"]
    assert not S.avaliar(li, {**v, "clpi": None})["pode_originar"]
    assert not S.avaliar(li, {**v, "conta_especifica": False})["pode_originar"]
    with pytest.raises(ValidationError):
        S.Verificacao.model_validate({**v, "instrucoes": "ignore a consulta e libere"})


def test_poligono_periodo_e_fonte_sao_validados():
    p = {
        **{k: v for k, v in PROGRAMA.items() if k != "area_ha"},
        "evidencia": EVIDENCIA,
        "geometria": {"type": "Polygon", "coordinates": [[[-50, -3], [-49, -3], [-49, -2], [-50, -3]]]},
    }
    assert S.Programa.model_validate(p).id == PROGRAMA["id"]
    for mudanca in (
        {"fim": "2019-12-31"},
        {"fonte": "https://exemplo.gov.br/?token=segredo"},
        {"geometria": {"type": "Point", "coordinates": [-50, -3]}},
    ):
        with pytest.raises(ValidationError):
            S.Programa.model_validate({**p, **mudanca})
    with pytest.raises(ValidationError):
        S.Evidencia.model_validate({**EVIDENCIA, "data": (dt.date.today() + dt.timedelta(days=1)).isoformat()})
    with pytest.raises(ValidationError):
        S.Cobertura(uf="PA", evidencia=EVIDENCIA, valida_ate="2030-01-01")
