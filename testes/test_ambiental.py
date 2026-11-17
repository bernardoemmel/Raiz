"""Vegetação e relevo na triagem (raiz/ambiental): reserva legal pela vegetação do IBGE, Lei da Mata Atlântica,
TerraClass e APP de relevo. Os códigos de vegetação abaixo são combinações reais do Mapa de Vegetação do IBGE
1:250 000 (versão 2026); os números de Boa Vista, Abreulândia e Parauapebas estão em docs/vegetacao-relevo.md."""

from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely

from raiz.ambiental import relevo as RV
from raiz.ambiental import status as ST
from raiz.ambiental import terraclass as TC
from raiz.ambiental import vegetacao as VG


@pytest.fixture(scope="module")
def regra():
    return ST.regra()


# --- classificação do IBGE ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("natural", "nome", "preterita", "regiao", "esperado"),
    [
        ("Dau", "Floresta Ombrófila Densa Aluvial com dossel uniforme", None, "D", "floresta"),
        ("Sas", "Savana Arborizada sem floresta-de-galeria", None, "S", "cerrado"),
        ("Sps", "Savana Parque sem floresta-de-galeria", "S", "S", "cerrado"),
        ("Sgs", "Savana Gramíneo-Lenhosa sem floresta-de-galeria", None, "S", "campos"),
        ("Ha", "Floresta Estacional Sempre Verde Aluvial", None, "SN", "floresta"),  # floresta dentro de contato
        ("SNt", "Contato Savana/Floresta Estacional", None, "SN", "transicao"),
        ("Lds", "Campinarana Florestada sem palmeiras", None, "L", "floresta"),
        ("Lgs", "Campinarana Gramíneo-Lenhosa sem palmeiras", None, "L", "campos"),
        ("Pfm", "Formação Pioneira com influência fluviomarinha arbórea", None, "P", "floresta"),
        ("Pahs", "Formação Pioneira com influência fluvial herbácea", None, "P", "campos"),
        (None, None, "F", "F", "floresta"),  # agropecuária sobre floresta estacional (vegetação pretérita)
        (None, None, "S", "S", "cerrado"),
        (None, None, "SN", "SN", "transicao"),
        (None, None, "ST", "ST", "cerrado"),
        (None, None, "ON", "ON", "floresta"),
        (None, None, "EP", "EP", "campos"),
        (None, None, None, "Magua", "agua"),
    ],
)
def test_classifica_codigos_reais_do_ibge(regra, natural, nome, preterita, regiao, esperado):
    assert VG.classificar_codigo(natural, nome, preterita, regiao, regra["vegetacao"]) == esperado


def test_lei_mata_atlantica_pega_formacoes_do_art2_e_nao_pega_varzea(regra):
    reg = regra["lei_mata_atlantica"]["regioes"]
    assert VG.lei_mata_atlantica("Ds", None, "D", reg)  # ombrófila densa
    assert VG.lei_mata_atlantica(None, "F", "F", reg)  # estacional antropizada
    assert VG.lei_mata_atlantica("Pfm", None, "P", reg)  # mangue
    assert not VG.lei_mata_atlantica("Pahs", None, "P", reg)  # várzea / Pantanal
    assert not VG.lei_mata_atlantica("Sas", None, "S", reg)  # cerrado
    assert VG.lei_mata_atlantica(None, "SN", "SN", reg)  # contato com estacional


# --- reserva legal por imóvel ------------------------------------------------------------------------------------


def _quadrado(x0, y0, lado):
    return shapely.box(x0, y0, x0 + lado, y0 + lado)


def _veg(partes):
    return gpd.GeoDataFrame(
        {"classe": [p[0] for p in partes], "regiao": [p[1] for p in partes], "lei_ma": [p[2] for p in partes]},
        geometry=[p[3] for p in partes],
        crs=4674,
    )


def test_boa_vista_lavrado_vale_35_e_nao_80(regra):
    """Imóvel em savana dentro do bioma Amazônia (Roraima): o motor dava 80%; a lei dá 35%."""
    car = gpd.GeoDataFrame({"cod_imovel": ["RR-1400100-A"]}, geometry=[_quadrado(-60.7, 2.8, 0.01)], crs=4674)
    veg = _veg([("cerrado", "S", False, _quadrado(-61, 2.5, 1))])
    m = VG.por_imovel(car, veg, "RR", regra)
    p = VG.percentuais(m, regra)
    assert p.pct_RL_vegetacao.iloc[0] == 35
    assert p.pct_RL_alem_vegetacao.iloc[0] == 35


def test_imovel_meio_floresta_meio_cerrado_soma_cada_parte(regra):
    """Art. 12 §2º: metade floresta (80) e metade cerrado (35) dá 57,5%."""
    car = gpd.GeoDataFrame(
        {"cod_imovel": ["TO-1700251-B"]}, geometry=[shapely.box(-49.0, -9.5, -48.98, -9.49)], crs=4674
    )
    veg = _veg([("floresta", "F", False, shapely.box(-49.1, -9.6, -48.99, -9.4)),
                ("cerrado", "S", False, shapely.box(-48.99, -9.6, -48.9, -9.4))])  # fmt: skip
    p = VG.percentuais(VG.por_imovel(car, veg, "TO", regra), regra)
    assert p.pct_RL_vegetacao.iloc[0] == pytest.approx(57.5, abs=0.3)
    assert p.pct_RL_alem_vegetacao.iloc[0] == pytest.approx(42.5, abs=0.3)  # floresta com 50% (art. 12 §4º)


def test_maranhao_a_leste_de_44_graus_fica_fora_da_amazonia_legal(regra):
    car = gpd.GeoDataFrame(
        {"cod_imovel": ["MA-2100000-L", "MA-2100000-O", "MA-2100000-M"]},
        geometry=[
            shapely.box(-43.9, -5.0, -43.88, -4.98),
            shapely.box(-44.2, -5.0, -44.18, -4.98),
            shapely.box(-44.01, -5.0, -43.99, -4.98),
        ],  # fmt: skip
        crs=4674,
    )
    veg = _veg([("cerrado", "S", False, shapely.box(-45, -6, -43, -4))])
    m = VG.por_imovel(car, veg, "MA", regra)
    p = VG.percentuais(m, regra)
    assert p.pct_RL_vegetacao.tolist()[:2] == [20, 35]
    assert p.pct_RL_vegetacao.iloc[2] == pytest.approx(27.5, abs=0.3)  # metade de cada lado do meridiano
    assert m.maranhao_leste_ha.iloc[0] == pytest.approx(m.ha_geo.iloc[0], rel=1e-6)


def test_fora_da_amazonia_legal_e_sempre_20(regra):
    car = gpd.GeoDataFrame({"cod_imovel": ["SP-3500000-A"]}, geometry=[_quadrado(-47.5, -22.5, 0.01)], crs=4674)
    veg = _veg([("floresta", "F", True, _quadrado(-48, -23, 1))])
    m = VG.por_imovel(car, veg, "SP", regra)
    assert VG.percentuais(m, regra).pct_RL_vegetacao.iloc[0] == 20
    assert m.lei_mata_atlantica_ha.iloc[0] == pytest.approx(m.ha_geo.iloc[0], rel=1e-6)


def test_sem_mapa_fica_vazio_e_nao_zero(regra):
    car = gpd.GeoDataFrame({"cod_imovel": ["PA-1500000-A"]}, geometry=[_quadrado(-52, -6, 0.01)], crs=4674)
    m = VG.por_imovel(car, None, "PA", regra)
    assert m.vegetacao_coberta_ha.isna().all()


def test_deficit_em_savana_usa_mapbiomas_e_nao_o_prodes():
    """O PRODES Amazônia chama savana de 'não floresta': no lavrado o motor não via a savana aberta."""
    im = pd.DataFrame({"ha": [100.0], "nao_floresta_ha": [100.0], "floresta_rem_ha": [0.0], "desm_total_ha": [0.0],
                       "m_fiscal": [10.0]}, index=["RR-1"])  # fmt: skip
    mb = pd.DataFrame({"mb_pasto_2025_ha": [80.0], "mb_agricultura_2025_ha": [0.0]}, index=["RR-1"])
    d = VG.deficit(im, pd.Series([35.0], index=im.index), pd.Series([35.0], index=im.index), mb=mb,
                   nao_floresta=pd.Series([True], index=im.index))  # fmt: skip
    assert d.rl_base_fonte.iloc[0] == "mapbiomas"
    assert d.deficit_RL_vegetacao_ha.iloc[0] == pytest.approx(15.0)  # 35 de reserva, 20 de savana em pé
    assert d.alem_RL_vegetacao_ha.iloc[0] == pytest.approx(65.0)  # 80 abertos menos 15 a recompor
    sem = VG.deficit(im, pd.Series([35.0], index=im.index), pd.Series([35.0], index=im.index))
    assert sem.rl_base_fonte.iloc[0] == "prodes" and sem.alem_RL_vegetacao_ha.iloc[0] == 0


def test_ate_4_modulos_nao_deve_reserva():
    im = pd.DataFrame({"ha": [50.0], "nao_floresta_ha": [0.0], "floresta_rem_ha": [10.0], "desm_total_ha": [40.0],
                       "m_fiscal": [2.0]}, index=["PA-1"])  # fmt: skip
    d = VG.deficit(im, pd.Series([80.0], index=im.index), pd.Series([50.0], index=im.index))
    assert d.alem_RL_vegetacao_ha.iloc[0] == 40  # art. 67: área aberta inteira


# --- relevo -------------------------------------------------------------------------------------------------------


def _cone(alt, raio, n=200, plano=100.0):
    y, x = np.mgrid[0:n, 0:n]
    d = np.hypot(x - n / 2, y - n / 2) * 30
    return plano + np.clip(alt * (1 - d / raio), 0, None)


def test_topo_de_morro_e_o_terco_de_cima(regra):
    z = _cone(800, 1000)  # 800 m de altura, encosta de 38,7 graus
    md, mt = RV.app_relevo(z, np.full(200, 30.0), 30.0, regra)
    esperado = np.pi * (1000 / 3 / 30) ** 2  # círculo acima de 2/3 da altura
    assert mt.sum() == pytest.approx(esperado, rel=0.05)
    assert md.sum() == 0  # menos de 45 graus


def test_morro_baixo_ou_suave_nao_tem_app(regra):
    for alt, raio in ((90, 200), (300, 1500)):  # menos de 100 m; inclinação média de 11 graus
        _, mt = RV.app_relevo(_cone(alt, raio), np.full(200, 30.0), 30.0, regra)
        assert mt.sum() == 0


def test_encosta_acima_de_45_graus(regra):
    md, _ = RV.app_relevo(_cone(1500, 1000), np.full(200, 30.0), 30.0, regra)
    assert md.sum() > 3000


def test_dois_morros_cada_um_com_seu_terco(regra):
    y, x = np.mgrid[0:200, 0:200]
    z = 100 + np.maximum(np.clip(800 * (1 - np.hypot(x - 60, y - 100) * 30 / 1000), 0, None),
                         np.clip(700 * (1 - np.hypot(x - 140, y - 100) * 30 / 1000), 0, None))  # fmt: skip
    _, mt = RV.app_relevo(z, np.full(200, 30.0), 30.0, regra)
    assert mt[:, :100].sum() > 300 and mt[:, 100:].sum() > 300


def test_morro_pequeno_em_cima_de_grande_entra_na_app_do_grande(regra):
    z = _cone(800, 1000)
    y, x = np.mgrid[0:200, 0:200]
    z = z + np.clip(50 * (1 - np.hypot(x - 100, y - 100) * 30 / 200), 0, None)  # pico de 50 m no cume
    _, mt = RV.app_relevo(z, np.full(200, 30.0), 30.0, regra)
    assert mt[100, 100]


def test_tile_do_anadem():
    assert RV.tile_anadem(-51.9, -6.6) == "22M"
    assert RV.tile_anadem(-60.7, 2.8) == "20N"
    assert RV.tile_anadem(-45.2, -23.3) == "23K"


def test_relevo_por_imovel_com_leitor_local(regra):
    """Um cone real em graus: o imóvel no cume pega APP de topo; o imóvel na planície, zero."""
    from rasterio.transform import from_origin

    res = 30 / 111320.0
    z = _cone(800, 1000)
    tr = from_origin(-50.0, -6.0, res, res)
    leitor = lambda cx: (z.copy(), tr, "anadem")  # noqa: E731
    cume = shapely.box(-50.0 + 95 * res, -6.0 - 105 * res, -50.0 + 105 * res, -6.0 - 95 * res)
    plan = shapely.box(-50.0 + 2 * res, -6.0 - 12 * res, -50.0 + 12 * res, -6.0 - 2 * res)
    car = gpd.GeoDataFrame({"cod_imovel": ["PA-1-C", "PA-1-P"]}, geometry=[cume, plan], crs=4326)
    r = dict(regra, relevo=dict(regra["relevo"], bloco_graus=1.0, borda_graus=0.0))
    out = RV.por_imovel(car, r, leitor=leitor).set_index("cod_imovel")
    assert out.loc["PA-1-C", "app_topo_morro_ha"] > 5
    assert out.loc["PA-1-P", "app_topo_morro_ha"] == 0
    assert out.relevo_fonte.eq("anadem_v1").all()
    assert out.app_relevo_aberta_ha.isna().all()  # sem MapBiomas não se sabe se está aberta


# --- TerraClass ---------------------------------------------------------------------------------------------------


def _raster(arquivo, arr, x0=-50.0, y0=-6.0, res=0.001):
    import rasterio
    from rasterio.transform import from_origin

    perfil = dict(driver="GTiff", width=arr.shape[1], height=arr.shape[0], count=1, dtype="uint8", crs="EPSG:4326",
                  transform=from_origin(x0, y0, res, res), nodata=0)  # fmt: skip
    with rasterio.open(arquivo, "w", **perfil) as o:
        o.write(arr, 1)


def test_terraclass_casa_classes_pelo_nome(tmp_path, regra):
    arr = np.full((100, 100), 11, np.uint8)
    arr[:, :50] = 7  # na legenda própria, 7 é pasto sujo (não é o número da Amazônia)
    arr[:20, :] = 3
    _raster(tmp_path / "terraclass_cerrado_2022.tif", arr)
    (tmp_path / "terraclass_cerrado_2022.json").write_text(
        json.dumps({"3": "Vegetação Natural Secundária", "7": "Pastagem Arbustiva", "11": "Pastagem Herbácea"}),
        encoding="utf-8",
    )
    car = gpd.GeoDataFrame({"cod_imovel": ["TO-1"]}, geometry=[shapely.box(-50.0, -6.1, -49.9, -6.0)], crs=4326)
    out = TC.por_imovel(car, tmp_path, regra)
    tot = out[list(TC.COLUNAS)].sum(axis=1).iloc[0]
    assert out.tc_pasto_sujo_ha.iloc[0] == pytest.approx(0.4 * tot, rel=0.02)
    assert out.tc_vegetacao_secundaria_ha.iloc[0] == pytest.approx(0.2 * tot, rel=0.02)
    assert out.tc_ano.iloc[0] == 2022 and out.tc_fonte.iloc[0] == "terraclass_cerrado_2022"


def test_terraclass_sem_arquivo_fica_vazio(tmp_path, regra):
    car = gpd.GeoDataFrame({"cod_imovel": ["TO-1"]}, geometry=[shapely.box(-50.0, -6.1, -49.9, -6.0)], crs=4326)
    out = TC.por_imovel(car, tmp_path / "nada", regra)
    assert out.tc_pasto_sujo_ha.isna().all() and out.tc_ano.isna().all()


# --- tarefa por município -----------------------------------------------------------------------------------------


def test_municipio_ponta_a_ponta(tmp_path, regra):
    """Roraima: lavrado diverge do motor (ressalva); sem relevo o imóvel fica nao_verificado; com relevo plano, ressalva
    só pelo índice; nunca sai do lote."""
    pasta = tmp_path / "RR"
    camadas = tmp_path / "camadas"
    pasta.mkdir()
    camadas.mkdir()
    g = [_quadrado(-60.70, 2.80, 0.01), _quadrado(-60.60, 2.80, 0.01)]
    car = gpd.GeoDataFrame({"cod_imovel": ["RR-1400100-A", "RR-1400100-B"]}, geometry=g, crs=4674).to_crs(5880)
    car.to_parquet(pasta / "geo_1400100.parquet")
    im = pd.DataFrame({"cod_imovel": ["RR-1400100-A", "RR-1400100-B"], "ha": [120.0, 120.0], "nao_floresta_ha": [0, 0],
                       "floresta_rem_ha": [100.0, 60.0], "desm_total_ha": [20.0, 60.0], "m_fiscal": [8, 8],
                       "pct_RL": [80, 35], "alem_RL_ha": [0.0, 20.0]})  # fmt: skip
    im.to_csv(pasta / "imoveis_1400100.csv", index=False)
    _veg([("cerrado", "S", False, _quadrado(-61, 2.5, 1))]).to_parquet(camadas / ST.NOMES["vegetacao"])
    (camadas / ST.NOMES["cobertura"]).write_text(json.dumps({"fontes": {}}), encoding="utf-8")

    sem_relevo = ST.calcular_municipio(pasta, 1400100, camadas=ST.Camadas(camadas, relevo=False),
                                       cobertura_mapbiomas=False)  # fmt: skip
    assert sem_relevo.ambiental_status.eq("nao_verificado").all()
    assert "relevo" in sem_relevo.ambiental_nao_verificadas.iloc[0]

    plano = lambda cx: (np.full((50, 50), 90.0), __import__("rasterio").transform.from_bounds(*cx, 50, 50), "anadem")  # noqa: E731
    df = ST.escrever_municipio(pasta, 1400100, camadas=ST.Camadas(camadas, relevo=True), leitor_relevo=plano,
                               cobertura_mapbiomas=False).set_index("cod_imovel")  # fmt: skip
    assert (pasta / "ambiental_1400100.csv").exists()
    assert df.loc["RR-1400100-A", "ambiental_status"] == "ressalva"
    assert df.loc["RR-1400100-A", "ambiental_motivos"] == "rl_vegetacao_diverge"
    assert df.loc["RR-1400100-B", "ambiental_status"] == "livre"  # motor já tinha 35
    assert df.pct_RL_vegetacao.eq(35).all()
    assert list(df.reset_index().columns) == ST.COLUNAS
    assert ST.resumo(df.reset_index())["ressalva"] == 1


def test_restauracao_prefere_reserva_pela_vegetacao():
    from raiz.restauracao import area_restauravel

    base = {"alem_RL_ha": 0.0, "pasto_ha": 50.0, "ha": 100.0, "app_recompor_ha": 0.0}
    assert area_restauravel(base) == 0
    assert area_restauravel({**base, "alem_RL_vegetacao_ha": 30.0}) == 30


def test_checklist_do_lote():
    from raiz.lote import ambiental_do_lote

    assert ambiental_do_lote(pd.DataFrame({"x": [1]}))["situacao"] == "pendente"
    lote = pd.DataFrame({"ambiental_status": ["livre", "ressalva", "nao_verificado"],
                         "ambiental_motivos": [None, "pasto_sujo|rl_transicao", None]})  # fmt: skip
    it = ambiental_do_lote(lote)
    assert it["situacao"] == "pendente"
    assert "pasto_sujo: 1" in it["detalhe"] and "1 sem verificação" in it["detalhe"]
    assert (
        ambiental_do_lote(pd.DataFrame({"ambiental_status": ["livre"], "ambiental_motivos": [None]}))["situacao"]
        == "ok"
    )


def test_oferta_leva_status_sem_bloquear():
    from raiz.pedidos.oferta import _ambiental

    linha = {"ambiental_status": "ressalva", "ambiental_motivos": "rl_transicao", "pct_RL_vegetacao": 80.0}
    assert _ambiental(linha) == linha
    assert _ambiental({})["ambiental_status"] is None


def test_regra_nao_corta_por_tamanho(regra):
    """Limiar mede a área marcada: imóvel de 2 ha com 0,2 ha marcado passa pela fração."""
    assert ST._passa(pd.Series([0.2]), pd.Series([2.0]), regra)[0]
    assert not ST._passa(pd.Series([0.05]), pd.Series([2.0]), regra)[0]
