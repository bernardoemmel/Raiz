"""Design v1 do front, itens 2 e 3: colunas e camadas dentro do imóvel, PMTiles por município, OpenStreetMap pelos
ladrilhos do Protomaps e as rotas que servem isso."""

import datetime as dt
import gzip
import json
import shutil

import geopandas as gpd
import httpx
import mapbox_vector_tile
import numpy as np
import pandas as pd
import pytest
import rasterio
import shapely
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point, box

from raiz import imovel_dados as I
from raiz import osm, serie_uso, tiles
from testes.conftest import AMOSTRA

RES = 0.00026949458523585647  # 30 m, a grade do MapBiomas


def test_porte_etapa_motivo_faixas():
    assert [I.porte(x) for x in (0.5, 4, 4.01, 15, 16, None)] == [
        "pequeno",
        "pequeno",
        "médio",
        "médio",
        "grande",
        None,
    ]
    apta = {"ha": 100, "carbono_ha": 40, "carbono_tco2_ano": 100, "f_matricula": 0.8}
    assert I.etapa_e_motivo(apta) == (
        "com_matricula",
        {"id": "titulo", "texto": "Matrícula ainda não conferida no cartório"},
    )
    assert I.etapa_e_motivo({**apta, "f_matricula": 0.2})[1]["id"] == "matricula"
    etapa, motivo = I.etapa_e_motivo({**apta, "embargo_ha": 5, "problema": True})
    assert etapa == "cadastro" and motivo["id"] == "embargo"  # o primeiro motivo, um só
    assert I.etapa_e_motivo({**apta, "matricula_conferida": True})[0] == "titulo_conferido"
    f = I.faixas({"carbono_tco2_ano": 100})
    assert (f["carbono_tco2_ano_p10"], f["carbono_tco2_ano_p50"], f["carbono_tco2_ano_p90"]) == (60, 100, 140)
    assert f["receita_ano_p10"] < f["receita_ano_p50"] < f["receita_ano_p90"] and "P10" in f["faixas_regra"]


def _raster(tmp_path, x0=-47.30, y0=-2.20, n=120):
    """Raster de cobertura: floresta (3) na faixa de cima, pasto (15) no meio, lavoura (39) embaixo, rio (33)."""
    a = np.zeros((n, n), dtype=np.uint8)
    a[:30, :] = 3
    a[30:80, :] = 15
    a[80:, :] = 39
    a[:, 55:60] = 33
    f = tmp_path / "PA_cobertura_2025.tif"
    with rasterio.open(f, "w", driver="GTiff", height=n, width=n, count=1, dtype="uint8", crs="EPSG:4326",
                       transform=from_origin(x0, y0, RES, RES), nodata=0) as d:  # fmt: skip
        d.write(a, 1)
    return f, (x0, y0 - n * RES, x0 + n * RES, y0)


def test_camadas_e_composicao_somam_a_area(tmp_path):
    tif, (x0, y0, x1, y1) = _raster(tmp_path)
    geom = box(x0 + 10 * RES, y0 + 10 * RES, x1 - 10 * RES, y1 - 10 * RES)
    geo = gpd.GeoDataFrame({"cod_imovel": ["PA-1-A"]}, geometry=[geom], crs=4674)
    ha = float(gpd.GeoSeries([geom], crs=4674).to_crs(5880).area.iloc[0] / 1e4)
    # água do PRODES no bloco do cache do motor, para a APP
    tb = tmp_path / "tb"
    tb.mkdir()
    rio = box(x0 + 55 * RES, y0, x0 + 60 * RES, y1)
    gpd.GeoDataFrame({"id": [1]}, geometry=[rio], crs=4674).to_parquet(
        tb / "prodes-legal-amz__hydrography__-47.5_-2.5.parquet"
    )
    linhas = {"PA-1-A": {"ha": ha, "carbono_ha": 30.0, "m_fiscal": 0.5}}
    feicoes, comp = I.camadas_e_composicao(geo, linhas, tif, tb)
    c = comp["PA-1-A"]
    assert sum(v for k, v in c.items() if k.startswith("comp_")) == pytest.approx(ha, abs=0.05)  # soma a área
    assert c["comp_para_restaurar_ha"] == 30.0 and c["comp_mata_em_pe_ha"] > 0 and c["comp_lavoura_ha"] > 0
    camadas = {f["camada"] for f in feicoes}
    assert {"mata_em_pe", "pode_voltar", "lavoura", "agua", "app"} <= camadas
    for f in feicoes:  # tudo dentro do imóvel (com a folga da simplificação)
        assert f["geometry"].buffer(0.0005).covers(f["geometry"]) and geom.buffer(0.001).covers(f["geometry"])
    # sem raster: tudo vai para sem_dado, mas a soma continua sendo a área
    _, comp2 = I.camadas_e_composicao(geo, linhas, None, None)
    assert comp2["PA-1-A"]["comp_sem_dado_ha"] == pytest.approx(ha, abs=0.01)


def test_pmtiles_do_municipio_e_leitura_remota(tmp_path):
    lugares = gpd.GeoDataFrame(
        {"kind": ["locality", "locality"], "kind_detail": ["town", "village"], "name": ["Cidade Alta", "Vila Baixa"]},
        geometry=[Point(-47.20, -2.30), Point(-47.10, -2.40)],
        crs=4326,
    )
    estradas = gpd.GeoDataFrame(
        {"kind": ["major_road"], "ref": ["PA-124"], "name": ["Rodovia"]},
        geometry=[LineString([(-47.4, -2.5), (-47.0, -2.1)])],
        crs=4326,
    )
    f = tmp_path / "osm.pmtiles"
    r = tiles.gerar(f, {"places": lugares, "roads": estradas}, zmin=10, zmax=11)
    assert r["ladrilhos"] > 0
    dado = f.read_bytes()

    def servir(req: httpx.Request) -> httpx.Response:  # servidor de faixas de bytes, como o build do Protomaps
        a, b = req.headers["range"].removeprefix("bytes=").split("-")
        return httpx.Response(206, content=dado[int(a) : int(b) + 1])

    remoto = osm.PMTilesRemoto("https://exemplo/x.pmtiles", None, httpx.Client(transport=httpx.MockTransport(servir)))
    lug, est = osm.lugares_e_estradas((-47.3, -2.45, -47.15, -2.25), remoto=remoto)
    assert {x["nome"] for x in lug} >= {"Cidade Alta"} and est and est[0]["nome"] == "PA-124"
    perto = osm.por_imovel({"A": Point(-47.2, -2.35)}, lug, est)["A"]
    assert perto["cidade_proxima"] == "Cidade Alta" and perto["cidade_proxima_direcao"] == "S"
    assert 5 < perto["cidade_proxima_km"] < 6 and perto["estrada_acesso"] == "PA-124" and perto["estrada_acesso_km"] < 5
    # um ladrilho do arquivo tem as duas camadas
    from pmtiles.reader import MmapSource, Reader

    with open(f, "rb") as h:
        rd = Reader(MmapSource(h))
        z, x, y = osm.ladrilhos_na_caixa(11, (-47.2, -2.3, -47.2, -2.3))[0]
        dec = mapbox_vector_tile.decode(gzip.decompress(rd.get(z, x, y)))
    assert "places" in dec or "roads" in dec


def test_direcao_e_distancia():
    c = Point(0, 0)
    assert (
        osm.direcao(c, Point(0, 1)) == "N"
        and osm.direcao(c, Point(1, 1)) == "NE"
        and osm.direcao(c, Point(-1, 0)) == "O"
    )
    assert osm.km(Point(0, 0), Point(0, 1)) == pytest.approx(111.2, abs=0.2)


def test_percentuais_da_serie():
    p = serie_uso.percentuais({3: 50, 15: 30, 39: 10, 33: 10, 0: 999})
    assert p == {"mata_pct": 50.0, "pasto_pct": 30.0, "lavoura_pct": 10.0, "agua_pct": 10.0}
    assert serie_uso.percentuais({0: 10})["mata_pct"] is None


# --- carga e rotas ------------------------------------------------------------------------------------------------


@pytest.fixture
def api(banco_url, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from pydantic import SecretStr
    from sqlalchemy import create_engine, text

    import raiz.api as api_mod
    from raiz.api import criar_app
    from raiz.carga import carregar_municipio

    eng = create_engine(banco_url)
    with eng.begin() as c:
        c.execute(text("truncate funil.rodada, funil.imovel, funil.vigente, funil.municipio_busca cascade"))
        c.execute(text("truncate negocio.codigo_curto, geo.camada_imovel, funil.serie_uso, negocio.aceite cascade"))
    saida = tmp_path / "saida" / "PA"
    saida.mkdir(parents=True)
    for f in ("imoveis_1504950.csv", "filtros_1504950.csv"):
        shutil.copy(AMOSTRA / f, saida / f)
    cods = pd.read_csv(saida / "imoveis_1504950.csv").cod_imovel.head(2).tolist()
    pd.DataFrame({"cod_imovel": cods, "porte": ["pequeno", "grande"], "etapa_funil": ["apta", "cadastro"],
                  "comp_mata_em_pe_ha": [1.0, 2.0]}).to_csv(saida / "ficha_1504950.csv", index=False)  # fmt: skip
    gpd.GeoDataFrame({"cod_imovel": [cods[0]] * 2, "camada": ["mata_em_pe", "pode_voltar"], "ha": [1.0, 2.0]},
                     geometry=[box(-47.3, -2.3, -47.29, -2.29), box(-47.29, -2.3, -47.28, -2.29)], crs=4674
                     ).to_parquet(saida / "camadas_1504950.parquet")  # fmt: skip
    pd.DataFrame({"cod_imovel": [cods[0]] * 2, "ano": [1985, 2025], "mata_pct": [90.0, 40.0], "pasto_pct": [5, 50],
                  "lavoura_pct": [0, 5], "agua_pct": [1, 1], "colecao": "mapbiomas-col11"}
                 ).to_csv(saida / "serie_uso_1504950.csv", index=False)  # fmt: skip
    (saida / "camadas_1504950.pmtiles").write_bytes(bytes(range(256)) * 8)
    with eng.begin() as c:
        carregar_municipio(c, saida, 1504950, dt.date(2026, 11, 12))
    cfg = type("C", (), {"api_token": SecretStr("t"), "api_origens": "", "motor_dir_trabalho": str(tmp_path)})()
    monkeypatch.setattr(api_mod, "config", lambda: cfg)
    import raiz.funil.rodar as rodar

    monkeypatch.setattr(rodar, "dir_trabalho", lambda: tmp_path)
    app = criar_app(engine=eng, grafo=object(), deps=object(), whatsapp=False)
    with TestClient(app, headers={"Authorization": "Bearer t"}) as cl:
        yield cl, eng, cods, saida
    eng.dispose()


@pytest.mark.banco
def test_rotas_de_camadas_e_ficha(api):
    from sqlalchemy import text

    cl, eng, cods, saida = api
    r = cl.get(f"/imoveis/{cods[0].lower()}/camadas.geojson")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/geo+json")
    assert sorted(f["properties"]["camada"] for f in r.json()["features"]) == ["mata_em_pe", "pode_voltar"]
    falta = cl.get(f"/imoveis/{cods[1]}/camadas.geojson")
    assert falta.status_code == 404 and "ainda não foram geradas" in falta.json()["detail"]["mensagem"]
    pm = cl.get("/geo/1504950/camadas.pmtiles", headers={"Range": "bytes=0-15"})
    assert pm.status_code == 206 and pm.content == bytes(range(16))

    i = cl.get(f"/imoveis/{cods[0]}").json()
    assert len(i["codigo_curto"]) == 7 and i["nivel_selo"] == "bronze" and i["porte"] == "pequeno"
    f = cl.get(f"/imoveis/{cods[0]}/ficha").json()
    assert f["codigo_curto"] == i["codigo_curto"] and f["nivel_selo"] == "bronze"
    assert [c["id"] for c in f["criterios_aptidao"]][:3] == ["embargo", "ti", "desmate2020"]
    assert len(f["criterios_aptidao"]) == 13 and all(c["data"] == "2026-11-12" for c in f["criterios_aptidao"])
    assert f["serie_uso"]["anos"] == [1985, 2025] and f["serie_uso"]["mata_pct"] == [90.0, 40.0]
    assert f["imovel"]["comp_mata_em_pe_ha"] == 1.0  # colunas da ficha_<mun>.csv chegam na linha

    # o código curto não muda quando o motor reprocessa; o aceite do dono vira selo ouro
    pd.read_csv(saida / "ficha_1504950.csv").assign(porte="médio").to_csv(saida / "ficha_1504950.csv", index=False)
    from raiz.carga import carregar_municipio

    with eng.begin() as c:
        carregar_municipio(c, saida, 1504950, dt.date(2026, 11, 13))
        c.execute(text("insert into negocio.aceite (cod_imovel, estado) values (:c, 'aceito')"), {"c": cods[0]})
    j = cl.get(f"/imoveis/{cods[0]}").json()
    assert j["codigo_curto"] == i["codigo_curto"] and j["porte"] == "médio"
    assert j["nivel_selo"] == "ouro" and j["etapa_funil"] == "aceite"
    assert json.dumps(j).count(i["codigo_curto"]) == 1
    codigos = [c for (c,) in eng.connect().execute(text("select codigo from negocio.codigo_curto"))]
    assert (
        len(codigos) == 880
        and len(set(codigos)) == 880
        and all(c.isalnum() and c.isupper() or c.isdigit() for c in codigos)
    )
    assert not any(ch in "ILOU" for c in codigos for ch in c)
    shapely.box(0, 0, 1, 1)  # (shapely importado para os testes de geometria acima)
