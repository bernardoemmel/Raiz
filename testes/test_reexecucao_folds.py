"""Folds com o motor real e fontes históricas: nenhum download, nem versão futura."""

import dataclasses
import datetime as dt
import json
import uuid

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box
from sqlalchemy import text

from raiz.aprendizado import reexecucao as R
from raiz.aprendizado.registro import conferir_lote

CORTE = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
ANTES = dt.datetime(2023, 1, 1, tzinfo=dt.UTC)
DEPOIS = dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
COD = "PA-1504950-TESTE-FOLD"
MUNICIPIO = 1504950


def _dados():
    d = {}
    for nome, esp in R.FONTES.items():
        df = pd.DataFrame(columns=esp.campos)
        if esp.geometria:
            df = gpd.GeoDataFrame(df, geometry=[], crs=4674)
        d[nome] = df
    geom = box(-47.3, -2.3, -47.298, -2.298)
    d["car"] = gpd.GeoDataFrame(
        {
            "cod_imovel": [COD],
            "status_imovel": ["AT"],
            "tipo_imovel": ["IRU"],
            "municipio": ["Município de teste"],
            "m_fiscal": [0.01],
            "_hash": ["car-antigo"],
        },
        geometry=[geom],
        crs=4674,
    )
    d["biomas"] = gpd.GeoDataFrame({"bioma": ["Amazônia"]}, geometry=[geom.buffer(1)], crs=4674)
    d["acc"] = gpd.GeoDataFrame(geometry=[geom], crs=4674)
    d["regeneracao"] = pd.DataFrame(
        {
            "cod_imovel": [COD],
            "car_hash": ["car-antigo"],
            "pasto_ha": [0.2],
            "secundaria_ha": [0.0],
            "pasto_ate1km_ha": [0.1],
        }
    )
    return d


def _retrato():
    return R.Retrato(CORTE, MUNICIPIO, "PA", _dados(), "hash-historico")


def test_motor_real_sem_rede_preserva_pequeno_e_detecta_problema_futuro(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("requests.sessions.Session.request", lambda *a, **kw: pytest.fail("acesso à rede no fold"))
    antes = _retrato()
    saida = R.motor_no_retrato(antes)
    assert saida.cod_imovel.tolist() == [COD]
    assert not saida.problema.iloc[0]
    assert saida.carbono_ha.iloc[0] == pytest.approx(0.1)
    pequena = _retrato()
    pequena.dados["car"].geometry = [box(-47.3, -2.3, -47.2995, -2.2995)]
    pequena_saida = R.motor_no_retrato(pequena)
    assert pequena_saida.cod_imovel.tolist() == [COD]
    assert 0 < pequena_saida.ha.iloc[0] < 1
    assert pequena_saida.frente.iloc[0] == "silvipastoril"  # pequena continua, mesmo sem outra frente
    futuro = _retrato()
    futuro.dados["car"].geometry = [box(-47.3, -2.3, -47.29, -2.29)]
    futuro.dados["yd"] = gpd.GeoDataFrame(
        {"year": [2024], "main_class": ["DESMATAMENTO"]}, geometry=futuro.dados["car"].geometry, crs=4674
    )
    assert R.motor_no_retrato(futuro).problema.iloc[0]


def test_motor_recusa_zonal_de_outra_versao_e_invalido():
    retrato = _retrato()
    retrato.dados["regeneracao"].loc[0, "car_hash"] = "car-novo"
    with pytest.raises(R.HistoricoInsuficiente, match="versão histórica"):
        R.motor_no_retrato(retrato)
    retrato = _retrato()
    retrato.dados["regeneracao"].loc[0, "pasto_ha"] = float("nan")
    with pytest.raises(R.HistoricoInsuficiente, match="incompleto"):
        R.motor_no_retrato(retrato)


def test_previsoes_modelos_sem_calibracao_atual(monkeypatch, tmp_path):
    from raiz import restauracao

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("requests.sessions.Session.request", lambda *a, **kw: pytest.fail("acesso à rede no fold"))
    falsa = tmp_path / "calibracao.yaml"
    falsa.write_text("custo:\n  regeneracao_assistida:\n    fator: 999\n")
    monkeypatch.setattr(restauracao, "ARQ_CALIBRACAO", falsa)
    r = R.prever(_retrato())
    assert set(r) == {"motor", "flag", "restauracao"}
    assert {p.cod_imovel for ps, _ in r.values() for p in ps} == {COD}
    assert "-sem-calibracao" in r["restauracao"][1]
    # Alvos e versão estão prontos para o mesmo portão campeão/desafiante.
    assert {p.alvo for p in r["motor"][0]} >= {"problema", "carbono_ha", "deficit_rl_ha"}
    assert {p.alvo for p in r["restauracao"][0]} >= {"restauracao_custo_rs_ha", "restauracao_modo"}
    custo = next(p for p in r["restauracao"][0] if p.alvo == "restauracao_custo_rs_ha")
    assert custo.p50 < 100000


def _banco_historico(con):
    esquema = "fold_" + uuid.uuid4().hex[:8]
    con.execute(text(f"create schema {esquema}"))
    catalogo = {}
    for nome, esp in R.FONTES.items():
        cols = [f"{c} text" for c in esp.campos]
        if esp.geometria:
            cols += ["geom geometry(Geometry,4674)"]
        cols += ["cod_municipio_ibge integer", "_dlt_valid_from timestamptz", "_dlt_valid_to timestamptz"]
        con.execute(text(f"create table {esquema}.{esp.tabela} ({','.join(cols)})"))
        catalogo[nome] = R.Fonte(ANTES, DEPOIS, "coletas-conferidas", esquema=esquema)
    for nome, df in _dados().items():
        esp = R.FONTES[nome]
        for row in df.to_dict("records"):
            if esp.geometria:
                row["geom"] = row.pop("geometry").wkt
            row.update(cod_municipio_ibge=MUNICIPIO, _dlt_valid_from=ANTES, _dlt_valid_to=None)
            cols, valores = [], []
            for k in row:
                cols.append(k)
                valores.append(f"ST_GeomFromText(:{k},4674)" if k == "geom" else f":{k}")
            con.execute(
                text(f"insert into {esquema}.{esp.tabela} ({','.join(cols)}) values ({','.join(valores)})"),
                {k: str(v) if k in esp.campos else v for k, v in row.items()},
            )
    return esquema, catalogo


@pytest.mark.banco
def test_reexecucao_scd2_exclui_futuro_congela_e_reproduz(con, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    esquema, cat = _banco_historico(con)
    q = f"{esquema}.car_imovel"
    primeiro = R.ler_retrato(con, CORTE, "PA", MUNICIPIO, cat)
    con.execute(text(f"update {q} set _dlt_valid_to = :d"), {"d": DEPOIS})
    con.execute(
        text(f"""insert into {q} select cod_imovel, 'CA', tipo_imovel, municipio, m_fiscal,
                           'car-futuro', geom, cod_municipio_ibge, :d, null from {q}"""),
        {"d": DEPOIS},
    )
    segundo = R.ler_retrato(con, CORTE, "PA", MUNICIPIO, cat)
    assert primeiro.entradas_hash == segundo.entradas_hash
    assert segundo.dados["car"].status_imovel.tolist() == ["AT"]
    assert R.ler_retrato(con, DEPOIS, "PA", MUNICIPIO, cat).dados["car"].status_imovel.tolist() == ["CA"]
    # Tipos numéricos do banco real; as tabelas artificiais usaram texto para campos dinâmicos do dlt.
    con.execute(text(f"alter table {q} alter column m_fiscal type double precision using m_fiscal::float"))
    for campo in ("pasto_ha", "secundaria_ha", "pasto_ate1km_ha"):
        con.execute(
            text(
                f"alter table {esquema}.mapbiomas_regeneracao alter column {campo} "
                f"type double precision using {campo}::float"
            )
        )
    a = R.reexecutar(con, [CORTE], "PA", MUNICIPIO, cat, ("motor", "flag"))
    b = R.reexecutar(con, [CORTE], "PA", MUNICIPIO, cat, ("motor", "flag"))
    assert all(x["novo"] for x in a) and not any(x["novo"] for x in b)
    for x in a:
        assert conferir_lote(con, x["lote_hash"])
        row = con.execute(
            text("select tipo, data_corte, receita_hash from aprendizado.previsao where lote_hash=:h"),
            {"h": x["lote_hash"]},
        ).first()
        assert row.tipo == "backtest" and row.data_corte == CORTE.date() and row.receita_hash


@pytest.mark.banco
def test_sem_cobertura_nao_vira_ausencia_e_rejeita_scd2_sobreposto(con):
    esquema, cat = _banco_historico(con)
    with pytest.raises(R.HistoricoInsuficiente, match="fontes sem"):
        R.ler_retrato(con, CORTE, "PA", MUNICIPIO, {})
    incompleto = {**cat, "ibama": dataclasses.replace(cat["ibama"], desde=DEPOIS)}
    with pytest.raises(R.HistoricoInsuficiente, match="ibama"):
        R.ler_retrato(con, CORTE, "PA", MUNICIPIO, incompleto)
    con.execute(text(f"insert into {esquema}.car_imovel select * from {esquema}.car_imovel"))
    with pytest.raises(R.HistoricoInsuficiente, match="sobrepostas"):
        R.ler_retrato(con, CORTE, "PA", MUNICIPIO, cat)


def test_catalogo_exige_fuso_referencia_e_nomes_validos(tmp_path):
    with pytest.raises(ValueError, match="fuso"):
        R.Fonte(ANTES.replace(tzinfo=None), DEPOIS, "conferido")
    with pytest.raises(ValueError, match="referência"):
        R.Fonte(ANTES, DEPOIS, "")
    with pytest.raises(ValueError, match="inválido"):
        R.Fonte(ANTES, DEPOIS, "ok", tabela="x;drop")
    p = tmp_path / "catalogo.json"
    p.write_text(
        json.dumps(
            {
                "fontes": {
                    "car": {"desde": ANTES.isoformat(), "ate": DEPOIS.isoformat(), "referencia": "coleta-publicada"}
                }
            }
        )
    )
    assert R.ler_catalogo(p)["car"].desde == ANTES


@pytest.mark.banco
def test_arquivo_acumula_scd2_fecha_fonte_vazia_e_isola_municipios(con, monkeypatch, tmp_path):
    from raiz.aprendizado import arquivo_historico as A

    esquema = "arquivo_fold_" + uuid.uuid4().hex[:8]
    monkeypatch.setattr(A, "ESQUEMA", esquema)
    dados = _dados()
    dados["car"]["nome_pessoa"] = "coluna excluída antes de arquivar"
    a = A.arquivar(con, dados, "PA", MUNICIPIO)
    A.arquivar(con, dados, "PA", MUNICIPIO)  # conferência, não outra versão do CAR
    dados["acc"] = gpd.GeoDataFrame(geometry=[], crs=4674)
    b = A.arquivar(con, dados, "PA", MUNICIPIO)
    A.arquivar(con, _dados(), "PA", MUNICIPIO + 1)
    cat = A.catalogo(con, MUNICIPIO)
    antigo = R.ler_retrato(con, dt.datetime.fromisoformat(a["observado_em"]), "PA", MUNICIPIO, cat)
    atual = R.ler_retrato(con, dt.datetime.fromisoformat(b["observado_em"]), "PA", MUNICIPIO, cat)
    assert len(antigo.dados["acc"]) == 1 and atual.dados["acc"].empty
    assert len(atual.dados["biomas"]) == 1  # não mistura o retrato do outro município
    assert "nome_pessoa" not in atual.dados["car"]
    n = con.execute(
        text(f"select count(*) from {esquema}.car_imovel where cod_municipio_ibge=:m"), {"m": MUNICIPIO}
    ).scalar_one()
    assert n == 1
    p = tmp_path / "catalogo.json"
    A.salvar_catalogo(con, MUNICIPIO, p)
    assert R.ler_catalogo(p) == cat
    before = con.execute(text(f"select count(*) from {esquema}.coleta")).scalar_one()
    dados["regeneracao"].loc[0, "car_hash"] = "errado"
    with pytest.raises(R.HistoricoInsuficiente, match="mesma versão"):
        A.arquivar(con, dados, "PA", MUNICIPIO)
    assert con.execute(text(f"select count(*) from {esquema}.coleta")).scalar_one() == before


def test_le_pasta_completa_sem_carregar_colunas_pessoais(tmp_path):
    from raiz.aprendizado.arquivo_historico import ler_pasta

    with pytest.raises(R.HistoricoInsuficiente, match="incompleto"):
        ler_pasta(tmp_path)
    for nome, df in _dados().items():
        df["nome_pessoa"] = "campo que não vai ao treino"
        df.to_parquet(tmp_path / f"{nome}.parquet", index=False)
    dados = ler_pasta(tmp_path)
    assert set(dados) == set(R.FONTES)
    assert all("nome_pessoa" not in d.columns for d in dados.values())
