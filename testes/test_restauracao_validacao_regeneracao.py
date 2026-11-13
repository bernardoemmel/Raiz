import numpy as np
import pandas as pd
import pytest

from raiz import restauracao_validacao_regeneracao as V


def parcelas():
    return pd.DataFrame(
        [
            {
                "plot_id": f"{mun}-{idade}",
                "cod_ibge": mun,
                "forest_age_years": idade,
                "biomass_total_Mg_ha": 200 * idade / (20 + idade) + mun,
            }
            for mun in (1, 2, 3, 4)
            for idade in (2, 5, 10, 15, 25, 50, 90)
        ]
    )


def test_holdout_municipal_nunca_vaza_para_ajuste_ou_intervalos():
    a = parcelas()
    b = a.copy()
    b.loc[b.cod_ibge == 1, "biomass_total_Mg_ha"] *= 10
    ra = V.validar_municipios(a, fonte_sha256="a" * 64)
    rb = V.validar_municipios(b, fonte_sha256="b" * 64)
    fora_a = [p for p in ra["previsoes"] if p["municipio_excluido"] == "1"]
    fora_b = [p for p in rb["previsoes"] if p["municipio_excluido"] == "1"]
    for x, y in zip(fora_a, fora_b, strict=True):
        assert x["treino_sha256"] == y["treino_sha256"]
        assert "1" not in x["treino_municipios"]
        assert (x["p10"], x["p50"], x["p90"]) == (y["p10"], y["p50"], y["p90"])
        assert x["erro_Mg_ha"] != y["erro_Mg_ha"]
    assert sum(m["n"] for m in ra["metricas_por_idade"]) == len(a)
    assert not ra["substitui_credito_liquido"]


def test_gravacao_preserva_previsoes_e_identidade(tmp_path):
    r = V.validar_municipios(parcelas(), fonte_sha256="a" * 64)
    p = V.gravar(r, tmp_path)
    assert V.gravar(r, tmp_path) == p
    assert all(x["modelo_versao"] == V.versao() for x in r["previsoes"])
    assert "responsible" not in p.read_text()
    p.write_text("alterado")
    with pytest.raises(ValueError, match="existente alterado"):
        V.gravar(r, tmp_path)


@pytest.mark.parametrize("sinal", [-1, 1])
def test_quantis_residuais_nao_sao_forcados_a_conter_curva(monkeypatch, sinal):
    monkeypatch.setattr(V, "_ajustar", lambda _: (np.array([200, 20]), sinal * np.array([2, 4, 8])))
    r = V.validar_municipios(parcelas(), fonte_sha256="a" * 64)
    for p in r["previsoes"]:
        base = p["curva_sem_correcao_residual_Mg_ha"]
        esperado = np.maximum(0, base + np.quantile(sinal * np.array([2, 4, 8]), [0.1, 0.5, 0.9]))
        assert [p["p10"], p["p50"], p["p90"]] == pytest.approx(esperado)


def test_juncao_usa_geometria_e_recusa_parcela_fora_ou_ambigua():
    import geopandas as gpd
    from shapely.geometry import box

    malha = gpd.GeoDataFrame({"CD_MUN": ["1501", "1502"]}, geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)], crs=4326)
    p = pd.DataFrame({"plot_id": ["qualquer"], "longitude": [0.5], "latitude": [0.5], "responsible": ["remover"]})
    assert V.vincular_municipios(p, malha).cod_ibge.tolist() == ["1501"]
    assert "responsible" not in V.vincular_municipios(p, malha)
    for longitude in (1, 3):
        p["longitude"] = longitude
        with pytest.raises(ValueError, match="fora da malha|ambíguo"):
            V.vincular_municipios(p, malha)


@pytest.mark.parametrize("valor", [-1, np.inf, np.nan])
def test_observacao_invalida_nao_gera_erro_falso(valor):
    t = parcelas()
    t.loc[0, "biomass_total_Mg_ha"] = valor
    with pytest.raises(ValueError):
        V.validar_municipios(t, fonte_sha256="a" * 64)
