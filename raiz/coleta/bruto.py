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
import re

import dlt
import geopandas as gpd
import pandas as pd
import shapely
from dlt.destinations.adapters import postgres_adapter
from sqlalchemy import Connection, create_engine, text
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
    textos = como_texto.agg("|".join, axis=1) if estaveis and len(df) else pd.Series([""] * len(df), index=df.index)
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


def carregar(
    tabela: str,
    df: pd.DataFrame,
    extraido_em: dt.datetime,
    chave: str,
    url: str | None = None,
    *,
    cod_municipio: int | None = None,
) -> dict:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", tabela):
        raise ValueError("nome de tabela inválido")
    if df.empty:
        if cod_municipio is None:
            raise ValueError("snapshot vazio exige cod_municipio explícito")
    else:
        municipios = set(df["cod_municipio_ibge"].dropna().astype(int))
        if len(municipios) != 1 or df["cod_municipio_ibge"].isna().any():
            raise ValueError("cada snapshot deve conter exatamente um município")
        if cod_municipio is not None and municipios != {int(cod_municipio)}:
            raise ValueError("município do snapshot difere do recorte declarado")
    p = pipeline(url)
    pendentes = _drenar_pendentes(p)
    if df.empty:
        resultado = _encerrar_municipio(tabela, int(cod_municipio), extraido_em, url)
        resultado["pacotes"] = pendentes
        return resultado
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
    info = p.run(postgres_adapter(recurso, geometry="geom", srid=4674))
    info.raise_on_failed_jobs()
    if p.has_pending_data:
        raise RuntimeError("histórico ainda tem pacotes pendentes após a carga")
    return {"pacotes": pendentes + len(info.load_packages), "linhas": len(df)}


def _drenar_pendentes(p) -> int:
    """run(novos_dados) ignora os dados novos quando há pendências. Resolva-as antes, inclusive do vazio.

    A primeira chamada também sincroniza o estado com o destino. Falha ou ausência de progresso impedem que o
    hash do snapshot atual seja declarado como carregado por sincronizar_historico.
    """
    pacotes = 0
    while True:
        antes = (tuple(p.list_extracted_load_packages()), tuple(p.list_normalized_load_packages()))
        info = p.run()
        if info is not None:
            info.raise_on_failed_jobs()
            pacotes += len(info.load_packages)
        if not p.has_pending_data:
            return pacotes
        depois = (tuple(p.list_extracted_load_packages()), tuple(p.list_normalized_load_packages()))
        if antes == depois:
            raise RuntimeError("histórico não avançou ao resolver pacotes pendentes")


def _encerrar_municipio(tabela: str, cod: int, extraido_em: dt.datetime, url: str | None) -> dict:
    """O dlt não produz merge_key para um lote vazio: encerra só o recorte explicitamente declarado.

    Não cria uma linha fictícia nem toca outro município. É idempotente, inclusive antes da primeira carga.
    """
    eng = create_engine(url or config().banco_url)
    try:
        with eng.begin() as con:
            if not con.execute(text("select to_regclass(:t)"), {"t": f"{DATASET}.{tabela}"}).scalar():
                return {"pacotes": 0, "linhas": 0, "encerradas": 0}
            posteriores = con.execute(
                text(
                    f"select count(*) from {DATASET}.{tabela} where cod_municipio_ibge = :cod "
                    "and _dlt_valid_to is null and _dlt_valid_from > :data"
                ),
                {"cod": cod, "data": extraido_em},
            ).scalar()
            if posteriores:
                raise ValueError("snapshot vazio anterior à versão vigente do município")
            r = con.execute(
                text(
                    f"update {DATASET}.{tabela} set _dlt_valid_to = :data "
                    "where cod_municipio_ibge = :cod and _dlt_valid_to is null"
                ),
                {"cod": cod, "data": extraido_em},
            )
            return {"pacotes": 0, "linhas": 0, "encerradas": r.rowcount}
    finally:
        eng.dispose()


def garantir_view(con: Connection, tabela: str) -> None:
    con.execute(
        text(
            f"create or replace view {DATASET}.{tabela}_vigente as "
            f"select * from {DATASET}.{tabela} where _dlt_valid_to is null"
        )
    )
