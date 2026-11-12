"""API do front (raiz/front_api.py) contra o banco de teste com a amostra: rotas, nomes de coluna dos CSV, funil igual
ao resumo do motor, ficha com perímetro em polyline, certidões, camadas, mapa base com Range e máscara de CPF/CNPJ."""

import datetime as dt
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from raiz import front_api
from raiz.api import criar_app
from raiz.carga import carregar_pasta
from testes.conftest import AMOSTRA
from testes.test_privacidade import CPF, fmt_cpf

COD = 1504950
TOKEN = "token-de-teste"


def test_polyline_igual_ao_algoritmo_do_google():
    # exemplo da documentação do algoritmo (5 casas), pares [lon, lat] como no front
    pontos = [(-120.2, 38.5), (-120.95, 40.7), (-126.453, 43.252)]
    assert front_api.polyline(pontos, 5) == "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
    assert front_api.mediana([3, 1, 2]) == 2 and front_api.mediana([4, 1, 2, 3]) == 2.5 and front_api.mediana([]) == 0


@pytest.fixture(scope="module")
def cliente(banco_url, tmp_path_factory):
    eng = create_engine(banco_url)
    with eng.begin() as c:
        c.execute(text("truncate funil.rodada, funil.imovel, geo.camada cascade"))
    carregar_pasta(eng, AMOSTRA, dt.date(2026, 11, 12))
    with eng.begin() as c:
        alvo = c.execute(text("select min(cod_imovel) from funil.resultado_imovel where cod_imovel like 'PA-1504950%'"))
        alvo = alvo.scalar()
        c.execute(
            text("""update funil.imovel set geom = ST_Multi(ST_GeomFromText(
                    'POLYGON((-47.30 -2.30, -47.29 -2.30, -47.29 -2.29, -47.30 -2.29, -47.30 -2.30))', 4674))
                    where cod_imovel = :c"""),
            {"c": alvo},
        )
        # um CPF que escapou num texto do motor tem de sair mascarado
        c.execute(
            text("""update funil.complemento_imovel
                    set atributos = atributos || jsonb_build_object('nota', cast(:n as text))
                    where cod_imovel = :c"""),
            {"c": alvo, "n": f"dono {fmt_cpf(CPF)}"},
        )
    pasta = tmp_path_factory.mktemp("geo")
    divisa = {"type": "Polygon", "coordinates": [[[-47.5, -2.5], [-47.0, -2.5], [-47.0, -2.0], [-47.5, -2.5]]]}
    (pasta / f"municipio_{COD}.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"cod_ibge": str(COD), "nome": "Nova Esperança do Piriá"},
                        "geometry": divisa,
                    }
                ],
            }
        )  # fmt: skip
    )
    (pasta / f"base_{COD}.pmtiles").write_bytes(bytes(range(256)) * 4)
    from raiz.geo import carregar

    with eng.begin() as c:
        assert carregar(c, COD, pasta) == {"municipio": 1}
    cfg = type("C", (), {"api_token": SecretStr(TOKEN), "api_origens": "http://localhost:5173"})()
    import raiz.api as api_mod
    import raiz.geo as geo_mod

    mp = pytest.MonkeyPatch()
    mp.setattr(api_mod, "config", lambda: cfg)
    mp.setattr(geo_mod, "pasta_geo", lambda: pasta)
    app = criar_app(engine=eng, grafo=object(), deps=object(), whatsapp=False)  # com a config de teste (CORS)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as cl:
        yield cl, alvo
    mp.undo()
    eng.dispose()


@pytest.mark.banco
def test_token_obrigatorio(cliente):
    cl, _ = cliente
    assert cl.get("/municipios", headers={"Authorization": "Bearer errado"}).status_code == 401


@pytest.mark.banco
def test_municipios_com_nomes_do_csv(cliente):
    cl, _ = cliente
    ms = cl.get("/municipios").json()
    resumo = pd.read_csv(AMOSTRA / "resumo_PA.csv")
    assert len(ms) == len(resumo) and {m["uf"] for m in ms} == {"PA"}
    m = next(x for x in ms if x["cod_ibge"] == COD)
    assert "def_RL" in m and "frente_carbono" in m  # maiúsculas do CSV e coluna sem contrato (atributos)


@pytest.mark.banco
def test_imoveis_e_funil_igual_ao_resumo(cliente):
    cl, _ = cliente
    lista = cl.get(f"/municipios/{COD}/imoveis").json()
    df = pd.read_csv(AMOSTRA / f"imoveis_{COD}.csv")
    assert len(lista) == len(df)
    um = lista[0]
    assert {"deficit_RL_ha", "pct_RL", "filtro_territorial", "tmf_classe", "mb_floresta_2025_ha"} <= set(um)
    assert "app_escadinha_ha" not in um  # coluna do contrato que não veio no arquivo do motor não aparece
    assert "atributos" not in um and "rodada_id" not in um
    # as regras do front (apta) somadas dão o resumo do motor
    resumo = pd.read_csv(AMOSTRA / "resumo_PA.csv").set_index("cod_ibge").loc[COD]
    aptas = [front_api.ler_imovel(i) for i in lista]
    assert sum(a["apta"] for a in aptas) == resumo.aptas_carbono
    assert round(sum(a["carbono_ha"] for a in aptas if a["apta"])) == resumo.ha_carbono
    assert cl.get("/municipios/1100015/imoveis").status_code == 404


@pytest.mark.banco
def test_imovel_ficha_e_mascara(cliente):
    cl, alvo = cliente
    i = cl.get(f"/imoveis/{alvo}").json()
    assert i["cod_imovel"] == alvo and fmt_cpf(CPF) not in json.dumps(i) and i["nota"].startswith("dono ***.")
    assert cl.get("/imoveis/PA-0000000-NAOEXISTE").status_code == 404
    f = cl.get(f"/imoveis/{alvo}/ficha").json()
    assert f["versao"] == 1 and f["contexto"]["n_imoveis"] == 880 and f["contexto"]["cod_ibge"] == str(COD)
    assert f["caixa"] == pytest.approx([-47.30, -2.30, -47.29, -2.29])
    assert len(f["perimetro"]) == 1 and isinstance(f["perimetro"][0], str)
    assert 0 <= f["contexto"]["posicao_carbono"] <= 1
    # o contexto rápido (só as colunas usadas) é o mesmo de montar com o município inteiro
    eng = cl.app.state.engine
    cheio = front_api.montar_ficha(i, front_api.imoveis_do_municipio(eng, cod_ibge=COD), None)["contexto"]
    assert f["contexto"] == cheio


@pytest.mark.banco
def test_leituras_em_markdown_com_os_mesmos_dados(cliente):
    cl, alvo = cliente
    for url, esperado in (
        ("/municipios", "Nova Esperança do Piriá"),
        (f"/municipios/{COD}/imoveis", alvo),
        (f"/imoveis/{alvo}", alvo),
        (f"/imoveis/{alvo}/ficha", "Contexto"),
        ("/busca?q=Nova%20Esperança", "Nova Esperança do Piriá"),
    ):
        resposta = cl.get(url, headers={"Accept": "text/markdown"})
        assert resposta.status_code == 200, url
        assert resposta.headers["content-type"].startswith("text/markdown"), url
        assert "Accept" in resposta.headers["vary"].split(", "), url
        assert esperado in resposta.text and fmt_cpf(CPF) not in resposta.text, url
        assert cl.get(url).headers["content-type"].startswith("application/json"), url


@pytest.mark.banco
def test_certidoes(cliente):
    cl, _ = cliente
    cert = pd.read_csv(AMOSTRA / f"certidoes_{COD}.csv")
    cod = cert.cod_imovel.iloc[0]
    r = cl.get(f"/imoveis/{cod}/certidoes").json()
    assert len(r) == (cert.cod_imovel == cod).sum()
    assert {"registro_cns", "registro_matricula", "ha_sobre_car", "parcelas"} <= set(r[0])


@pytest.mark.banco
def test_camadas_e_mapa_base_com_range(cliente):
    cl, alvo = cliente
    m = cl.get(f"/geo/{COD}/municipio.geojson")
    assert m.status_code == 200 and m.headers["content-type"].startswith("application/geo+json")
    assert m.json()["features"][0]["properties"]["nome"] == "Nova Esperança do Piriá"  # nome de lugar fica
    im = cl.get(f"/geo/{COD}/imoveis.geojson").json()
    assert [f["properties"]["cod_imovel"] for f in im["features"]] == [alvo]
    assert cl.get(f"/geo/{COD}/rios.geojson").status_code == 404
    assert cl.get(f"/geo/{COD}/estradas.geojson").status_code == 404
    r = cl.get(f"/geo/{COD}/base.pmtiles", headers={"Range": "bytes=10-19"})
    assert r.status_code == 206 and r.content == bytes(range(10, 20))
    assert r.headers["content-range"] == "bytes 10-19/1024"
    assert cl.get(f"/geo/{COD}/base.pmtiles").headers.get("accept-ranges") == "bytes"
    assert cl.get("/geo/1100015/base.pmtiles").status_code == 404


@pytest.mark.banco
def test_cors_para_o_front(cliente):
    cl, _ = cliente
    r = cl.options(
        "/municipios",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,range",
        },
    )
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "http://localhost:5173"
    g = cl.get(f"/geo/{COD}/base.pmtiles", headers={"Origin": "http://localhost:5173", "Range": "bytes=0-3"})
    assert "Content-Range" in g.headers["access-control-expose-headers"]
