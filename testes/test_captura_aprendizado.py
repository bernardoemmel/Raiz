"""Captura automática na tarefa e modelos reexecutados sem usar fontes de hoje."""

import datetime as dt
import uuid
from types import SimpleNamespace

import geopandas as gpd
import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from raiz import flag, rebanho
from raiz.aprendizado import arquivo_historico as A
from raiz.aprendizado import reexecucao as R
from raiz.aprendizado.captura import Captura, sanitizar_entrada
from raiz.funil import rodar as RD
from raiz.operacao.healthchecks import Healthchecks
from testes.test_reexecucao_folds import COD, MUNICIPIO, _dados, _retrato


def test_captura_nao_antecipa_censo_quando_modelo_nao_precisa(monkeypatch):
    monkeypatch.setattr(rebanho, "bovinos_municipio", lambda *a: (None, None))
    monkeypatch.setattr(rebanho, "censo_2017", lambda *a: pytest.fail("Censo não é necessário sem PPM"))
    cap = Captura("PA", MUNICIPIO)
    with cap.modelos():
        result = rebanho.espalhar([{"cod_imovel": COD, "pasto_ha": 10}], MUNICIPIO)
    assert result[0]["rebanho_fonte"] == "sem_ppm"
    assert cap.entradas["entrada_rebanho"][COD]["contexto"]["totais"]["censo_2017"] is None


def test_documento_numerico_fora_da_lista_positiva_nao_vai_ao_treino():
    from testes.test_privacidade import gerar_cpf

    numero = int(gerar_cpf("".join(str(i) for i in range(1, 10))))
    atributos, _ = sanitizar_entrada("entrada_flag", {"documento": numero, "uf": numero, "ha": 0.3}, {})
    assert atributos == {"ha": 0.3}


def test_flag_preserva_pasto_da_pequena_fora_da_frente_de_regeneracao():
    li = {
        "ha": 0.3,
        "alem_RL_ha": 0.3,
        "app_recompor_ha": 0.0,
        "mb_pasto_2023_ha": 0.2,
        "bioma": "Amazônia",
        "uf": "PA",
    }
    retrato = _retrato()
    retrato.dados["entrada_flag"] = pd.DataFrame([{"cod_imovel": COD, "atributos": li, "contexto": {}}])
    previsto = R.prever(retrato, ("flag",))["flag"][0][0]
    assert previsto.valor_num == flag.por_imovel(li)["flag_tco2_ano"] == pytest.approx(0.6)
    # Um zonal ausente é falta de histórico, nunca 0 hectares por suposição.
    retrato.dados.pop("entrada_flag")
    with pytest.raises(R.HistoricoInsuficiente, match="entradas históricas"):
        R.prever(retrato, ("flag",))


def test_codigo_municipal_numerico_nao_esconde_embargo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = _retrato()
    r.dados["ibama"] = pd.DataFrame(
        [
            {
                "seq_tad": "termo-teste",
                "cod_municipio": float(MUNICIPIO),
                "sit_cancelado": "N",
                "sit_desembargo": "N",
                "geom_area_embargada": r.dados["car"].geometry.iloc[0].wkt,
            }
        ]
    )
    saida = R.motor_no_retrato(r)
    assert saida.embargo_ha.iloc[0] > 1 and saida.problema.iloc[0]


def test_modelos_adicionais_so_usam_suas_entradas_arquivadas(monkeypatch):
    monkeypatch.setattr(rebanho, "bovinos_municipio", lambda *a: pytest.fail("leu PPM atual"))
    monkeypatch.setattr(rebanho, "censo_2017", lambda *a: pytest.fail("leu Censo atual"))
    out = R.prever(_retrato(), ("rebanho", "regularizacao", "triagem"))
    assert set(out) == {"rebanho", "regularizacao", "triagem_titulo"}
    assert all(ps for ps, _ in out.values())
    assert sum(p.p50 for p in out["rebanho"][0] if p.alvo == "rebanho_cab") == 1


def test_captura_fontes_observadas_restaura_funcoes_e_nao_inventa_alerta(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = _dados()
    motor = R._motor_isolado()
    motor.car_mun = lambda *a: d["car"].drop(columns="_hash")
    motor.sigef = lambda *a: d["sigef"]
    motor.camadas = lambda *a: ({k: d[k] for k in ("yd", "acc", "nf", "hy", "ti", "uc")}, ["Amazônia"])
    motor.biomas = lambda: d["biomas"]
    motor.alertas = lambda *a: d["alertas"].rename(columns={"anodetec": "ANODETEC"})
    motor.PROJ = gpd.GeoDataFrame(geometry=[], crs=4674)

    def regeneracao(c, uf):
        for k, valor in (("pasto_ha", 0.2), ("secundaria_ha", 0.0), ("pasto_ate1km_ha", 0.1)):
            c[k] = valor
        c["carbono_ha"] = 0.1
        return c

    motor.regeneracao = regeneracao
    orig = motor.car_mun, motor.regeneracao, motor.camadas
    cap = Captura("PA", MUNICIPIO)
    emb = d["ibama"].rename(columns=str.upper)
    with cap.motor(motor, emb):
        motor.municipio("PA", MUNICIPIO, emb, str(tmp_path))
    assert (motor.car_mun, motor.regeneracao, motor.camadas) == orig
    assert {"car", "sigef", "biomas", "regeneracao", "ibama"} <= set(cap.dados)
    assert {"projetos", "alertas"} <= cap.indisponiveis
    assert not {"projetos", "alertas"} & set(cap.dados)
    assert cap.dados["regeneracao"].car_hash.iloc[0] == cap.dados["car"]._hash.iloc[0]


@pytest.mark.banco
def test_executor_arquiva_flag_automaticamente_e_fold_nao_depende_do_motor(banco_url, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    esquema = "captura_" + uuid.uuid4().hex[:8]
    monkeypatch.setattr(A, "ESQUEMA", esquema)
    monkeypatch.setattr(RD, "_R", SimpleNamespace())
    monkeypatch.setattr(RD, "_ENGINE", None)
    pasta = tmp_path / "saida" / "PA"
    pasta.mkdir(parents=True)
    pd.DataFrame(
        [{"cod_imovel": COD, "ha": 0.3, "alem_RL_ha": 0.3, "app_recompor_ha": 0.0, "bioma": "Amazônia", "uf": "PA"}]
    ).to_csv(pasta / f"imoveis_{MUNICIPIO}.csv", index=False)
    pd.DataFrame([{"cod_imovel": COD, "mb_pasto_2023_ha": 0.2}]).to_csv(
        pasta / f"mapbiomas_{MUNICIPIO}.csv", index=False
    )
    op = RD.Opcoes("PA", tarefas=("flag",), refazer=True, banco_url=banco_url)
    assert RD.rodar_municipio(MUNICIPIO, op, Healthchecks()) == {"flag": "sucesso"}
    with create_engine(banco_url).begin() as con:
        cat = A.catalogo(con, MUNICIPIO)
        assert set(cat) == {"entrada_flag"}
        corte = cat["entrada_flag"].ate
        resultados = R.reexecutar(con, [corte], "PA", MUNICIPIO, cat, ("motor", "flag"))
        assert resultados[0]["situacao"] == "historico_insuficiente"
        assert resultados[1]["situacao"] == "ok" and resultados[1]["previsoes"] == 1
        p = con.execute(
            text("select valor_num from aprendizado.previsao where lote_hash=:h"), {"h": resultados[1]["lote_hash"]}
        ).scalar_one()
        assert p == pytest.approx(0.6)
        lote = con.execute(
            text("select detalhe from operacao.lote where tarefa='flag' and cod_municipio=:c order by id desc limit 1"),
            {"c": MUNICIPIO},
        ).scalar_one()
        assert lote["historico_aprendizado"]["contagens"] == {"entrada_flag": 1}
        # Nada era conhecido um instante antes da captura real.
        anterior = R.reexecutar(con, [corte - dt.timedelta(microseconds=1)], "PA", MUNICIPIO, cat, ("flag",))
        assert anterior[0]["situacao"] == "historico_insuficiente"
