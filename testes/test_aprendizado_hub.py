"""Previsões congeladas no formato do hub (hubverse) e painel de acerto (E7 passo 5)."""

import datetime as dt
import json
import re

import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from raiz.aprendizado import acerto as AC
from raiz.aprendizado import hub as H

TOKEN = "token-acerto-teste"


def test_wis_e_notas():
    # y dentro do intervalo: WIS = (0,5 |y - m| + 0,1 (u - l)) / 1,5
    assert AC.wis(12, 10, 11, 20) == pytest.approx((0.5 * 1 + 0.1 * 10) / 1.5)
    # y acima: IS = (u - l) + 10 (y - u)
    assert AC.wis(25, 10, 11, 20) == pytest.approx((0.5 * 14 + 0.1 * (10 + 10 * 5)) / 1.5)
    f = AC.nota({"alvo": "custo", "p10": 10, "p50": 11, "p90": 20, "real_num": 25})
    assert f["tipo"] == "faixa" and f["cobertura_80"] == 0 and f["ae_mediana"] == 14
    c = AC.nota({"alvo": "aceite_dono", "valor_num": 0.8, "real_num": 1})
    assert c["tipo"] == "chance" and c["brier"] == pytest.approx(0.04) and c["acerto"] == 1
    assert AC.nota({"alvo": "frente", "valor_texto": "carbono", "real_texto": "Carbono"})["acerto"] == 1
    assert AC.nota({"alvo": "x", "valor_num": 3.0, "real_num": 5.0}) == {"tipo": "numero", "ae": 2.0, "eq": 4.0}
    assert AC.nota({"alvo": "x", "valor_num": 3.0}) is None


def test_placar_e_versao_na_frente():
    linhas = []
    for versao, erro in (("v1", 5.0), ("v2", 1.0)):
        for _ in range(12):
            linhas.append({"modelo": "m", "modelo_versao": versao, "alvo": "custo", "p10": 0, "p50": 10 + erro,
                           "p90": 30, "real_num": 10, "maturou": True})  # fmt: skip
    pl = AC.placar(linhas)
    assert [(r["modelo_versao"], r["com_gabarito"], r["cobertura_80"]) for r in pl] == [
        ("v1", 12, 1.0),
        ("v2", 12, 1.0),
    ]
    assert AC.campeoes(pl) == [
        {
            "modelo": "m",
            "alvo": "custo",
            "metrica": "wis",
            "versao": "v2",
            "nota": pl[1]["wis"],
            "versoes_comparadas": 2,
        }
    ]


def test_formato_das_linhas_do_hub():
    assert re.fullmatch(r"[a-z0-9_]+-[a-z0-9_]+", H.model_id("aceite_dono", "pedidos-2026.11a+1a2b"))
    base = {"cod_imovel": "PA-1-A", "data_corte": dt.date(2026, 1, 1), "horizonte_dias": 30,
            "horizonte_em": dt.date(2026, 1, 31)}  # fmt: skip
    q = H.linhas_previsao({**base, "alvo": "custo", "p10": 9.0, "p50": 1.0, "p90": 5.0})
    assert [(x["output_type"], x["output_type_id"], x["value"]) for x in q] == [
        ("quantile", "0.1", 1.0),
        ("quantile", "0.5", 5.0),
        ("quantile", "0.9", 9.0),
    ]  # quantis em ordem crescente
    pmf = H.linhas_previsao({**base, "alvo": "aceite_dono", "valor_num": 0.3})
    assert [(x["output_type_id"], x["value"]) for x in pmf] == [("verdadeiro", 0.3), ("falso", 0.7)]
    cat = H.linhas_previsao({**base, "alvo": "frente", "valor_texto": "Carbono"}, ["carbono", "desbloqueio"])
    assert [(x["output_type_id"], x["value"]) for x in cat] == [("carbono", 1.0), ("desbloqueio", 0.0)]
    assert H.linhas_previsao({**base, "alvo": "f", "valor_num": 0.5})[0]["output_type"] == "mean"
    g = H.linhas_gabarito({**base, "alvo": "aceite_dono", "real_num": 1.0})
    assert [(x["output_type_id"], x["oracle_value"]) for x in g] == [("verdadeiro", 1.0), ("falso", 0.0)]


@pytest.fixture(scope="module")
def eng(banco_url):
    e = create_engine(banco_url)
    yield e
    e.dispose()


@pytest.mark.banco
def test_exporta_o_hub_e_mostra_o_painel(eng, tmp_path, monkeypatch):
    from raiz.aprendizado.registro import Previsao, Versoes, registrar_gabarito, registrar_lote

    corte = dt.date(2025, 6, 1)
    with eng.begin() as con:
        registrar_lote(
            con,
            [Previsao(f"PA-1504950-H{k}", "hub_custo_rs_ha", 365, p10=100.0, p50=150.0, p90=200.0) for k in range(3)]
            + [Previsao(f"PA-1504950-H{k}", "aceite_dono", 30, valor_num=0.7) for k in range(3)]
            + [Previsao("PA-1504950-H0", "hub_frente", 365, valor_texto="carbono")],
            Versoes("hub_teste", "hub-v1", "teste", corte),
        )
        for k, real in enumerate((160.0, 120.0, 250.0)):
            registrar_gabarito(con, f"PA-1504950-H{k}", "hub_custo_rs_ha", dt.date(2026, 6, 1), "campo", real)
        registrar_gabarito(con, "PA-1504950-H0", "aceite_dono", dt.date(2025, 6, 20), "whatsapp", 1.0)
        registrar_gabarito(con, "PA-1504950-H1", "aceite_dono", dt.date(2025, 6, 20), "whatsapp", 0.0)
        registrar_gabarito(con, "PA-1504950-H0", "hub_frente", dt.date(2026, 6, 1), "contrato", valor_texto="carbono")
    r = H.exportar(eng, tmp_path, desde=corte)
    mid = H.model_id("hub_teste", "hub-v1")
    arq = tmp_path / "model-output" / mid / f"{corte}-{mid}.parquet"
    df = pd.read_parquet(arq)
    assert list(df.columns) == H.COLS_SAIDA and set(df.output_type) == {"quantile", "pmf"}
    assert r["modelos"] >= 1 and (tmp_path / "model-metadata" / f"{mid}.yml").exists()
    tasks = json.loads((tmp_path / "hub-config" / "tasks.json").read_text())
    assert tasks["schema_version"].endswith("/v6.0.0/tasks-schema.json")
    alvos = {m["target_metadata"][0]["target_id"]: m for m in tasks["rounds"][0]["model_tasks"]}
    assert alvos["aceite_dono"]["output_type"]["pmf"]["output_type_id"]["required"] == ["verdadeiro", "falso"]
    assert alvos["hub_custo_rs_ha"]["output_type"]["quantile"]["output_type_id"]["required"] == [0.1, 0.5, 0.9]
    oraculo = pd.read_csv(tmp_path / "target-data" / "oracle-output.csv")
    assert list(oraculo.columns) == ["location", "target", "target_end_date", "output_type", "output_type_id",
                                     "oracle_value"]  # fmt: skip
    pe = yaml.safe_load((tmp_path / "predevals-config.yml").read_text())
    assert pe["schema_version"] == H.PREDEVALS and pe["rounds_idx"] == 0
    metr = {t["target_id"]: t["metrics"] for t in pe["targets"]}
    assert metr["hub_custo_rs_ha"] == ["wis", "ae_median", "interval_coverage_80"] and metr["aceite_dono"] == [
        "log_score"
    ]
    # painel pela API (token) e a página sem dado
    from raiz.api import criar_app

    cfg = type("C", (), {"api_token": SecretStr(TOKEN), "api_origens": ""})()
    import raiz.api as api_mod

    monkeypatch.setattr(api_mod, "config", lambda: cfg)
    with TestClient(criar_app(engine=eng, grafo=object(), deps=object(), whatsapp=False)) as cl:
        assert cl.get("/acerto/placar").status_code == 401
        assert "token da API" in cl.get("/painel/acerto").text
        d = cl.get(f"/acerto/placar?desde={corte}", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    pl = {(p["modelo"], p["alvo"]): p for p in d["previsoes"]}
    custo = pl[("hub_teste", "hub_custo_rs_ha")]
    assert custo["com_gabarito"] == 3 and custo["cobertura_80"] == pytest.approx(2 / 3)
    aceite = pl[("hub_teste", "aceite_dono")]
    assert aceite["com_gabarito"] == 2 and aceite["brier"] == pytest.approx((0.3**2 + 0.7**2) / 2)
    assert pl[("hub_teste", "hub_frente")]["acerto"] == 1.0
    with eng.connect() as con:  # previsão congelada continua congelada
        with pytest.raises(Exception, match="congelada"):
            con.execute(text("delete from aprendizado.previsao where modelo = 'hub_teste'"))
