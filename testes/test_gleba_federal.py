"""Gleba pública federal não destinada (CNFP do SFB): mais de 10% do CAR sai do lote ou vira ressalva, conforme o modo.

Nunca corta por tamanho: a fração é do próprio CAR, pequeno ou grande. Sem medição (sem CNFP), nada é cortado e a
consulta e a triagem dizem "não medida"."""

import os
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
import shapely

from raiz import restauracao_catalogo as C
from raiz import restauracao_nacional as N
from raiz import restauracao_selecao as S
from raiz import terra as T
from raiz.pedidos.campos import CamposPedido
from raiz.triagem_desenvolvedor import nota as TN
from testes.test_restauracao_catalogo import criar_fonte, indexar


def test_limiar_de_dez_por_cento_e_nulo_sem_medicao():
    assert T.gleba_federal({"ha": 100, "terra_gleba_federal_ha": 10})["gleba_federal"] is False  # 10% não passa
    assert T.gleba_federal({"ha": 100, "terra_gleba_federal_ha": 10.5})["gleba_federal"] is True
    assert T.gleba_federal({"ha": 0.5, "terra_gleba_federal_ha": 0.2})["gleba_federal"] is True  # pequena conta igual
    assert T.gleba_federal({"ha": 100})["gleba_federal"] is None
    assert T.gleba_federal({"ha": 100, "terra_gleba_federal_ha": None})["gleba_federal_fracao"] is None


def _cnfp(tmp_path, governo):
    g = gpd.GeoDataFrame(
        {"nome": ["GLEBA X"], "tipo": ["B"], "governo": [governo], "categoria": ["GLEBA ARRECADADA"]},
        geometry=[shapely.box(-47.0, -3.0, -46.98, -2.98)],
        crs=4674,
    )
    f = tmp_path / f"cnfp_{governo}.parquet"
    g.to_parquet(f)
    return f


def test_so_gleba_federal_conta_e_sem_cnfp_fica_vazio(tmp_path):
    imoveis = gpd.GeoDataFrame(
        {"cod_imovel": ["PA-1-DENTRO", "PA-1-BORDA", "PA-1-FORA"]},
        geometry=[
            shapely.box(-47.0, -3.0, -46.99, -2.99),  # todo dentro
            shapely.box(-46.982, -3.0, -46.97, -2.99),  # ~17% dentro
            shapely.box(-46.9, -3.0, -46.89, -2.99),
        ],
        crs=4674,
    )
    caixa = tuple(imoveis.total_bounds)
    por = T.sobreposicoes(imoveis, None, T.camadas_de_terra(caixa, None, _cnfp(tmp_path, "FEDERAL")))
    ha = imoveis.to_crs(5880).area / 1e4
    fr = {c: por[c]["terra_gleba_federal_ha"] / h for c, h in zip(imoveis.cod_imovel, ha, strict=True)}
    assert fr["PA-1-DENTRO"] > 0.99 and 0.1 < fr["PA-1-BORDA"] < 0.3 and fr["PA-1-FORA"] == 0
    estadual = T.sobreposicoes(imoveis, None, T.camadas_de_terra(caixa, None, _cnfp(tmp_path, "ESTADUAL")))
    assert estadual["PA-1-DENTRO"]["terra_gleba_federal_ha"] == 0  # gleba estadual não é federal
    assert estadual["PA-1-DENTRO"]["terra_publica_ha"] > 0  # mas segue como terra pública
    sem = T.sobreposicoes(imoveis, None, T.camadas_de_terra(caixa, None, None))
    assert sem["PA-1-DENTRO"]["terra_gleba_federal_ha"] is None  # sem CNFP: não medido, nunca 0


def _fonte_com_gleba(pasta, fracoes):
    criar_fonte(pasta, n=len(fracoes))
    t = pd.read_csv(pasta / "terra_1500602.csv")
    t["terra_gleba_federal_ha"] = [None if f is None else 2.0 * f for f in fracoes]  # ha = 2.0 na fonte sintética
    t.to_csv(pasta / "terra_1500602.csv", index=False)
    return [f"PA-1500602-SINTETICO{i:04d}" for i in range(len(fracoes))]


def _consulta(tmp_path, cat, modo, nome):
    return N.montar_tres_opcoes(
        cat,
        CamposPedido(meta={"valor": 1_000_000}, cronograma="livre", gleba_federal=modo),
        N.normalizar_recorte(ufs=["PA"]),
        modelo="modelo-teste",
        cenario="central_r11",
        destino=tmp_path / nome,
        limites=S.LimitesSelecao(2, 10, 1),
    )


def test_lote_nacional_exclui_ou_marca_conforme_o_modo(tmp_path):
    ids = _fonte_com_gleba(tmp_path / "pa", [0.5, 0.05, 0.0, None])
    destino = tmp_path / "indice"
    p = indexar(tmp_path / "pa", destino)
    t = pd.read_parquet(destino / p["arquivos"]["oferta"]["caminho"]).set_index("cod_imovel")
    assert t.loc[ids[0], "gleba_federal"] and not t.loc[ids[1], "gleba_federal"]
    assert pd.isna(t.loc[ids[3], "gleba_federal"])
    cat = C.consolidar_catalogo([p], destino, municipios_esperados={"PA": [1500602]})
    ex = _consulta(tmp_path, cat, "excluir", "excluir")
    assert ex["gleba_federal"]["situacao"] == "parcial" and ex["gleba_federal"]["acima_do_limiar"] == 1
    for op in ex["opcoes"].values():
        assert ids[0] not in set(pd.read_parquet(op["tabela"]["caminho"]).cod_imovel)
        assert op["marcadas_gleba_federal"] == 0
    d = pd.read_parquet(ex["auditoria"]["caminho"]).set_index("cod_imovel")
    assert "gleba pública federal não destinada" in d.loc[ids[0], "criterio_texto"]
    res = _consulta(tmp_path, cat, "ressalva", "ressalva")
    assert res["gleba_federal"]["modo"] == "ressalva"
    escolhidas = [set(pd.read_parquet(op["tabela"]["caminho"]).cod_imovel) for op in res["opcoes"].values()]
    assert any(ids[0] in e for e in escolhidas)
    assert any(op["marcadas_gleba_federal"] == 1 for op in res["opcoes"].values())


def _linha_triagem(**kw):
    base = {"cod_imovel": "PA-1-A", "ha": 100.0, "custo_credito_usd": 9.0, "tir_alavancada_pct_p50": 14.0,
            "credito_liquido_tco2_ha_contrato_p50": 140.0, "caminho_terra": "privada_matricula",
            "risco_terra": "baixo", "status_sobreposicao": "livre"}  # fmt: skip
    return {**base, **kw}


def test_triagem_trava_ou_ressalva():
    livre = TN.avaliar(_linha_triagem(terra_gleba_federal_ha=0.0))
    assert livre["faixa"] == "recomendada" and livre["gleba_federal_pct"] == 0
    trava = TN.avaliar(_linha_triagem(terra_gleba_federal_ha=30.0))
    assert trava["faixa"] == "nao_segue" and "30% do CAR" in trava["motivo"] and trava["nota"] <= 30
    ressalva = TN.avaliar(_linha_triagem(terra_gleba_federal_ha=30.0), modo_gleba="ressalva")
    assert ressalva["faixa"] == "com_ressalvas" and "Ressalva" in ressalva["motivo"]
    sem = TN.avaliar(_linha_triagem())
    assert sem["faixa"] == "recomendada" and "gleba federal não medida" in sem["motivo"]
    with pytest.raises(ValueError):
        TN.avaliar(_linha_triagem(), modo_gleba="ignorar")


# Conferência com dados reais (17/11/2026): os dois imóveis de Paragominas que o fundador pediu para testar.
# Polígonos do Release `dados` (raiz_geo_PA.tar.gz, PA/geo_1505502.parquet) e CNFP 2025 do SFB
# (`raiz terra preparar-cnfp`). Roda só com os arquivos na máquina: dados grandes não entram no git.
GEO = os.environ.get("RAIZ_TESTE_GEO_PARAGOMINAS")
CNFP = Path(__file__).resolve().parents[1] / "dados" / "terra_publica" / "cnfp_PA.parquet"


@pytest.mark.skipif(not (GEO and Path(GEO).exists() and CNFP.exists()), reason="sem os dados reais de Paragominas")
def test_paragominas_d4386947_e_ce800c8a():
    g = gpd.read_parquet(GEO)
    s = g[g.cod_imovel.astype(str).str.contains("D4386947|CE800C8A")].to_crs(4674)
    assert len(s) == 2
    por = T.sobreposicoes(s, None, T.camadas_de_terra(tuple(s.total_bounds), None, CNFP))
    for c, area in zip(s.cod_imovel, s.to_crs(5880).area / 1e4, strict=True):
        gf = T.gleba_federal({"ha": area, **por[c]})
        # Nenhuma gleba federal não destinada do CNFP 2025 toca os dois CAR: ficam no lote.
        assert gf["gleba_federal"] is False and gf["gleba_federal_ha"] == 0
