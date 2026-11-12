"""Leitor WFS, assinatura barata e checagem HEAD, contra um GeoServer falso (sem rede)."""

import json

import httpx
import pytest
from sqlalchemy import create_engine, text

from raiz.coleta import wfs
from raiz.coleta.checagem import checar, checar_url, urls
from raiz.coleta.http import sessao
from raiz.coleta.manifesto import carregar
from raiz.operacao.healthchecks import Healthchecks
from testes.servidor_falso import sessao_falsa

URL = "https://geo.exemplo/geoserver/sicar/wfs"
CAMADA = wfs.Camada(URL, "sicar:sicar_imoveis_pa")


def _feicoes(n0, n, total):
    feats = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-47.3, -2.3]},
            "properties": {"cod_imovel": f"PA-1-{i:04d}", "data_atualizacao": f"2026-07-{1 + i % 28:02d}"},
        }
        for i in range(n0, n0 + n)
    ]
    return json.dumps({"type": "FeatureCollection", "features": feats, "numberMatched": total, "numberReturned": n})


def geoserver(total=25, mentir_total=False):
    def responder(metodo, base, p, h):
        if p.get("request") == "DescribeFeatureType":
            return (
                200,
                {},
                (
                    '<xsd:schema><xsd:element name="sicar_imoveis_pa" type="x"/>'
                    '<xsd:element name="cod_imovel" type="xsd:string"/>'
                    '<xsd:element name="data_atualizacao" type="xsd:dateTime"/></xsd:schema>'
                ),
            )
        if p.get("resultType") == "hits":
            return 200, {}, f'<wfs:FeatureCollection numberMatched="{total}" numberReturned="0"/>'
        if p.get("count") == "1" and p.get("sortBy") == "data_atualizacao DESC":
            assert p["propertyName"] == "data_atualizacao"
            if "IS NOT NULL" not in p["CQL_FILTER"]:  # como o servidor real: DESC põe o nulo primeiro
                return 200, {}, _feicoes(0, 1, total).replace('"2026-07-01"', "null")
            return 200, {}, _feicoes(0, 1, total).replace("2026-07-01", "2026-07-28")
        ini, qtd = int(p["startIndex"]), int(p["count"])
        assert p["sortBy"] == "cod_imovel" and p["CQL_FILTER"] == "cod_municipio_ibge=1504950"
        n = max(0, min(qtd, total - ini))
        return 200, {}, _feicoes(ini, n, total + (1 if mentir_total else 0))

    return responder


def test_assinatura_barata():
    s, srv = sessao_falsa(geoserver(25))
    cql = "cod_municipio_ibge=1504950"
    assert wfs.assinatura(s, CAMADA, "data_atualizacao", cql) == "25|2026-07-28"
    assert len(srv.pedidos) == 2  # só contagem + 1 linha: nada de baixar o município
    assert wfs.campos(s, CAMADA) == {"cod_imovel", "data_atualizacao"}


def test_paginas_com_ordem_e_conferencia():
    s, srv = sessao_falsa(geoserver(25))
    g = wfs.ler(s, CAMADA, "cod_imovel", "cod_municipio_ibge=1504950", pagina=10)
    assert len(g) == 25 and g.cod_imovel.is_unique and g.crs.to_epsg() == 4674
    assert [p[2]["startIndex"] for p in srv.pedidos] == ["0", "10", "20"]


def test_leitura_incompleta_falha():
    s, _ = sessao_falsa(geoserver(25, mentir_total=True))
    with pytest.raises(wfs.LeituraIncompleta, match="25 de 26"):
        wfs.ler(s, CAMADA, "cod_imovel", "cod_municipio_ibge=1504950", pagina=10)


def test_sessao_monta_tls_legado_e_cache(tmp_path):
    s = sessao(tls_legado=True, cache=True, pasta_cache=tmp_path)
    from raiz.coleta.http import AdaptadorTLSLegado

    assert isinstance(s.get_adapter("https://geoserver.car.gov.br"), AdaptadorTLSLegado)
    assert s.settings.allowable_codes == (200,)  # erro nunca fica no cache


def test_urls_do_manifesto():
    m = carregar()
    assert len(urls(m.fonte("gpw_pasto"))) == 2 and "{" not in urls(m.fonte("gpw_pasto"))[0]
    assert len(urls(m.fonte("geobr_territorios"))) == 3
    assert urls(m.fonte("sigmine")) == []  # sem endereço confirmado


def test_checar_url_sem_head():
    def r(metodo, base, p, h):
        if metodo == "HEAD":
            return 405, {}, ""
        assert h["Range"] == "bytes=0-0"
        return 206, {"Content-Range": "bytes 0-0/123456", "ETag": '"abc"'}, "x"

    s, _ = sessao_falsa(r)
    res = checar_url(s, "x", "https://arquivos.exemplo/a.tif")
    assert (res.status, res.bytes, res.etag) == (206, 123456, '"abc"')


@pytest.mark.banco
def test_checagem_avisa_mudanca_e_falta(banco_url):
    etag = {"v": '"1"'}

    def r(metodo, base, p, h):
        if "opengeohub" in base:
            return 403, {}, ""  # bucket fechado
        return 200, {"Content-Length": "100", "ETag": etag["v"], "Last-Modified": "Wed, 11 Nov 2026"}, ""

    s, _ = sessao_falsa(r)
    pings = []
    hc = Healthchecks(
        "k",
        "https://hc.exemplo",
        "raiz-{tarefa}",
        httpx.Client(
            transport=httpx.MockTransport(
                lambda req: pings.append((req.url.path, req.content.decode())) or httpx.Response(200)
            )
        ),
    )
    eng = create_engine(banco_url)
    with eng.begin() as c:
        c.execute(text("truncate coleta.checagem_http, coleta.evento"))
        primeira = checar(c, s, hc=hc)
        assert any(x.faltando for x in primeira) and not any(x.mudou for x in primeira)
        assert pings[-1][0] == "/k/raiz-checagem/fail" and "FALTA gpw_pasto" in pings[-1][1]
        etag["v"] = '"2"'
        segunda = checar(c, s, hc=hc)
        assert {x.fonte for x in segunda if x.mudou} == {
            "ibama_embargos",
            "ybyra_secundaria",
            "geobr_territorios",
            "jrc_tmf",
            "wri_causas_perda",
        }
        n = c.execute(text("select count(*) from coleta.evento where tipo = 'mudaram'")).scalar()
        assert n == sum(1 for x in segunda if x.mudou)
    eng.dispose()
