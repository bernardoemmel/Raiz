import pytest

from raiz import restauracao_ecologia as E
from raiz import restauracao_ecologia_regional as R


def test_referencias_nao_viram_especies_totais_ou_arvores_distintas():
    linha = dict(cod_imovel="PA-sintetico", uf="PA", bioma="Amazônia", modo_restauracao="regeneracao_assistida")
    a = E.projetar({**linha, "restauracao_area_ha": 0.1}, "modelo-teste")
    b = E.projetar({**linha, "restauracao_area_ha": 1000}, "modelo-teste")
    h = next(x for x in a["horizontes"] if x["ano"] == 5)
    ref = h["referencia_regional_padronizada"]
    assert len(ref) == 1 and ref[0]["indicador"] == "riqueza_rarefeita_por_25_fustes"
    assert ref[0]["p50"] == pytest.approx(8.97932218707968)
    assert ref == next(x for x in b["horizontes"] if x["ano"] == 5)["referencia_regional_padronizada"]
    assert h["numero_especies"]["p50"] is None
    assert h["densidade_arvores_ha"]["p50"] is None
    assert ref[0]["peso_inventario_local"] == 0
    assert ref[0]["fonte_documentada"]["licenca_dados"] == "CC0-1.0"


def test_nao_transfere_fustes_tefe_para_para_nem_regeneracao_para_plantio():
    linha = dict(uf="PA", bioma="Amazônia", modo_restauracao="plantio_total")
    assert not R.referencias(linha, 5)
    am = R.referencias({**linha, "uf": "AM", "modo_restauracao": "regeneracao_assistida"}, 5)
    assert len(am) == 2
    fustes = next(x for x in am if x["indicador"] == "densidade_fustes_ha")
    assert fustes["p50"] == 1880
    assert not fustes["previsao_validada_em_fazenda"]
    assert R.catalogo()["experimentos_rejeitados"][0]["aprovado"] is False


def test_plantio_mata_atlantica_tem_quatro_horizontes_contextuais():
    linha = dict(uf="SP", bioma="Mata Atlântica", modo_restauracao="plantio_total")
    for idade, mediana in [(3, 11), (5, 12), (10, 19), (15, 23.5)]:
        ref = R.referencias(linha, idade)
        assert len(ref) == 1 and ref[0]["p50"] == mediana
        assert ref[0]["area_amostral_m2"] == 900
        assert ref[0]["fonte_documentada"]["licenca_dados"] == "CC-BY-4.0"
