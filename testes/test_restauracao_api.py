"""Valor para quem restaura no banco e na API: carga de desenvolvedor_<mun>.csv, bloco "Para quem restaura" na
ficha, painel do município ordenado e filtrado, lotes, simulador com parâmetros editáveis, real informado pelo
cliente, previsões congeladas com a versão do modelo e recalibração."""

import datetime as dt
import shutil

import pytest
from sqlalchemy import create_engine, text

from raiz import restauracao as R
from testes.conftest import AMOSTRA

pytestmark = pytest.mark.banco
COD = 1504950


def _geo_sintetico(pasta):
    """A amostra não traz polígonos: quadrados de ~300 m espalhados em 0,3 grau, fixos pelo código do imóvel."""
    import hashlib

    import geopandas as gpd
    import pandas as pd
    import shapely

    cods = pd.read_csv(pasta / f"imoveis_{COD}.csv", usecols=["cod_imovel"]).cod_imovel.astype(str)
    geoms = []
    for c in cods:
        h = hashlib.sha256(c.encode()).digest()
        x, y = -47.4 + h[0] / 255 * 0.3, -2.4 + h[1] / 255 * 0.3
        geoms.append(shapely.box(x, y, x + 0.003, y + 0.003))
    gpd.GeoDataFrame({"cod_imovel": cods}, geometry=geoms, crs=4674).to_parquet(pasta / f"geo_{COD}.parquet")


@pytest.fixture(scope="module")
def cliente(banco_url, tmp_path_factory):
    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    import raiz.api as api_mod
    from raiz.api import criar_app
    from raiz.carga import carregar_municipio

    pasta = tmp_path_factory.mktemp("rest") / "PA"
    pasta.mkdir()
    for f in AMOSTRA.glob(f"*_{COD}.csv"):
        shutil.copy(f, pasta / f.name)
    _geo_sintetico(pasta)
    R.calcular_municipio(pasta, COD, fontes_geo=()).to_csv(pasta / f"desenvolvedor_{COD}.csv", index=False)
    eng = create_engine(banco_url)
    with eng.begin() as c:
        c.execute(text("truncate funil.rodada, funil.imovel, funil.vigente, funil.municipio_busca cascade"))
        # o aprendizado é só de inserir (não se apaga): o mesmo lote congelado de novo não duplica (mesmo hash)
        res = carregar_municipio(c, pasta, COD, dt.date(2026, 11, 12))
        from raiz.aprendizado.congelar import congelar_rodada

        congelar_rodada(c, res.rodada_id)
        rodada = res.rodada_id
    mp = pytest.MonkeyPatch()
    cfg = type("C", (), {"api_token": SecretStr("t"), "api_origens": ""})()
    mp.setattr(api_mod, "config", lambda: cfg)
    app = criar_app(engine=eng, grafo=object(), deps=object(), whatsapp=False)
    with TestClient(app, headers={"Authorization": "Bearer t"}) as cl:
        yield cl, eng, rodada
    mp.undo()
    eng.dispose()


def _um_com_area(cl):
    lista = cl.get(f"/municipios/{COD}/imoveis", params={"ordem": "valor_desenvolvedor"}).json()
    return lista[0]


def test_ficha_tem_o_bloco_para_quem_restaura(cliente):
    cl, _, _ = cliente
    alvo = _um_com_area(cl)
    f = cl.get(f"/imoveis/{alvo['cod_imovel']}/ficha").json()
    b = f["para_quem_restaura"]
    assert b["disponivel"] and "Estimativa" in b["aviso"]
    assert b["modo"]["id"] in R.regra()["modos"]
    for k in ("custo_rs_ha", "captura_tco2_ha_ano", "credito_liquido_tco2_ha_ano", "vpl_rs_ha", "tir_projeto_pct",
              "tir_alavancada_pct", "pico_capital_proprio_rs_ha"):  # fmt: skip
        assert b[k]["p10"] <= b[k]["p50"] <= b[k]["p90"], k
    assert b["versao"] == R.versao() and b["cenario"]["cenario"] == "central_r11"
    assert [d["id"] for d in b["descontos"]] == ["linha_base", "vazamento", "reserva_risco", "incerteza"]
    assert b["marcos"]["lista"] and b["pagamento_dono"]["comparacao"][0]["atual"]
    assert "explicacao" in b["linha_base"] and b["faltou"]  # sem geo na amostra: diz o que faltou
    # FLAG e crédito continuam separados; o bloco novo não soma com a meta FLAG
    assert "flag" in f and "nao_somar" in f["flag"]


def test_painel_do_municipio_ordena_e_filtra_sem_sumir_ninguem(cliente):
    cl, _, _ = cliente
    todos = cl.get(f"/municipios/{COD}/imoveis").json()
    ordenados = cl.get(f"/municipios/{COD}/imoveis", params={"ordem": "valor_desenvolvedor"}).json()
    assert len(ordenados) == len(todos)  # ordenar não corta ninguém
    v = [x.get("valor_desenvolvedor_rs") for x in ordenados if x.get("valor_desenvolvedor_rs") is not None]
    assert v == sorted(v, reverse=True)
    so = cl.get(f"/municipios/{COD}/imoveis", params={"modo": "plantio_total"}).json()
    assert so and all(x["modo_restauracao"] == "plantio_total" for x in so)
    tir = cl.get(f"/municipios/{COD}/imoveis", params={"tir_min": 25}).json()
    assert all(x["tir_alavancada_pct_p50"] >= 25 for x in tir)
    assert cl.get(f"/municipios/{COD}/imoveis", params={"ordem": "nome"}).status_code == 422
    assert cl.get(f"/municipios/{COD}/imoveis", params={"modo": "xyz"}).status_code == 422


def test_lotes(cliente):
    cl, _, _ = cliente
    lotes = cl.get(f"/municipios/{COD}/lotes").json()
    assert lotes and all(lt["n_imoveis"] >= 1 and lt["ha"] > 0 for lt in lotes)
    assert [lt["credito_tco2_ano"] for lt in lotes] == sorted([lt["credito_tco2_ano"] for lt in lotes], reverse=True)
    assert all("nome" not in str(lt).lower() for lt in lotes)


def test_simulador_e_cenarios(cliente):
    cl, _, _ = cliente
    alvo = _um_com_area(cl)
    cods = cl.get("/restauracao/cenarios").json()
    assert cods["padrao"] == "central_r11"
    assert {"central_r11_74", "estresse_r11", "otimista_fundador", "otimista_fundador_74"} <= set(cods["cenarios"])
    assert cods["cenarios"]["central_r11"]["fontes"]["preco_usd_t"].startswith("fundador, rodada 11")
    assert "duas_fases" in cods["opcoes"]["pagamento_dono"]
    base = cl.get(f"/imoveis/{alvo['cod_imovel']}/restauracao/simular").json()
    caro = cl.get(f"/imoveis/{alvo['cod_imovel']}/restauracao/simular", params={"preco_usd_t": 74}).json()
    assert caro["vpl_rs_ha"]["p50"] > base["vpl_rs_ha"]["p50"] and len(base["fluxo_p50"]["anos"]) == 41
    ot = cl.get(f"/imoveis/{alvo['cod_imovel']}/restauracao/simular", params={"cenario": "otimista_fundador"}).json()
    assert len(ot["fluxo_p50"]["anos"]) == 26 and ot["cenario"]["cenario"] == "otimista_fundador"
    r = cl.get(f"/imoveis/{alvo['cod_imovel']}/restauracao/simular", params={"fracao_financiada": 3})
    assert r.status_code == 422 and "fracao_financiada" in r.json()["detail"]["mensagem"]


def test_previsao_congelada_real_do_cliente_e_recalibracao(cliente, tmp_path):
    from raiz.restauracao_aprendizado import comparar, recalibrar

    cl, eng, rodada = cliente
    with eng.connect() as c:
        lote = c.execute(
            text("""select lote_hash, modelo_versao, n_previsoes from aprendizado.lote_previsao
                    where modelo = 'restauracao' and rodada_id = :r"""),
            {"r": rodada},
        ).one()
    assert lote.modelo_versao == R.versao() and lote.n_previsoes > 0
    alvo = _um_com_area(cl)
    cod = alvo["cod_imovel"]
    ok = cl.post(f"/imoveis/{cod.lower()}/restauracao/real",
                 json={"custo_rs_ha": alvo["custo_restauracao_ha_p50"] * 1.5, "modo": alvo["modo_restauracao"],
                       "fonte": "desenvolvedor (planilha de implantação)", "observado_em": "2027-06-01"})  # fmt: skip
    assert ok.status_code == 200 and ok.json()["gravados"] == 2
    assert cl.post(f"/imoveis/{cod}/restauracao/real", json={"custo_rs_ha": 1}).status_code == 422  # sem fonte
    assert cl.post(f"/imoveis/{cod}/restauracao/real", json={"fonte": "x"}).status_code == 422  # sem valor
    with eng.connect() as c:
        comp = {(x["alvo"], x["modo"]): x for x in comparar(c, versao=R.versao(), lotes=[lote.lote_hash])}
        custo = comp[("restauracao_custo_rs_ha", alvo["modo_restauracao"])]
        assert custo["n"] == 1 and custo["razao_mediana"] == pytest.approx(1.5, rel=1e-3)
        assert comp[("restauracao_modo", alvo["modo_restauracao"])]["acerto_modo"] == 1
        arq = tmp_path / "calibracao.yaml"
        r = recalibrar(c, gravar=True, arquivo=arq, versao=R.versao(), lotes=[lote.lote_hash])
    fator = r["fatores"]["custo"][alvo["modo_restauracao"]]["fator"]
    assert fator == pytest.approx(1 + 0.5 * 1 / 6, rel=1e-3)  # 1 caso: anda 1/6 do caminho
    assert arq.exists()
    v_antes = R.regra(R.ARQ_REGRA, R.ARQ_CENARIOS, tmp_path / "nada.yaml")["versao_completa"]
    calibrada = R.regra(R.ARQ_REGRA, R.ARQ_CENARIOS, arq)
    assert calibrada["versao_completa"] != v_antes
    li = {**alvo}
    p50_antes = R.custo(li, r=R.regra(R.ARQ_REGRA, R.ARQ_CENARIOS, tmp_path / "nada.yaml"))["p50"]
    assert R.custo(li, r=calibrada)["p50"] > p50_antes
