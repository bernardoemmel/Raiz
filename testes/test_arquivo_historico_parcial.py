"""Capturas automáticas parciais não transformam fonte ausente em fonte vazia."""

import datetime as dt
import uuid

import geopandas as gpd
import pandas as pd
import pytest
from sqlalchemy import event, text

from raiz.aprendizado import arquivo_historico as A
from raiz.aprendizado.reexecucao import FONTES, FONTES_MOTOR, HistoricoInsuficiente
from testes.test_reexecucao_folds import MUNICIPIO, _dados


def _base():
    dados = _dados()
    return {n: dados[n] for n in FONTES_MOTOR}


def _ibama():
    return pd.DataFrame(
        [
            {
                "seq_tad": "termo-teste",
                "cod_municipio": str(MUNICIPIO),
                "sit_cancelado": "N",
                "sit_desembargo": "N",
                "geom_area_embargada": _base()["car"].geometry.iloc[0].wkt,
            }
        ]
    )


def _entrada():
    return pd.DataFrame(
        [
            {
                "cod_imovel": "PA-TESTE-ENTRADA",
                "atributos": {"pasto_ha": 10.5, "nome_dono": "campo pessoal que deve sair"},
                "contexto": {"pasto_baixo_vigor_ha": 3.0, "nome_pessoa": "campo que deve sair"},
            }
        ]
    )


def test_manual_exige_base_mas_extras_sao_opcionais():
    dados = _base()
    assert set(A._normalizar(dados)) == set(FONTES_MOTOR)
    with pytest.raises(HistoricoInsuficiente, match="todas as fontes"):
        A._normalizar({"car": dados["car"]})
    assert set(A._normalizar({"car": dados["car"]}, exigir_completo=False)) == {"car"}
    with pytest.raises(HistoricoInsuficiente, match="nenhuma fonte"):
        A._normalizar({}, exigir_completo=False)
    with pytest.raises(HistoricoInsuficiente, match="desconhecidas"):
        A._normalizar({"inventada": pd.DataFrame()}, exigir_completo=False)
    vazio = {"car": dados["car"].iloc[0:0]}
    assert A._normalizar(vazio, exigir_completo=False) == {"car": []}
    with pytest.raises(HistoricoInsuficiente, match="linhas"):
        A._normalizar({**dados, **vazio})


def test_regeneracao_parcial_exige_car_correspondente_mas_nao_zonal_de_todos():
    dados = _base()
    with pytest.raises(HistoricoInsuficiente, match="exige o CAR"):
        A._normalizar({"regeneracao": dados["regeneracao"]}, exigir_completo=False)
    vazio = dados["regeneracao"].iloc[0:0]
    normalizado = A._normalizar({"car": dados["car"], "regeneracao": vazio}, exigir_completo=False)
    assert normalizado["car"] and not normalizado["regeneracao"]
    dados["regeneracao"].loc[0, "car_hash"] = "outra-versao"
    with pytest.raises(HistoricoInsuficiente, match="mesma versão"):
        A._normalizar({"car": dados["car"], "regeneracao": dados["regeneracao"]}, exigir_completo=False)


def test_ler_pasta_base_obrigatoria_e_entrada_opcional(tmp_path):
    for nome, df in _base().items():
        df.to_parquet(tmp_path / f"{nome}.parquet", index=False)
    assert set(A.ler_pasta(tmp_path)) == set(FONTES_MOTOR)
    _entrada().to_parquet(tmp_path / "entrada_flag.parquet", index=False)
    assert set(A.ler_pasta(tmp_path)) == {*FONTES_MOTOR, "entrada_flag"}
    (tmp_path / "car.parquet").unlink()
    with pytest.raises(HistoricoInsuficiente, match="falta car"):
        A.ler_pasta(tmp_path)


@pytest.mark.banco
def test_catalogo_por_fonte_ausencia_preserva_vazio_fecha(con, monkeypatch):
    esquema = f"parcial_{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(A, "ESQUEMA", esquema)
    dados = _base()
    a = A.arquivar(con, {"car": dados["car"]}, "PA", MUNICIPIO, exigir_completo=False)
    b = A.arquivar(con, {"ibama": _ibama()}, "PA", MUNICIPIO, exigir_completo=False)
    c = A.arquivar(con, {"car": dados["car"]}, "PA", MUNICIPIO, exigir_completo=False)
    assert not a["motor_completo"] and a["contagens"] == {"car": 1}
    assert set(a["faltantes"]) == set(FONTES) - {"car"}
    fontes = A.catalogo(con, MUNICIPIO)
    assert set(fontes) == {"car", "ibama"}
    assert fontes["car"].desde == dt.datetime.fromisoformat(a["observado_em"])
    assert fontes["car"].ate == dt.datetime.fromisoformat(c["observado_em"])
    assert fontes["ibama"].desde == fontes["ibama"].ate == dt.datetime.fromisoformat(b["observado_em"])
    # Não houve captura SIGEF; nenhuma tabela ou cobertura foi inventada.
    assert con.execute(text("select to_regclass(:t)"), {"t": f"{esquema}.sigef_parcela"}).scalar() is None
    assert con.execute(text(f"select count(*) from {esquema}.ibama_embargo where _dlt_valid_to is null")).scalar() == 1
    retirada = A.arquivar(con, {"ibama": _ibama().iloc[0:0]}, "PA", MUNICIPIO, exigir_completo=False)
    assert retirada["contagens"] == {"ibama": 0}
    assert con.execute(text(f"select count(*) from {esquema}.ibama_embargo where _dlt_valid_to is null")).scalar() == 0
    assert con.execute(text(f"select count(*) from {esquema}.car_imovel")).scalar() == 1
    fontes = A.catalogo(con, MUNICIPIO)
    assert fontes["car"].ate == dt.datetime.fromisoformat(c["observado_em"])
    assert fontes["ibama"].ate == dt.datetime.fromisoformat(retirada["observado_em"])
    # Retirada observada do último CAR também é diferente de não consultar o CAR.
    A.arquivar(con, {"car": dados["car"].iloc[0:0]}, "PA", MUNICIPIO, exigir_completo=False)
    assert con.execute(text(f"select count(*) from {esquema}.car_imovel where _dlt_valid_to is null")).scalar() == 0


@pytest.mark.banco
def test_entradas_json_saneadas_e_scd2_sem_duplicar(con, monkeypatch):
    esquema = f"json_fold_{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(A, "ESQUEMA", esquema)
    dados = {"entrada_flag": _entrada()}
    a = A.arquivar(con, dados, "PA", MUNICIPIO, exigir_completo=False)
    b = A.arquivar(con, dados, "PA", MUNICIPIO, exigir_completo=False)
    assert a["manifesto_hash"] == b["manifesto_hash"]
    tabela = f"{esquema}.{FONTES['entrada_flag'].tabela}"
    rows = con.execute(text(f"select atributos, contexto, jsonb_typeof(atributos) as tipo from {tabela}")).all()
    assert len(rows) == 1 and rows[0].tipo == "object"
    assert rows[0].atributos == {"pasto_ha": 10.5}
    assert rows[0].contexto == {"pasto_baixo_vigor_ha": 3.0}
    dados["entrada_flag"].at[0, "atributos"] = {"pasto_ha": 11.0}
    c = A.arquivar(con, dados, "PA", MUNICIPIO, exigir_completo=False)
    rows = con.execute(
        text(f"select atributos, _dlt_valid_from, _dlt_valid_to from {tabela} order by _dlt_valid_from")
    ).all()
    assert len(rows) == 2 and rows[0]._dlt_valid_to == rows[1]._dlt_valid_from
    assert rows[1]._dlt_valid_to is None and rows[1].atributos["pasto_ha"] == 11
    assert c["manifesto_hash"] != a["manifesto_hash"]
    assert set(A.catalogo(con, MUNICIPIO)) == {"entrada_flag"}
    dados["entrada_flag"].at[0, "contexto"] = "não é um objeto"
    with pytest.raises(HistoricoInsuficiente, match="objetos JSON"):
        A.arquivar(con, dados, "PA", MUNICIPIO, exigir_completo=False)
    assert con.execute(text(f"select count(*) from {esquema}.coleta")).scalar() == 3


@pytest.mark.banco
def test_insercoes_em_lotes_preservam_todas_as_linhas(con, monkeypatch):
    esquema = f"lotes_fold_{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(A, "ESQUEMA", esquema)
    molde = _base()["car"]
    linhas = pd.concat([molde] * 1203, ignore_index=True)
    linhas["cod_imovel"] = [f"CAR-TESTE-{i}" for i in range(len(linhas))]
    linhas["_hash"] = [f"car-hash-{i}" for i in range(len(linhas))]
    linhas = gpd.GeoDataFrame(linhas, geometry="geometry", crs=4674)
    lotes = []

    def registrar(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith(f"insert into {esquema}.car_imovel"):
            lotes.append(len(parameters) if executemany else 1)

    event.listen(con, "before_cursor_execute", registrar)
    try:
        A.arquivar(con, {"car": linhas}, "PA", MUNICIPIO, exigir_completo=False)
    finally:
        event.remove(con, "before_cursor_execute", registrar)
    assert lotes == [500, 500, 203]
    assert con.execute(text(f"select count(*) from {esquema}.car_imovel")).scalar() == len(linhas)
