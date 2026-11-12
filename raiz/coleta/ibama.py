"""Embargos do Ibama incrementais (E1 passo 4).

- Pedido condicional (If-None-Match com o ETag guardado): 304 = nada a fazer.
- Na entrada, saem as colunas de nome, CPF/CNPJ, contato e endereço (privacidade.remover_colunas_pessoais) e todo CPF
  ou CNPJ que sobrar em texto livre é mascarado. Nada pessoal chega ao disco depois disto.
- Espelho por município (chave SEQ_TAD; o hash da linha cobre DAT_ULT_ALTERACAO e DAT_ULT_ALTER_GEOM): só municípios
  com termo novo, alterado ou retirado são regravados e entram no histórico scd2 (bruto.ibama_embargo).
- O CSV limpo e o ETag vão para o cache do motor (cache/termo_de_embargo.csv e .etag): o motor passa a ler a versão
  sem dado pessoal e não baixa de novo.
"""

from __future__ import annotations

import datetime as dt
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
import shapely
from sqlalchemy import Connection

from raiz.coleta.espelho import Diferenca, Espelho
from raiz.coleta.manifesto import carregar
from raiz.coleta.replicacao import atualizar, estado, evento
from raiz.privacidade import mascarar, remover_colunas_pessoais

FONTE = "ibama_embargos"
RECORTE = "BR"


@dataclass
class ResultadoIbama:
    acao: str  # sem_mudanca | atualizado
    linhas: int = 0
    removidas: list[str] = field(default_factory=list)
    municipios: dict[int, Diferenca] = field(default_factory=dict)


def _geometria(wkt: str | None):
    if not isinstance(wkt, str) or not wkt.strip():
        return None
    try:
        g = shapely.from_wkt(wkt)
        return g if g is not None and not g.is_empty else None
    except shapely.errors.GEOSException:
        return None


def limpar(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    df, fora = remover_colunas_pessoais(df)
    texto = [c for c in df.columns if df[c].dtype == object or pd.api.types.is_string_dtype(df[c])]
    for c in texto:
        if c != "GEOM_AREA_EMBARGADA":
            df[c] = df[c].map(lambda v: mascarar(v) if isinstance(v, str) else v)
    return df, fora


def coletar(
    s: requests.Session, con: Connection, espelho: Espelho, cache_motor: Path | None = None, url: str | None = None
) -> ResultadoIbama:
    url = url or carregar().fonte(FONTE).url
    agora = dt.datetime.now(dt.UTC)
    e = estado(con, FONTE, RECORTE)
    cab = {"If-None-Match": e.etag} if e is not None and e.etag else {}
    with s.get(url, headers=cab, stream=True, timeout=1800) as r:
        if r.status_code == 304:
            atualizar(con, FONTE, RECORTE, verificado_em=agora, sujo=False)
            evento(con, FONTE, RECORTE, "sem_mudanca")
            return ResultadoIbama("sem_mudanca")
        r.raise_for_status()
        etag, last_mod = r.headers.get("ETag"), r.headers.get("Last-Modified")
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            for bloco in r.iter_content(1 << 20):
                tmp.write(bloco)
    try:
        bruto = pd.read_csv(tmp.name, sep=";", dtype=str, encoding="utf-8-sig", on_bad_lines="skip")
    finally:
        os.unlink(tmp.name)  # o arquivo original (com nomes e CPF) não fica em disco
    df, fora = limpar(bruto)
    del bruto
    res = ResultadoIbama("atualizado", len(df), fora)
    if cache_motor is not None:
        _cache_motor(df, cache_motor, etag)

    df["cod_mun"] = pd.to_numeric(df.get("COD_MUNICIPIO"), errors="coerce")
    df["uf_"] = df.get("UF", pd.Series("XX", index=df.index)).fillna("XX").astype(str).str.upper()
    vistos = set()
    for (uf, cod), parte in df.dropna(subset=["cod_mun"]).groupby(["uf_", "cod_mun"]):
        geoms = [_geometria(w) for w in parte.get("GEOM_AREA_EMBARGADA", [None] * len(parte))]
        g = gpd.GeoDataFrame(parte.drop(columns=["cod_mun", "uf_"]), geometry=geoms, crs=4674)
        _gravar(con, espelho, res, uf, int(cod), g)
        vistos.add((uf, int(cod)))
    # município que perdeu o último termo some do CSV: o espelho dele precisa registrar a retirada
    colunas = [c for c in df.columns if c not in ("cod_mun", "uf_")]
    for f in (espelho.raiz / "ibama").glob("*/*.parquet"):
        uf, cod = f.parent.name, int(f.stem)
        if (uf, cod) not in vistos:
            _gravar(con, espelho, res, uf, cod, gpd.GeoDataFrame(columns=colunas, geometry=[], crs=4674))
    atualizar(
        con,
        FONTE,
        RECORTE,
        etag=etag,
        last_modified=last_mod,
        contagem=len(df),
        sujo=False,
        tentativas=0,
        ultimo_erro=None,
        verificado_em=agora,
        coletado_em=agora,
    )
    return res


def _gravar(con: Connection, espelho: Espelho, res: ResultadoIbama, uf: str, cod: int, g: gpd.GeoDataFrame) -> None:
    dif = espelho.gravar("ibama", uf, cod, g, "SEQ_TAD")
    if dif.mudou:
        res.municipios[cod] = dif
        for tipo, chaves in (("novos", dif.novos), ("mudaram", dif.mudaram), ("sumiram", dif.sumiram)):
            if chaves:
                evento(con, FONTE, f"{uf}/{cod}", tipo, len(chaves), {"exemplos": chaves[:20]})


def _cache_motor(df: pd.DataFrame, pasta: Path, etag: str | None) -> None:
    """Grava o CSV já limpo no formato que motor/raiz_estado.embargos() lê (separador ;, utf-8-sig)."""
    pasta.mkdir(parents=True, exist_ok=True)
    f = pasta / "termo_de_embargo.csv"
    tmp = f.with_suffix(f".{os.getpid()}.tmp")
    df.drop(columns=["cod_mun", "uf_"], errors="ignore").to_csv(tmp, sep=";", index=False, encoding="utf-8-sig")
    os.replace(tmp, f)
    if etag:
        (pasta / "termo_de_embargo.etag").write_text(etag)
