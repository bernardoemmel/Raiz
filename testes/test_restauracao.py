"""Valor para quem restaura: modo pela regra escrita, os dois métodos disputando cada fazenda com as premissas da
rodada 11, custo e captura em faixa, linha de base medida ao lado da do cenário (mostrada, não escondida), crédito
líquido, simulador, lotes de fazendas vizinhas sem descartar pequenas, versão das premissas e as entradas geográficas
num raster sintético."""

import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from raiz import desenvolvedor as D
from raiz import restauracao as R
from testes.conftest import AMOSTRA

RAIZ = Path(__file__).resolve().parents[1]


def _linha(**kw):
    """Fazenda de 100 ha de pasto livre no leste do Pará, com as entradas geográficas preenchidas."""
    base = {
        "cod_imovel": "PA-1-A",
        "uf": "PA",
        "bioma": "Amazônia",
        "alem_RL_ha": 100.0,
        "app_recompor_ha": 0.0,
        "pasto_ha": 100.0,
        "taxa_tco2_ha_ano": 5.91,
        "pasto_d0_ha": 0.0,
        "pasto_d1_ha": 0.0,
        "pasto_d2_ha": 0.0,
        "pasto_d3_ha": 100.0,
        "mb_pasto_idade_anos_media": 20,
        "mb_pasto_vigor_principal": 2,
        "fogo_anos_media": 0.5,
        "declividade_media_pct": 5,
        "estrada_acesso_km": 1,
        "cidade_proxima_km": 20,
        "chuva_mm_ano": 2200,
        "solo_cec_cmolc_kg": 10,
        # taxas do município medidas no YbYrá (pasto que vira mata sozinho por ano, por faixa de distância)
        "linha_base_taxa_d0": 0.028,
        "linha_base_taxa_d1": 0.0073,
        "linha_base_taxa_d2": 0.0013,
        "linha_base_taxa_d3": 0.0009,
        "linha_base_fonte": "ybyra_2024_municipio",
    }
    return {**base, **kw}


PERTO = {"pasto_d0_ha": 85.0, "pasto_d1_ha": 15.0, "pasto_d3_ha": 0.0, "mb_pasto_idade_anos_media": 8,
         "fogo_anos_media": 0.1}  # fmt: skip


def test_cenario_vem_das_premissas_da_rodada_11():
    """Custo, captura, descontos, receita, dívida e dono saem de motor/premissas/restauracao_v2026_11.yaml."""
    c = R.cenario()
    assert c == D.cenario() and c["cenario"] == "central"
    assert (c["preco_contrato_usd_t"], c["fracao_financiada"], c["juros_ano"]) == (55, 0.5, 0.0494)
    assert c["carencia_anos"] == 8
    r = R.regra()
    assert r["premissas"]["versao"] == "premissas-2026-11" and r["versao_completa"].startswith("restauracao-2026b+")
    assert "custo_rs_ha" not in r and "captura_tco2_ha_ano" not in r  # não há duas fontes para o mesmo número
    longe = R.por_imovel(_linha())
    assert longe["tir_desenvolvedor"] == longe["metodo_plantio_tir_pct"] == pytest.approx(6.0, abs=0.2)
    assert longe["tir_alavancada_pct_p10"] <= longe["tir_desenvolvedor"] <= longe["tir_alavancada_pct_p90"]
    assert longe["icsd_minimo"] >= 1.3 - 1e-6 and 0 < longe["fracao_divida"] <= 0.5
    assert longe["fator_liquido"] == pytest.approx(0.5702, abs=1e-4) and longe["vazamento_motivo"] == "cenario"


def test_fazenda_perto_de_mata_e_regeneracao_assistida_barata_com_linha_de_base_alta():
    perto = R.por_imovel(_linha(**PERTO))
    longe = R.por_imovel(_linha())
    assert perto["modo_restauracao"] == "regeneracao_assistida"
    assert perto["restauracao_regeneracao_assistida_ha"] == pytest.approx(100)
    assert perto["custo_restauracao_ha_p50"] == pytest.approx(4230 + 800) and perto["custo_restauracao_ha_p90"] <= 6100
    # onde a mata volta sozinha a linha de base medida é alta e aparece ao lado da do cenário, não some
    assert perto["desconto_linha_base_pct"] >= 10
    assert perto["desconto_linha_base_pct"] > 10 * longe["desconto_linha_base_pct"]
    assert perto["linha_base_cenario_pct"] == 20 and not perto["linha_base_medida_acima"]
    muito = R.por_imovel(_linha(**PERTO, linha_base_taxa_d0=0.06, linha_base_taxa_d1=0.04))
    assert muito["desconto_linha_base_pct"] > 20 and muito["linha_base_medida_acima"]
    assert perto["linha_base_regenera_pct"] > 30
    assert perto["credito_liquido_tco2_ha_ano"] < perto["captura_tco2_ha_ano_p50"] * 0.88 * 0.9
    assert perto["linha_base_fonte"] == "ybyra_2024_municipio"


def test_fazenda_longe_de_mata_e_plantio_total():
    longe = R.por_imovel(_linha())
    assert longe["modo_restauracao"] == "plantio_total"
    assert longe["restauracao_plantio_total_ha"] == pytest.approx(100)
    assert longe["custo_restauracao_ha_p10"] >= 14000
    assert longe["desconto_linha_base_pct"] < 2
    assert longe["captura_tco2_ha_ano_p50"] == pytest.approx(588.8 / 40, abs=0.01)  # média dos 40 anos da URTX
    assert longe["teto_bioma_tco2_ha"] == 588.8 and longe["teto_bioma_publicado"]


def test_regra_por_pontos_usa_os_cinco_fatores():
    # pasto perto da mata, mas velho, com muito fogo e braquiária fechada: semeadura ou plantio, não regeneração
    m = R.modos(_linha(**{**PERTO, "mb_pasto_idade_anos_media": 35, "fogo_anos_media": 2.0,
                          "mb_pasto_vigor_principal": 3}))  # fmt: skip
    assert m["modo"] != "regeneracao_assistida"
    assert {f["fator"] for f in m["fatores"]} == {"idade_pasto", "vigor_pasto", "fogo_anos_media",
                                                  "declividade_media_pct"}  # fmt: skip
    # encosta íngreme soma ponto para a regeneração (e encarece o custo)
    plano = R.modos(_linha(pasto_d2_ha=100.0, pasto_d3_ha=0.0, fogo_anos_media=0.5))
    ingreme = R.modos(_linha(pasto_d2_ha=100.0, pasto_d3_ha=0.0, fogo_anos_media=0.5, declividade_media_pct=35))
    assert ingreme["pontos_imovel"] == plano["pontos_imovel"] + 1
    assert R.fator_custo(_linha(declividade_media_pct=35))[0] > R.fator_custo(_linha())[0]
    # área dividida por faixa: parte perto vira regeneração, o resto é plantio (a semeadura não tem custo oficial e
    # conta como plantio); os dois métodos disputam a fazenda pelo custo líquido por crédito
    misto = R.por_imovel(_linha(pasto_d0_ha=40.0, pasto_d3_ha=60.0, mb_pasto_idade_anos_media=8, fogo_anos_media=0.1))
    assert misto["modo_pela_regra"] in ("semeadura_direta", "plantio_total")
    assert misto["modo_restauracao"] == "regeneracao_assistida"  # 40 ha de regeneração baixam o custo por crédito
    assert misto["restauracao_regeneracao_assistida_ha"] == pytest.approx(40)
    assert misto["restauracao_plantio_total_ha"] == pytest.approx(60) and misto["restauracao_semeadura_direta_ha"] == 0
    assert misto["metodo_regeneracao_custo_credito"] < misto["metodo_plantio_custo_credito"]
    assert misto["custo_liquido_por_credito"] == misto["metodo_regeneracao_custo_credito"]


def test_ajustes_de_acesso_degradacao_chuva_e_solo():
    base = R.por_imovel(_linha())
    longe_da_estrada = R.por_imovel(_linha(estrada_acesso_km=30, cidade_proxima_km=150))
    assert longe_da_estrada["custo_restauracao_ha_p50"] > base["custo_restauracao_ha_p50"] * 1.2
    assert (
        R.por_imovel(_linha(mb_pasto_vigor_principal=1))["custo_restauracao_ha_p50"] > base["custo_restauracao_ha_p50"]
    )
    seco = R.por_imovel(_linha(chuva_mm_ano=1300))
    fertil = R.por_imovel(_linha(solo_cec_cmolc_kg=25))
    assert seco["captura_tco2_ha_ano_p50"] < base["captura_tco2_ha_ano_p50"]
    # o plantio na Amazônia já está no teto do bioma (588,8 t em 40 anos): solo fértil não passa dele
    assert fertil["captura_tco2_ha_ano_p50"] == base["captura_tco2_ha_ano_p50"]
    assert fertil["captura_fator_ajuste"] <= 1.10 + 1e-9  # solo mexe pouco (teto de 10%)
    regen = R.por_imovel(_linha(**PERTO))
    regen_fertil = R.por_imovel(_linha(**PERTO, solo_cec_cmolc_kg=25))
    assert regen_fertil["captura_tco2_ha_ano_p50"] > regen["captura_tco2_ha_ano_p50"]
    cerrado = R.por_imovel(_linha(bioma="Cerrado", chuva_mm_ano=1500))
    assert cerrado["captura_tco2_ha_ano_p50"] == pytest.approx(99.8 / 40, abs=0.01)  # teto do Cerrado


def test_sem_entrada_geografica_usa_premissa_neutra_e_diz_o_que_faltou():
    nua = {k: v for k, v in _linha().items() if not k.startswith(("pasto_d", "linha_base", "declividade", "chuva",
                                                                    "solo", "estrada", "cidade"))}  # fmt: skip
    c = R.por_imovel(nua)
    falta = set(c["restauracao_faltou"].split(","))
    assert {"distancia_mata", "declividade", "chuva", "solo", "acesso", "linha_base_municipio"} <= falta
    assert c["linha_base_fonte"] == "padrao" and c["modo_restauracao"] in R.regra()["modos"]
    b = R.bloco_ficha({**nua, **c})
    assert b["disponivel"] and {x["id"] for x in b["faltou"]} == falta


@settings(max_examples=60, deadline=None)
@given(
    d=st.lists(st.floats(0, 500), min_size=4, max_size=4),
    idade=st.floats(0, 40),
    fogo=st.floats(0, 3),
    vigor=st.sampled_from([1, 2, 3]),
    decl=st.floats(0, 80),
    alem=st.floats(0, 2000),
    pasto=st.floats(0, 2000),
)
def test_propriedades(d, idade, fogo, vigor, decl, alem, pasto):
    li = _linha(pasto_d0_ha=d[0], pasto_d1_ha=d[1], pasto_d2_ha=d[2], pasto_d3_ha=d[3], mb_pasto_idade_anos_media=idade,
                fogo_anos_media=fogo, mb_pasto_vigor_principal=vigor, declividade_media_pct=decl, alem_RL_ha=alem,
                pasto_ha=pasto)  # fmt: skip
    c = R.por_imovel(li)
    area = c["restauracao_area_ha"]
    assert area <= min(alem, pasto) + 1e-4  # arredondado a 4 casas
    assert sum(c[f"restauracao_{m}_ha"] for m in R.regra()["modos"]) == pytest.approx(area, abs=1e-3)
    for base in ("custo_restauracao_ha", "captura_tco2_ha_ano", "vpl_rs_ha", "tir_alavancada_pct"):
        assert c[f"{base}_p10"] <= c[f"{base}_p50"] <= c[f"{base}_p90"]
    assert 0 <= c["credito_liquido_tco2_ha_ano"] <= c["captura_tco2_ha_ano_p50"]
    assert 0 <= c["desconto_linha_base_pct"] <= 100


def test_lote_junta_pequenas_e_nao_descarta_nenhuma():
    pontos = [(f"P{i}", -47.0 + 0.002 * i, -2.0) for i in range(30)]  # 30 sítios pequenos lado a lado
    pontos += [("LONGE", -46.0, -2.0)]
    g = R.agrupar(pontos)
    assert set(g) == {p[0] for p in pontos}  # todo mundo tem lote
    assert len({g[f"P{i}"] for i in range(30)}) == 1 and g["LONGE"] != g["P0"]
    df = pd.DataFrame({"cod_imovel": list(g), "grupo_id": [f"X-{g[c]}" for c in g],
                       "restauracao_area_ha": [2.0] * 31, "credito_liquido_tco2_ano": [20.0] * 31})  # fmt: skip
    t = R.colunas_do_lote(df, 1, R.cenario()).set_index("cod_imovel")
    assert t.loc["P0", "grupo_imoveis"] == 30 and t.loc["P0", "grupo_ha"] == 60
    assert t.loc["P0", "grupo_creditos_prazo"] == 30 * 20 * 25 and not t.loc["P0", "grupo_fecha_contrato"]
    assert t.loc["P0", "grupo_ha_para_contrato"] == pytest.approx(1e6 / (10 * 25))
    # pequena entra no lote; quem tem embargo ou não tem área fica fora do lote, mas continua na lista
    assert R.elegivel(_linha(pasto_ha=1.5, alem_RL_ha=1.5))
    assert not R.elegivel(_linha(problema=True)) and not R.elegivel(_linha(filtro_territorial="bloqueio"))
    assert not R.elegivel(_linha(alem_RL_ha=0))


def test_contrato_de_um_milhao_pede_4_4_mil_ha_no_plantio_e_5_9_mil_na_regeneracao():
    longe, perto = R.por_imovel(_linha()), R.por_imovel(_linha(**PERTO))
    assert longe["ha_por_milhao_volume"] == pytest.approx(4400, rel=0.05)
    assert perto["ha_por_milhao_volume"] == pytest.approx(5900, rel=0.05)
    # os marcos intermediários pedem mais área que o volume do ano 25
    assert longe["ha_por_milhao_marcos"] > longe["ha_por_milhao_volume"]


def test_simulador_e_parametros_da_url():
    li = {**_linha(**PERTO), **R.por_imovel(_linha(**PERTO))}
    nome, muda = R.parametros_da_consulta({"preco_usd_t": "74", "juros_ano": "0,05", "forma_dono": "duas_fases"})
    assert nome is None and muda == {"preco_contrato_usd_t": 74.0, "juros_ano": 0.05, "forma_dono": "duas_fases"}
    assert R.parametros_da_consulta({"cenario": "estresse"}) == ("estresse", {})
    s74 = R.simular(li, preco_contrato_usd_t=74)
    s55 = R.simular(li)
    assert s74["vpl_rs_ha"]["p50"] > s55["vpl_rs_ha"]["p50"] and s74["cenario"]["preco_contrato_usd_t"] == 74
    assert len(s55["fluxo_p50"]["anos"]) == 41 and s55["aviso"]
    _, alu = R.parametros_da_consulta({"arrendamento_rs_ha_ano": "532"})  # nome antigo vira aluguel fixo ao dono
    assert alu == {"forma_dono": "aluguel_fixo", "aluguel_rs_ha_ano": 532.0}
    assert R.simular(li, **alu)["tir_alavancada_pct"]["p50"] < s55["tir_alavancada_pct"]["p50"]
    assert R.simular(li, "so_contrato_25")["tir_alavancada_pct"]["p50"] < s55["tir_alavancada_pct"]["p50"]
    for ruim in ({"preco_usd_t": "-1"}, {"fracao_financiada": "2"}, {"xyz": "1"}, {"entregas_anos": "7,12"},
                 {"cenario": "inexistente"}, {"forma_dono": "outra"}, {"metodo": "semeadura_direta"}):  # fmt: skip
        with pytest.raises(ValueError):
            R.parametros_da_consulta(dict(ruim))


def test_ficha_separa_faixas_e_avisa():
    li = {**_linha(**PERTO), **R.por_imovel(_linha(**PERTO))}
    b = R.bloco_ficha(li)
    assert b["disponivel"] and "Estimativa" in b["aviso"]
    assert b["modo"]["id"] == "regeneracao_assistida" and b["modo"]["nome"] == "Regeneração assistida"
    for k in ("custo_rs_ha", "captura_tco2_ha_ano", "credito_liquido_tco2_ha_ano", "vpl_rs_ha", "tir_alavancada_pct",
              "tir_projeto_pct", "custo_liquido_por_credito"):  # fmt: skip
        assert b[k]["p10"] <= b[k]["p50"] <= b[k]["p90"], k
    assert "viraria mata sozinho" in b["linha_base"]["explicacao"] and b["linha_base"]["cenario_pct"] == 20
    assert b["do_bruto_ao_liquido"]["ordem"] == ["linha_base", "vazamento", "reserva_risco", "incerteza"]
    assert "nenhuma vizinha" in b["do_bruto_ao_liquido"]["vazamento_situacao"]
    assert set(b["dono"]["tir_por_forma_pct"]) == {"parte_credito", "aluguel_fixo", "duas_fases"}
    assert b["metodos"]["regeneracao_assistida"]["tir_pct"] > b["metodos"]["plantio_total"]["tir_pct"]
    assert "SFB" in b["premissas"]["custo_plantio"] or "Bom Futuro" in b["premissas"]["custo_plantio"]
    assert b["premissas"]["versao"] == D.premissas()["versao_completa"]
    assert not R.bloco_ficha({"cod_imovel": "X"})["disponivel"]


def test_ordenar_e_filtrar_painel():
    lista = [
        {"cod_imovel": "A", "valor_desenvolvedor_rs": 10, "modo_restauracao": "plantio_total",
         "tir_alavancada_pct_p50": 12},
        {"cod_imovel": "B", "valor_desenvolvedor_rs": 50, "modo_restauracao": "regeneracao_assistida",
         "tir_alavancada_pct_p50": 35, "grupo_fecha_contrato": True},
        {"cod_imovel": "C"},  # ainda sem cálculo: vai para o fim, não some
    ]  # fmt: skip
    assert [x["cod_imovel"] for x in R.ordenar_filtrar(lista)] == ["A", "B", "C"]
    assert [x["cod_imovel"] for x in R.ordenar_filtrar(lista, "valor_desenvolvedor")] == ["B", "A", "C"]
    assert [x["cod_imovel"] for x in R.ordenar_filtrar(lista, modo="plantio_total")] == ["A"]
    assert [x["cod_imovel"] for x in R.ordenar_filtrar(lista, tir_min=30)] == ["B"]
    assert [x["cod_imovel"] for x in R.ordenar_filtrar(lista, so_lote_fecha=True)] == ["B"]
    with pytest.raises(ValueError):
        R.ordenar_filtrar(lista, "nome")


def test_versao_muda_com_as_premissas(tmp_path):
    a = tmp_path / "restauracao.yaml"
    pr = tmp_path / "premissas.yaml"
    shutil.copy(R.ARQ_REGRA, a)
    shutil.copy(R.ARQ_PREMISSAS, pr)
    v1 = R.regra(a, tmp_path / "nao_existe.yaml", pr)["versao_completa"]
    assert v1.startswith("restauracao-2026b+premissas-2026-11+")
    pr.write_text(pr.read_text(encoding="utf-8").replace("valor: 5.40", "valor: 5.10"), encoding="utf-8")
    assert R.regra(a, tmp_path / "nao_existe.yaml", pr)["versao_completa"] != v1


def test_cada_premissa_tem_fonte():
    r = R.regra()
    for k in ("regra_modo", "linha_base", "agrupamento"):
        assert r[k]["fonte"]
    for k in ("acesso", "declividade", "degradacao"):
        assert r["ajustes_custo"][k]["fonte"]
    for k in ("chuva", "solo"):
        assert r["ajustes_captura"][k]["fonte"]
    for nome in r["premissas"]["cenarios"]:
        f = R.fontes_cenario(nome)
        assert set(R.CENARIO_EDITAVEL) <= set(f), set(R.CENARIO_EDITAVEL) - set(f)


def test_municipio_da_amostra_sem_geo(tmp_path):
    pasta = tmp_path / "PA"
    pasta.mkdir()
    for f in AMOSTRA.glob("*_1504950.csv"):
        shutil.copy(f, pasta / f.name)
    t = R.calcular_municipio(pasta, 1504950, fontes_geo=())
    im = pd.read_csv(pasta / "imoveis_1504950.csv")
    assert len(t) == len(im) and set(t.cod_imovel) == set(im.cod_imovel.astype(str))  # ninguém sai
    assert set(t.modo_restauracao.dropna()) <= set(D.METODOS)
    assert (t.restauracao_versao == R.versao()).all()
    calc = t[t.restauracao_area_ha > 0]
    assert len(calc) and calc.custo_liquido_por_credito.notna().all() and calc.tir_desenvolvedor.notna().all()
    assert (calc.restauracao_area_ha < 5).any()  # sítio pequeno também tem conta
    # sem o ponto de cada imóvel não dá para procurar a vizinha: o vazamento fica no do cenário e diz por quê
    # ("cenario" é de quem não entra no lote, por embargo ou outro bloqueio)
    assert set(calc.vazamento_motivo) <= {"sem_ponto", "sem_gado", "sem_rebanho", "cenario"}
    assert (calc[calc.elegivel_lote].vazamento_motivo != "cenario").all()
    assert not t.astype(str).apply(lambda s: s.str.contains(r"\d{3}\.\d{3}\.\d{3}-\d{2}")).any().any()
    # cada coluna gravada está documentada em docs/colunas.md
    doc = (RAIZ / "docs" / "colunas.md").read_text(encoding="utf-8")

    def documentada(c: str) -> bool:  # aceita a forma curta x_p10/_p50/_p90
        base = c.rsplit("_p", 1)[0]
        return c in doc or (c[-4:] in ("_p10", "_p50", "_p90") and f"{base}_p10/_p50/_p90" in doc)

    faltam = [c for c in t.columns if not documentada(c)]
    assert not faltam, faltam


# --- entradas geográficas num raster sintético ------------------------------------------------------------------


def _raster(caminho, arr, x0=-47.0, y0=-2.0, res=0.00026949458523585647, dtype="uint8"):
    import rasterio
    from rasterio.transform import from_origin

    with rasterio.open(caminho, "w", driver="GTiff", width=arr.shape[1], height=arr.shape[0], count=1, dtype=dtype,
                       crs="EPSG:4326", transform=from_origin(x0, y0, res, res), nodata=0) as f:  # fmt: skip
        f.write(arr.astype(dtype), 1)


def test_faixas_de_distancia_e_linha_base_medida(tmp_path):
    import geopandas as gpd
    import shapely

    from raiz import restauracao_geo as G

    res = 0.00026949458523585647
    n = 400  # ~12 km de lado
    cob = np.full((n, n), 15, dtype="uint8")  # pasto
    cob[:, :40] = 3  # faixa de floresta a oeste (~1,2 km)
    idade = np.zeros((n, n), dtype="uint8")
    idade[:, 40:42] = 5  # rebrotou há 5 anos colado na mata (d0); não conta como mata-fonte
    idade[:200, 300:301] = 7  # um pouco longe da mata (d3)
    _raster(tmp_path / "cob.tif", cob)
    _raster(tmp_path / "idade.tif", idade)

    def caixa(c0, c1):
        return shapely.box(-47.0 + c0 * res, -2.0 - 300 * res, -47.0 + c1 * res, -2.0 - 100 * res)

    # a taxa da linha de base é medida na caixa de todos os imóveis do município (aqui, da mata até o LONGE)
    geo = gpd.GeoDataFrame({"cod_imovel": ["MATA", "PERTO", "LONGE"]},
                           geometry=[caixa(5, 30), caixa(42, 50), caixa(250, 350)], crs=4326)  # fmt: skip
    por, mun = G.faixas_e_linha_base(geo, tmp_path / "cob.tif", idade_url=str(tmp_path / "idade.tif"),
                                     pasta_tmp=tmp_path)  # fmt: skip
    assert por["PERTO"]["pasto_d0_ha"] > 0 and por["PERTO"]["pasto_d3_ha"] == 0
    assert por["LONGE"]["pasto_d3_ha"] > 0 and por["LONGE"]["pasto_d0_ha"] == 0
    assert mun["linha_base_fonte"].startswith("ybyra")
    assert mun["linha_base_taxa_d0"] > mun["linha_base_taxa_d3"] > 0
    # sem o YbYrá: faixas continuam, linha de base cai para a taxa padrão
    por2, mun2 = G.faixas_e_linha_base(geo, tmp_path / "cob.tif", idade_url=None, pasta_tmp=tmp_path)
    assert mun2 == {"linha_base_fonte": "padrao"} and por2["LONGE"]["pasto_d3_ha"] > 0
    perto = R.por_imovel(_linha(**{**por["PERTO"], **{k: v for k, v in mun.items() if k.startswith("linha_base")},
                                   "mb_pasto_idade_anos_media": 8, "fogo_anos_media": 0.1}))  # fmt: skip
    assert perto["modo_restauracao"] == "regeneracao_assistida"


def test_nome_do_ladrilho_do_copernicus():
    from raiz import restauracao_geo as G

    assert G.nome_ladrilho_dem(-2, -48) == ("S02", "W048")
    assert G.nome_ladrilho_dem(0, -50) == ("N00", "W050")
