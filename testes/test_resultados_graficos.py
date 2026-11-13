"""Fatos não viram previsões ou zeros; referências incompatíveis e extras nunca chegam à API."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from raiz.pedidos.resultados_graficos import ResultadosGraficos

FIXTURE = Path(__file__).parent / "fixtures" / "resultados_graficos_sinteticos.json"


@pytest.fixture
def resultados():
    return json.loads(FIXTURE.read_text())


def test_preserva_zero_ausencia_e_marca_sintetica(resultados):
    dado = ResultadosGraficos.model_validate(resultados).model_dump(mode="json", by_alias=True)
    assert dado == resultados
    assert dado["contratos"][0]["marcos"][0]["emitido"] is None
    assert dado["contratos"][0]["marcos"][1]["emitido"]["valor"] == 0


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("classe", "flag"),
        ("area_base_ha", 21),
        ("area_elegivel_carteira_ha", 21),
        ("escopo_carteira", "titulares_e_reservas"),
        ("metrica", "captura_bruta"),
    ],
)
def test_nao_pareia_referencias_distintas(resultados, campo, valor):
    resultados["comparacoes"][0]["observado"]["referencia"][campo] = valor
    with pytest.raises(ValidationError):
        ResultadosGraficos.model_validate(resultados)


@pytest.mark.parametrize(
    "alvo", ["fonte", "cronologia", "futuro", "nao_finito", "quantis", "estimativa", "pii", "duplicado"]
)
def test_rejeita_evidencia_invalida_e_campos_livres(resultados, alvo):
    c = resultados["comparacoes"][0]
    if alvo == "fonte":
        del c["observado"]["fonte"]["registro_id"]
    elif alvo == "cronologia":
        c["previsao"]["congelada_em"] = "2026-01-01T00:00:00Z"
    elif alvo == "futuro":
        c["observado"]["registrado_em"] = "2027-01-01T00:00:00Z"
    elif alvo == "nao_finito":
        c["observado"]["valor"] = float("nan")
    elif alvo == "quantis":
        c["previsao"]["p10"] = 200
    elif alvo == "estimativa":
        resultados["contratos"][0]["marcos"][0]["contratado"]["natureza"] = "estimativa"
    elif alvo == "pii":
        c["observado"]["dono"] = "campo proibido, valor sintético"
    elif alvo == "duplicado":
        resultados["comparacoes"].append(deepcopy(c))
    with pytest.raises(ValidationError):
        ResultadosGraficos.model_validate(resultados)


def test_backtest_declarado_fica_separado(resultados):
    c = resultados["comparacoes"][0]
    c["avaliacao"] = "backtest"
    c["previsao"]["congelada_em"] = "2026-01-02T00:00:00Z"
    assert ResultadosGraficos.model_validate(resultados).comparacoes[0].avaliacao == "backtest"


@pytest.mark.parametrize("alvo", ["fonte_livre", "origem", "booleano"])
def test_recusa_fonte_livre_e_mistura_de_evidencia(resultados, alvo):
    if alvo == "fonte_livre":
        resultados["comparacoes"][0]["observado"]["fonte"]["nome"] = "fonte livre não autorizada"
    elif alvo == "origem":
        resultados["origem"] = "real"
    else:
        resultados["comparacoes"][0]["observado"]["valor"] = True
    with pytest.raises(ValidationError):
        ResultadosGraficos.model_validate(resultados)


def test_por_hectare_preserva_denominador_original(resultados):
    for c in resultados["comparacoes"]:
        for campo in ("previsao", "observado"):
            c[campo]["referencia"].update(escala="por_hectare", unidade="tCO2e/ha", area_base_ha=1)
    dado = ResultadosGraficos.model_validate(resultados)
    assert dado.comparacoes[0].previsao.referencia.area_elegivel_carteira_ha == 20
    resultados["comparacoes"][0]["observado"]["referencia"]["area_elegivel_carteira_ha"] = 30
    with pytest.raises(ValidationError):
        ResultadosGraficos.model_validate(resultados)
