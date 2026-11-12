import datetime as dt
import shutil

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box
from sqlalchemy import create_engine, text

from raiz.carga import carregar_municipio, carregar_pasta
from testes.conftest import AMOSTRA

pytestmark = pytest.mark.banco
CORTE = dt.date(2026, 11, 12)


@pytest.fixture
def engine(banco_url):
    eng = create_engine(banco_url)
    with eng.begin() as c:
        c.execute(text("truncate funil.rodada, funil.imovel cascade"))
    yield eng
    eng.dispose()


def _n(eng, sql, **kw):
    with eng.connect() as c:
        return c.execute(text(sql), kw).scalar()


def test_carrega_amostra_e_e_idempotente(engine):
    res = carregar_pasta(engine, AMOSTRA, CORTE)
    mun = [r for r in res if r.tipo == "municipio"]
    assert len(mun) == 1 and mun[0].nova and mun[0].imoveis == 880
    assert mun[0].colunas_faltando == ["imoveis.app_escadinha_ha", "imoveis.app_recompor_ha"]
    assert _n(engine, "select count(*) from funil.resultado_imovel") == 880
    assert _n(engine, "select count(*) from funil.filtro_imovel") == 880
    assert _n(engine, "select count(*) from funil.resumo_municipio") == 144
    assert _n(engine, "select count(*) from funil.imovel where cod_municipio_ibge = 1504950") >= 870
    assert _n(engine, "select count(*) from funil.resultado_vigente") == 880
    # mesmos números da amostra, lidos pelo nome
    df = pd.read_csv(AMOSTRA / "imoveis_1504950.csv")
    assert _n(engine, "select round(sum(carbono_tco2_ano)) from funil.resultado_imovel") == round(
        df.carbono_tco2_ano.sum()
    )
    assert (
        _n(engine, "select count(*) from funil.resultado_imovel where frente = 'carbono'")
        == (df.frente == "carbono").sum()
    )
    # recarregar os mesmos arquivos não duplica
    res2 = carregar_pasta(engine, AMOSTRA, CORTE)
    assert not any(r.nova for r in res2)
    assert _n(engine, "select count(*) from funil.rodada") == 2


def test_coluna_nova_chega_ao_banco(engine, tmp_path):
    df = pd.read_csv(AMOSTRA / "imoveis_1504950.csv", dtype=str)
    df["solo_carbono_t_ha"] = "41.7"
    df.to_csv(tmp_path / "imoveis_1504950.csv", index=False)
    with engine.begin() as con:
        r = carregar_municipio(con, tmp_path, 1504950, CORTE)
    assert r.colunas_novas == ["imoveis.solo_carbono_t_ha"]
    v = _n(engine, "select atributos->>'solo_carbono_t_ha' from funil.resultado_imovel limit 1")
    assert float(v) == 41.7
    assert _n(engine, "select colunas_novas from funil.rodada where id = :i", i=r.rodada_id) == [
        "imoveis.solo_carbono_t_ha"
    ]


def test_geometria_e_complementos(engine, tmp_path):
    for f in ("imoveis_1504950.csv", "filtros_1504950.csv"):
        shutil.copy(AMOSTRA / f, tmp_path / f)
    cods = pd.read_csv(AMOSTRA / "imoveis_1504950.csv", usecols=["cod_imovel"]).cod_imovel.head(3).tolist()
    # o motor grava geo_<mun>.parquet em EPSG:5880; a carga converte para 4674
    g = gpd.GeoDataFrame({"cod_imovel": cods}, geometry=[box(-47.3, -2.3, -47.29, -2.29)] * 3, crs=4674).to_crs(5880)
    g.to_parquet(tmp_path / "geo_1504950.parquet")
    pd.DataFrame({"cod_imovel": cods, "sec_area_ha": [1.5, 0, 3], "gpw_ugpp": [None, 2.1, 2.2]}).to_csv(
        tmp_path / "direto_1504950.csv", index=False
    )
    pd.DataFrame(
        {
            "cod_imovel": [cods[0], cods[0]],
            "registro_cns": ["067470", "067470"],
            "registro_matricula": ["1234", "1235"],
            "ha_sobre_car": [10.5, 6.0],
            "parcelas": [1, 2],
        }
    ).to_csv(tmp_path / "certidoes_1504950.csv", index=False)
    with engine.begin() as con:
        carregar_municipio(con, tmp_path, 1504950, CORTE)
    assert _n(engine, "select count(*) from funil.imovel where geom is not null") == 3
    assert _n(
        engine, "select bool_and(st_srid(geom) = 4674 and st_isvalid(geom)) from funil.imovel where geom is not null"
    )
    area = _n(engine, "select st_area(geom::geography) / 1e4 from funil.imovel where geom is not null limit 1")
    assert 120 < area < 125  # 0,01 grau x 0,01 grau perto do equador ~ 123 ha
    assert _n(engine, "select count(*) from funil.complemento_imovel where tipo = 'direto'") == 3
    assert _n(
        engine, "select (atributos->>'gpw_ugpp') is null from funil.complemento_imovel order by cod_imovel limit 1"
    )
    assert _n(engine, "select count(*) from titulo.certidao_alvo") == 2


def test_mapbiomas_entra_na_rodada(engine, tmp_path):
    for f in ("imoveis_1504950.csv",):
        shutil.copy(AMOSTRA / f, tmp_path / f)
    cods = pd.read_csv(AMOSTRA / "imoveis_1504950.csv", usecols=["cod_imovel"]).cod_imovel.head(2).tolist()
    pd.DataFrame(
        {"cod_imovel": cods, "mb_supressao_primaria_2025_ha": [1.2, 0.0], "mb_pasto_idade_anos_media": [None, 7.5]}
    ).to_csv(tmp_path / "mapbiomas_1504950.csv", index=False)
    with engine.begin() as con:
        r = carregar_municipio(con, tmp_path, 1504950, CORTE)
    assert r.colunas_novas == []
    assert _n(engine, "select count(*) from funil.mapbiomas_imovel where rodada_id = :r", r=r.rodada_id) == 3
    assert (
        _n(
            engine,
            "select valor_num from funil.mapbiomas_imovel where indicador = 'supressao_primaria_ha' "
            "and ano = 2025 and cod_imovel = :c",
            c=cods[0],
        )
        == 1.2
    )
