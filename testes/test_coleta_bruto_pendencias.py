"""Um pacote dlt antigo pendente nunca se passa pelo snapshot atual, inclusive quando este está vazio."""

import datetime as dt

import dlt
import geopandas as gpd
import pytest
from dlt.destinations.adapters import postgres_adapter
from shapely.geometry import box
from sqlalchemy import create_engine, text

from raiz.coleta import bruto

pytestmark = pytest.mark.banco


@pytest.mark.parametrize("vazio", [False, True])
def test_resolve_pacote_antigo_antes_do_snapshot_atual(banco_url, tmp_path, monkeypatch, vazio):
    monkeypatch.setattr(bruto, "PASTA_DLT", tmp_path / "dlt")
    eng = create_engine(banco_url)
    with eng.begin() as con:
        con.execute(text("drop schema bruto cascade"))
        con.execute(text("create schema bruto"))
    g = gpd.GeoDataFrame({"seq_tad": ["1"], "versao": ["antiga"]}, geometry=[box(0, 0, 1, 1)], crs=4674)
    antiga = bruto.linhas(g, "seq_tad", 1504950)
    t1, t2 = dt.datetime(2026, 11, 1, tzinfo=dt.UTC), dt.datetime(2026, 11, 2, tzinfo=dt.UTC)
    recurso = dlt.resource(
        antiga.to_dict("records"),
        name="ibama_embargo",
        primary_key="seq_tad",
        write_disposition={
            "disposition": "merge",
            "strategy": "scd2",
            "boundary_timestamp": t1,
            "row_version_column_name": "_hash",
        },
        columns={"cod_municipio_ibge": {"merge_key": True, "data_type": "bigint"}},
    )
    p = bruto.pipeline(banco_url)
    p.extract(postgres_adapter(recurso, geometry="geom", srid=4674))
    assert p.has_pending_data  # simula interrupção real depois da extração, antes da carga
    atual = bruto.linhas(g.iloc[:0] if vazio else g.assign(versao="nova"), "seq_tad", 1504950)
    bruto.carregar("ibama_embargo", atual, t2, "seq_tad", banco_url, cod_municipio=1504950)
    with eng.connect() as con:
        rows = con.execute(
            text("select versao, _dlt_valid_from, _dlt_valid_to from bruto.ibama_embargo order by _dlt_valid_from")
        ).all()
        assert rows == ([("antiga", t1, t2)] if vazio else [("antiga", t1, t2), ("nova", t2, None)])
    # Uma retomada subsequente não pode reabrir o termo já retirado nem reaplicar a versão velha.
    p = bruto.pipeline(banco_url)
    assert not p.has_pending_data
    assert p.run() is None
    with eng.connect() as con:
        assert con.execute(text("select count(*) from bruto.ibama_embargo where _dlt_valid_to is null")).scalar() == (
            0 if vazio else 1
        )
    eng.dispose()
