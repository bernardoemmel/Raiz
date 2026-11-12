"""Fontes sem rede: o formato que cada uma devolve e a privacidade do Ibama."""

from __future__ import annotations

import datetime as dt
import io

import pandas as pd
import shapely
from shapely.geometry import box, mapping

from raiz.vigilancia.config import Config
from raiz.vigilancia.fontes import Contexto, data, ibama, inpe, mapbiomas_alerta, montar, so_area
from raiz.vigilancia.fontes import firms as firms_mod
from raiz.vigilancia.testes.conftest import CNPJ, CPF, HOJE, fmt_cnpj, fmt_cpf


def _ctx(regras, tmp_path, caixas=None):
    return Contexto(regras, Config(estado=tmp_path / "e", cache=tmp_path / "c"), HOJE, ["PA"], caixas or [])


def test_datas_das_fontes():
    assert data("2026-10-30T00:00:00Z") == dt.date(2026, 10, 30)
    assert data("20261016") == dt.date(2026, 10, 16)
    assert data("30/10/2026") == dt.date(2026, 10, 30)
    assert data(None) is None and data("") is None and data(float("nan")) is None


def test_so_area_tira_linha_solta_e_conserta_colecao():
    col = shapely.GeometryCollection([box(0, 0, 1, 1), shapely.LineString([(2, 2), (3, 3)])])
    assert so_area(col).geom_type == "Polygon"
    gravata = shapely.Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])  # se cruza
    g = so_area(gravata)
    assert g.is_valid and g.geom_type in ("Polygon", "MultiPolygon") and g.area > 0
    assert so_area(shapely.Point(1, 1)).geom_type == "Point"


def test_firms_pixel_classe_e_filtro_do_brasil(regras, tmp_path):
    csv = (
        "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,confidence,version,bright_ti5,frp,daynight\n"
        "-6.0,-53.0,330.1,0.40,0.37,2026-11-11,415,N20,h,2.0NRT,290,7.5,N\n"
        "-6.0,-53.0,320.0,0.40,0.37,2026-11-11,415,N21,nominal,2.0NRT,290,1.0,N\n"
        "-12.0,-76.5,320.0,0.40,0.37,2026-11-11,415,N21,low,2.0NRT,290,1.0,N\n"  # Peru: fora da caixa do Brasil
    )
    df = firms_mod._csv(csv, "N20")
    linhas = firms_mod.normalizar(df, _ctx(regras, tmp_path))
    assert len(linhas) == 2
    a = linhas[0]
    assert a["classe"] == "foco_alta" and a["chave"] == "N20|2026-11-11|0415|-6.00000|-53.00000"
    assert abs(a["area_ha"] - 14.8) < 0.1  # 400 m x 370 m
    assert linhas[1]["classe"] == "foco_nominal"
    assert "firms.modaps.eosdis.nasa.gov/map" in a["link"]
    # fora das caixas vigiadas não entra
    assert firms_mod.normalizar(df, _ctx(regras, tmp_path, caixas=[(-50, -10, -49, -9)])) == []


def test_deter_chave_composta_e_tipo(regras):
    feicoes = [
        {
            "type": "Feature",
            "geometry": mapping(box(-53.0, -6.0, -52.99, -5.99)),
            "properties": {
                "gid": "1_curr",
                "classname": "DESMATAMENTO_CR",
                "view_date": "2026-10-30",
                "mun_geocod": "1507300",
                "uf": "PA",
                "satellite": "AMAZONIA-1",
            },
        }
    ]
    linhas = inpe.normalizar_deter(inpe._gdf(feicoes), "deter-amz:deter_amz")
    a = linhas[0]
    assert a["classe"] == "desmatamento_cr" and a["data_evento"] == dt.date(2026, 10, 30)
    assert a["chave"].startswith("deter-amz:deter_amz|desmatamento_cr|2026-10-30|")
    assert "1_curr" not in a["chave"]  # o gid muda quando o mês fecha
    assert a["cod_municipio_ibge"] == 1507300 and a["publicado_em"] is None
    assert regras.tipo("deter", a["classe"]) == "desmatamento"


def test_prodes_estado_por_extenso_vira_sigla():
    assert inpe.uf_de("MATO GROSSO DO SUL") == "MS" and inpe.uf_de("Pará") == "PA" and inpe.uf_de("PARA") == "PA"
    assert inpe.uf_de("pa") == "PA" and inpe.uf_de("Atlântida") is None
    assert set(inpe._valores_uf(["PA"], True)) == {"PARÁ", "PARA"}
    feicoes = [
        {
            "type": "Feature",
            "geometry": mapping(box(-53.0, -6.0, -52.99, -5.99)),
            "properties": {
                "fid": 1,
                "state": "PARÁ",
                "main_class": "DESMATAMENTO",
                "year": 2026,
                "image_date": "2026-07-27",
                "uuid": "u1",
                "pub_date": "20261016",
            },
        }
    ]
    a = inpe.normalizar_prodes(inpe._gdf(feicoes), "prodes-cerrado-nb:yearly_deforestation", "state")[0]
    assert a["uf"] == "PA" and a["publicado_em"] == dt.date(2026, 10, 16) and a["chave"].endswith("|u1")


def test_mapbiomas_normaliza_car_e_status():
    itens = [
        {
            "alertCode": 1234,
            "areaHa": 3.5,
            "detectedAt": "2026-10-01",
            "publishedAt": "2026-11-05",
            "statusName": "published",
            "geometryWkt": box(-53.0, -6.0, -52.99, -5.99).wkt,
            "crossedStates": ["Pará"],
            "deforestationClasses": ["Agriculture"],
            "crossedRuralProperties": [{"code": "PA-1507300-X", "alertAreaInCar": 2.0}],
            "ruralPropertiesCodes": ["PA-1507300-X", "PA-1507300-Y"],
        },
        {"alertCode": 9, "geometryWkt": None},
    ]
    linhas = mapbiomas_alerta.normalizar(itens)
    assert len(linhas) == 1
    a = linhas[0]
    assert a["chave"] == "1234" and a["uf"] == "PA" and a["classe"] == "agriculture"
    assert a["car_fonte"] == {"PA-1507300-X": 2.0, "PA-1507300-Y": None}
    assert a["link"].endswith("/alerta/1234") and a["atributos"]["status"] == "published"
    assert len(montar(linhas)) == 1


def test_mapbiomas_sem_credencial(regras, tmp_path, monkeypatch):
    monkeypatch.delenv("MAPBIOMAS_ALERTA_EMAIL", raising=False)
    monkeypatch.delenv("MAPBIOMAS_ALERTA_SENHA", raising=False)
    try:
        mapbiomas_alerta.entrar("http://nao-usado")
    except mapbiomas_alerta.SemCredencial:
        return
    raise AssertionError("devia pedir credencial")


CSV_IBAMA = (
    '"SEQ_TAD";"NOME_EMBARGADO";"CPF_CNPJ_EMBARGADO";"NUM_TAD";"SIT_CANCELADO";"DAT_EMBARGO";"NUM_PROCESSO";'
    '"COD_MUNICIPIO";"UF";"NUM_LONGITUDE_TAD";"NUM_LATITUDE_TAD";"QTD_AREA_EMBARGADA";"GEOM_AREA_EMBARGADA";'
    '"SIT_DESEMBARGO";"DAT_ULT_ALTERACAO";"NOME_IMOVEL";"DES_TAD"\n'
    f'"1";"PESSOA_A";"{fmt_cpf(CPF)}";"A1";"N";"01/03/2024";"02018.000001/2024-11";"1507300";"PA";"-53,0";"-6,0";'
    '"10,5";"POLYGON ((-53 -6, -52.99 -6, -52.99 -5.99, -53 -5.99, -53 -6))";"N";"01/03/2024";"IMOVEL_X";'
    f'"autuado {CPF}"\n'
    f'"2";"EMPRESA_B";"{fmt_cnpj(CNPJ)}";"A2";"S";"01/03/2024";"";"1507300";"PA";"-53,0";"-6,0";"";"";"N";'
    '"10/11/2026";"";""\n'
    '"3";"PESSOA_C";"";"A3";"N";"05/05/2025";"";"1507300";"PA";"-53,1";"-6,1";"";"";"N";"05/05/2025";"";""\n'
)


def test_ibama_sem_dado_pessoal_e_espelho(regras, tmp_path):
    caminho = tmp_path / "termo.csv"
    caminho.write_text("﻿" + CSV_IBAMA, encoding="utf-8")
    df = ibama.ler_csv(caminho)
    assert not {"NOME_EMBARGADO", "CPF_CNPJ_EMBARGADO", "NOME_IMOVEL", "DES_TAD"} & set(df.columns)
    tudo = df.to_csv()
    assert "PESSOA_A" not in tudo and fmt_cpf(CPF) not in tudo and CPF not in tudo and "IMOVEL_X" not in tudo
    esp = ibama.espelho(df)
    assert esp.set_index("seq_tad").loc["2", "cancelado"] and not esp.set_index("seq_tad").loc["1", "cancelado"]
    oc = ibama.ocorrencias(df, _ctx(regras, tmp_path))
    assert set(oc["chave"]) == {"1", "3"}  # o cancelado não entra
    por = oc.set_index("chave")
    assert por.loc["1", "classe"] == "embargo" and por.loc["1", "area_ha"] == 10.5
    assert por.loc["3", "classe"] == "embargo_ponto" and por.loc["3", "geometry"].geom_type == "Point"
    assert por.loc["1", "data_evento"] == dt.date(2024, 3, 1)


def test_ibama_so_o_que_mudou(regras, tmp_path, monkeypatch):
    caminho = tmp_path / "termo.csv"
    caminho.write_text(CSV_IBAMA, encoding="utf-8")
    df = ibama.ler_csv(caminho)
    antigo = ibama.espelho(df)
    antigo.loc[antigo.seq_tad == "2", "cancelado"] = False  # na leitura anterior, o 2 ainda não estava cancelado
    limpo = tmp_path / "c" / "ibama" / "termo_de_embargo_limpo.parquet"
    limpo.parent.mkdir(parents=True)
    df.to_parquet(limpo)
    monkeypatch.setattr(ibama, "baixar_limpo", lambda url, limpo, etag: True)
    leitura = ibama.ler(_ctx(regras, tmp_path), {}, antigo)
    assert len(leitura.ocorrencias) == 0  # nada novo nem alterado entre os ativos
    assert leitura.extras["cancelados"] == {"2"}
    tudo = ibama.ler(_ctx(regras, tmp_path), {}, antigo, refazer=True)  # polígonos mudaram: cruza todos os ativos
    assert set(tudo.ocorrencias["chave"]) == {"1", "3"}


def test_baixar_limpo_nao_deixa_o_bruto(regras, tmp_path, monkeypatch):
    class Resp:
        status_code = 200
        headers = {"ETag": "abc"}

        def iter_content(self, n):
            yield CSV_IBAMA.encode("utf-8")

    monkeypatch.setattr(ibama.rede, "pedir", lambda *a, **k: Resp())
    limpo = tmp_path / "ibama" / "limpo.parquet"
    limpo.parent.mkdir()
    assert ibama.baixar_limpo("http://x", limpo, tmp_path / "ibama" / "etag")
    arquivos = [p.name for p in (tmp_path / "ibama").iterdir()]
    assert sorted(arquivos) == ["etag", "limpo.parquet"]
    assert "PESSOA_A" not in pd.read_parquet(limpo).to_csv()
    assert io.BytesIO(limpo.read_bytes()).getbuffer().nbytes > 0
