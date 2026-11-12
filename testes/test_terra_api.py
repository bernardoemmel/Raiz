"""Caminho da terra no banco e na API: imóvel sem matrícula continua no mapa com caminho e risco; nenhum imóvel some
do total do município por causa da terra; ficha com o aviso do que falta; camada de terra pública para restaurar."""

import datetime as dt
import shutil

import geopandas as gpd
import pandas as pd
import pytest
import shapely
from sqlalchemy import create_engine, text

from raiz import terra as T
from testes.conftest import AMOSTRA

pytestmark = pytest.mark.banco
COD = 1504950


@pytest.fixture(scope="module")
def cliente(banco_url, tmp_path_factory):
    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    import raiz.api as api_mod
    from raiz import terra_publica as TP
    from raiz.api import criar_app
    from raiz.carga import carregar_municipio

    base = tmp_path_factory.mktemp("terra")
    pasta = base / "PA"
    pasta.mkdir()
    for f in ("imoveis", "filtros"):
        shutil.copy(AMOSTRA / f"{f}_{COD}.csv", pasta / f"{f}_{COD}.csv")
    T.calcular_municipio(pasta, COD).to_csv(pasta / f"terra_{COD}.csv", index=False)
    eng = create_engine(banco_url)
    with eng.begin() as c:
        c.execute(text("truncate funil.rodada, funil.imovel, funil.vigente, funil.municipio_busca, geo.camada cascade"))
        c.execute(text("truncate geo.terra_publica"))
        carregar_municipio(c, pasta, COD, dt.date(2026, 11, 12))
        # divisa do município para recortar a terra pública
        c.execute(text("""insert into geo.camada (cod_ibge, camada, propriedades, geom) values
                          (:c, 'municipio', '{}', ST_Multi(ST_MakeEnvelope(-47.5, -2.5, -47.0, -2.0, 4674)))"""),
                  {"c": COD})  # fmt: skip
    area = gpd.GeoDataFrame(
        {"id": ["PA-cnfp-teste"], "uf": ["PA"], "fonte": ["cnfp"], "nome": ["GLEBA TESTE"],
         "destinacao": ["sem_destinacao"], "categoria": ["GLEBA ARRECADADA"], "esfera": ["Estadual"],
         "orgao": ["ITERPA"], "tradicional": [False], "ha": [1000.0], "desmatado_ha": [400.0], "pasto_ha": [380.0],
         "mata_ha": [600.0], "modo_restauracao": ["plantio_total"], "credito_liquido_tco2_ano": [3900.0],
         "custo_restauracao_ha_p50": [20000.0], "concessao": [None]},
        geometry=[shapely.box(-47.3, -2.3, -47.2, -2.2)], crs=4674)  # fmt: skip
    arq = base / "terra_publica_PA.parquet"
    area.to_parquet(arq)
    TP.carregar(eng, arq)
    cfg = type("C", (), {"api_token": SecretStr("t"), "api_origens": ""})()
    mp = pytest.MonkeyPatch()
    mp.setattr(api_mod, "config", lambda: cfg)
    app = criar_app(engine=eng, grafo=object(), deps=object(), whatsapp=False)
    with TestClient(app, headers={"Authorization": "Bearer t"}) as cl:
        yield cl, pasta
    mp.undo()
    eng.dispose()


def test_imovel_sem_matricula_continua_no_mapa_com_caminho_e_risco(cliente):
    cl, pasta = cliente
    im = pd.read_csv(pasta / f"imoveis_{COD}.csv", low_memory=False)
    lista = cl.get(f"/municipios/{COD}/imoveis").json()
    assert len(lista) == len(im)  # todos no mapa
    assert all(x.get("caminho_terra") in T.CAMINHOS and x.get("risco_terra") in T.RISCOS for x in lista)
    sem = [x for x in lista if (x.get("f_matricula") or 0) == 0]
    assert sem and all(x["caminho_terra"] != "privada_matricula" for x in sem)
    alvo = sem[0]["cod_imovel"]
    f = cl.get(f"/imoveis/{alvo}/ficha").json()
    b = f["caminho_terra"]
    assert b["caminho"] == sem[0]["caminho_terra"] and b["risco"] in T.RISCOS and b["risco_motivo"]
    if b["caminho"] in ("posse_em_titulacao", "assentamento", "publica_sem_destinacao"):
        assert b["aviso"]  # o que falta, sem tela em branco
    crit = {c["id"]: c for c in f["criterios_aptidao"]}
    assert crit["caminho_terra"]["grupo"] == "só informa"  # a terra não decide a aptidão
    assert f["nivel_selo"] == "bronze"


def test_nenhum_imovel_some_do_total_do_municipio_por_causa_da_terra(cliente):
    cl, pasta = cliente
    im = pd.read_csv(pasta / f"imoveis_{COD}.csv", low_memory=False)
    d = cl.get(f"/municipios/{COD}").json()
    e = {x["etapa"]: x for x in d["funil"]["etapas"]}
    assert e["cadastro"]["imoveis"] == len(im)
    assert e["caminho_terra"]["imoveis"] == e["apta"]["imoveis"]  # toda apta tem caminho, ninguém corta
    ct = d["funil"]["caminho_terra"]
    assert sum(x["imoveis"] for x in ct["caminhos"].values()) == e["caminho_terra"]["imoveis"]
    assert sum(x["imoveis"] for x in ct["situacoes"].values()) == e["caminho_terra"]["imoveis"]
    assert ct["situacoes"]["em_espera"]["imoveis"] > 0
    assert "pronta agora" in d["frase"] and "em espera" in d["frase"]


def test_terra_publica_para_restaurar(cliente):
    cl, _ = cliente
    r = cl.get("/terra-publica", params={"uf": "pa"}).json()
    assert r["uf"] == "PA" and r["areas"][0]["id"] == "PA-cnfp-teste" and r["areas"][0]["desmatado_ha"] == 400
    assert "não se origina com particular" in r["regra"]
    assert cl.get("/terra-publica", params={"uf": "RO"}).status_code == 404
    assert cl.get("/terra-publica", params={"uf": "PA", "ordem": "x"}).status_code == 422
    fc = cl.get(f"/geo/{COD}/terra_publica.geojson").json()
    assert fc["features"] and fc["features"][0]["properties"]["nome"] == "GLEBA TESTE"
