"""Histórico no PostGIS (esquema bruto) com scd2 do dlt (Apache-2.0) — E1 passo 4.

- Cada carga é o retrato completo de UM município (merge_key = cod_municipio_ibge): o dlt fecha (_dlt_valid_to) só
  as linhas daquele município que sumiram ou mudaram, e abre as novas. Município não carregado não é tocado.
- boundary_timestamp = momento da extração (não o da carga): o histórico diz quando a Raíz viu a mudança.
- row_version = hash próprio (campos estáveis + geometria normalizada), o mesmo critério do espelho.
- Geometria em WKT convertida em PostGIS (postgres_adapter), SRID 4674.
- View <tabela>_vigente = versão atual (_dlt_valid_to nulo). A E8 lê "como estava" filtrando as duas datas.
"""

from __future__ import annotations

import datetime as dt
import hashlib

import dlt
import geopandas as gpd
import pandas as pd
import shapely
from dlt.destinations.adapters import postgres_adapter
from sqlalchemy import Connection, text
from sqlalchemy.engine import make_url

from raiz import RAIZ_REPO
from raiz.config import config

DATASET = "bruto"
# estado local do dlt (pacotes pendentes são refeitos na próxima rodada); os testes usam uma pasta temporária
PASTA_DLT = RAIZ_REPO / "dados" / "dlt"


def _credenciais(url: str | None) -> str:
    return make_url(url or config().banco_url).set(drivername="postgresql").render_as_string(hide_password=False)


def pipeline(url: str | None = None, nome: str = "raiz_bruto"):
    return dlt.pipeline(
        pipeline_name=nome,
        destination=dlt.destinations.postgres(credentials=_credenciais(url)),
        dataset_name=DATASET,
        pipelines_dir=str(PASTA_DLT),
    )


def linhas(g: gpd.GeoDataFrame, chave: str, cod_municipio: int, volateis: tuple[str, ...] = ()) -> pd.DataFrame:
    """Retrato do município pronto para o dlt: geometria em WKT, hash da linha e o município como merge_key."""
    df = pd.DataFrame(g.drop(columns="geometry"))
    from raiz.coleta.espelho import geometria_canonica
    from raiz.funil import grade

    geoms = [geometria_canonica(x) for x in g.geometry.values]
    estaveis = sorted(c for c in df.columns if c not in volateis)
    # pandas 3: astype(str) mantém o nulo como nulo; o hash precisa de texto em todas as células
    como_texto = pd.DataFrame({c: [("" if pd.isna(v) else str(v)) for v in df[c]] for c in estaveis}, index=df.index)
    textos = como_texto.agg("|".join, axis=1) if estaveis else pd.Series([""] * len(df), index=df.index)
    wkb = [b"" if x is None else shapely.to_wkb(x, output_dimension=2) for x in geoms]
    df["_hash"] = [hashlib.sha256(t.encode() + b"|" + w).hexdigest()[:32] for t, w in zip(textos, wkb, strict=True)]
    df["geom"] = [None if x is None else shapely.to_wkt(x, rounding_precision=-1) for x in geoms]
    df["cod_municipio_ibge"] = int(cod_municipio)
    # chave de bloco de 0,5 grau (raiz/funil/grade.py); fora do hash, que só olha o dado da fonte
    graus = g.geometry.values if g.crs is None or g.crs.is_geographic else g.geometry.to_crs(4674).values
    df["bloco"] = grade.chaves(graus)
    for c in df.columns:  # datas como texto ISO (o dlt infere o tipo a partir do primeiro lote)
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = df[c].astype(str)
    return df.reset_index(drop=True)


def carregar(tabela: str, df: pd.DataFrame, extraido_em: dt.datetime, chave: str, url: str | None = None) -> dict:
    recurso = dlt.resource(
        df.to_dict("records"),
        name=tabela,
        primary_key=chave,
        write_disposition={
            "disposition": "merge",
            "strategy": "scd2",
            "boundary_timestamp": extraido_em,
            "row_version_column_name": "_hash",
        },
        columns={"cod_municipio_ibge": {"merge_key": True, "data_type": "bigint"}},
    )
    info = pipeline(url).run(postgres_adapter(recurso, geometry="geom", srid=4674))
    return {"pacotes": len(info.load_packages), "linhas": len(df)}


def garantir_view(con: Connection, tabela: str) -> None:
    con.execute(
        text(
            f"create or replace view {DATASET}.{tabela}_vigente as "
            f"select * from {DATASET}.{tabela} where _dlt_valid_to is null"
        )
    )
