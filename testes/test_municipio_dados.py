"""Dados por município (design v1, item 4): funil por etapa e porte com motivos, desde a última análise, frase-resumo
e contorno urbano, e as rotas."""

import datetime as dt
import shutil

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from raiz import motivos
from raiz.municipio_dados import frase, funil
from testes.conftest import AMOSTRA

COD = 1504950


def test_funil_e_frase_sem_banco():
    linhas = [
        {"etapa": "cadastro", "motivo_saida": "embargo", "ha": 10, "carbono_ha": 0, "porte": "pequeno"},
        {"etapa": "sem_problema", "motivo_saida": "alem", "ha": 20, "carbono_ha": 0, "porte": "pequeno"},
        {"etapa": "apta", "motivo_saida": "matricula", "ha": 30, "carbono_ha": 12, "porte": "médio"},
        {"etapa": "com_matricula", "motivo_saida": "titulo", "ha": 40, "carbono_ha": 8, "porte": "grande",
         "aceite": "aceito"},
    ]  # fmt: skip
    f = funil(linhas)
    e = {x["etapa"]: (x["imoveis"], x["ha"]) for x in f["etapas"]}
    assert e["cadastro"] == (4, 100) and e["sem_problema"] == (3, 90) and e["apta"] == (2, 20) and e["aceite"] == (1, 8)
    assert f["motivos_saida"]["cadastro"][0]["motivo"] == "embargo"
    assert set(f["por_porte"]) == {"pequeno", "médio", "grande"}
    t = frase("Lugar", "PA", f, None, {"subiram": 2, "desceram": 1})
    assert t.startswith("Em Lugar (PA), a Raíz analisou 4 imóveis") and "2 subiram e 1 desceram" in t
    assert frase("Lugar", "PA", None, {"imoveis": 50, "aptas_carbono": 7}, None).endswith("ainda não foi carregada.")
    assert frase("Lugar", "PA", None, None, None) == "A Raíz ainda não analisou os imóveis de Lugar (PA)."


@pytest.mark.banco
def test_rotas_e_desde_a_ultima_analise(banco_url, tmp_path, monkeypatch):
    import raiz.api as api_mod
    from raiz.api import criar_app
    from raiz.carga import carregar_municipio

    eng = create_engine(banco_url)
    with eng.begin() as c:
        c.execute(text("truncate funil.rodada, funil.imovel, funil.vigente, funil.municipio_busca, geo.camada cascade"))
    pasta = tmp_path / "PA"
    pasta.mkdir()
    shutil.copy(AMOSTRA / "imoveis_1504950.csv", pasta / "imoveis_1504950.csv")
    with eng.begin() as c:
        carregar_municipio(c, pasta, COD, dt.date(2026, 11, 12))
    # o motor reprocessa: uma apta ganha matrícula (sobe) e outra ganha embargo (desce)
    df = pd.read_csv(pasta / "imoveis_1504950.csv")
    aptas = [
        i for i, r in enumerate(df.to_dict("records")) if motivos.ler(r)["apta"] and not motivos.ler(r)["com_matricula"]
    ]
    df.loc[aptas[0], "f_matricula"] = 0.9
    df.loc[aptas[1], ["problema", "embargo_ha"]] = [True, 50.0]
    df.to_csv(pasta / "imoveis_1504950.csv", index=False)
    with eng.begin() as c:
        carregar_municipio(c, pasta, COD, dt.date(2026, 11, 13))
        sede = "POLYGON((-46 -2,-45.99 -2,-45.99 -1.99,-46 -1.99,-46 -2))"
        c.execute(text("""insert into geo.camada (cod_ibge, camada, propriedades, geom)
                          values (:c, 'urbana', '{"nome": "Sede"}', ST_SetSRID(ST_GeomFromText(:g), 4674))"""),
                  {"c": COD, "g": sede})  # fmt: skip
    cfg = type("C", (), {"api_token": SecretStr("t"), "api_origens": ""})()
    monkeypatch.setattr(api_mod, "config", lambda: cfg)
    app = criar_app(engine=eng, grafo=object(), deps=object(), whatsapp=False)
    with TestClient(app, headers={"Authorization": "Bearer t"}) as cl:
        d = cl.get(f"/municipios/{COD}").json()
        assert d["desde_ultima_analise"]["subiram"] == 1 and d["desde_ultima_analise"]["desceram"] == 1
        assert d["desde_ultima_analise"]["iguais"] == 878 and d["desde_ultima_analise"]["novos"] == 0
        assert (
            d["funil"]["etapas"][0]["imoveis"] == 880 and "Desde a última análise, 1 subiram e 1 desceram" in d["frase"]
        )
        assert all(len(v) <= 3 for v in d["funil"]["motivos_saida"].values())
        assert 100 < d["area_urbana_ha"] < 130  # 0,01 x 0,01 grau perto do equador
        u = cl.get(f"/municipios/{COD}/urbana.geojson")
        assert u.status_code == 200 and u.json()["features"][0]["properties"]["nome"] == "Sede"
        assert cl.get("/municipios/1507300/urbana.geojson").status_code == 404
        assert cl.get("/municipios/9999999").status_code == 404
    eng.dispose()
