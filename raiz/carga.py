"""Carga das saídas do motor (saida/<UF>/) no banco, pelo contrato de colunas.

Unidade de carga = um município (imoveis_<mun>.csv e o que houver junto: filtros, extras, direto, ajustes, alertas,
certidoes, geo_<mun>.parquet). Cada município vira uma rodada; recarregar os mesmos arquivos não duplica nada
(a rodada é identificada pelo hash dos arquivos). O resumo da UF é uma rodada à parte.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from psycopg.types.json import Jsonb
from sqlalchemy import Connection, text

from raiz import contrato
from raiz.versoes import motor_commit, motor_versao, regras_versao, sha256_arquivo

log = logging.getLogger(__name__)

TIPOS_MUNICIPIO = ("imoveis", "filtros", "extras", "direto", "ajustes", "alertas", "certidoes")


@dataclass
class ResultadoCarga:
    rodada_id: int
    nova: bool
    tipo: str
    uf: str
    cod_municipio: int | None
    imoveis: int = 0
    colunas_novas: list[str] = field(default_factory=list)
    colunas_faltando: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    lote_previsoes: str | None = None  # lote de previsões congeladas desta rodada
    previsoes_novas: int = 0


def _py(v):
    """Valor do pandas/numpy para Python puro (o COPY do psycopg não conhece tipos do numpy)."""
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, np.generic):
        v = v.item()
        return None if isinstance(v, float) and math.isnan(v) else v
    return v


def _copy(con: Connection, tabela: str, colunas: list[str], linhas) -> int:
    raw = con.connection.driver_connection
    n = 0
    with raw.cursor() as cur, cur.copy(f"COPY {tabela} ({', '.join(colunas)}) FROM STDIN") as cp:
        for linha in linhas:
            cp.write_row(linha)
            n += 1
    return n


def _linhas_leitura(rodada_id: int, leitura: contrato.Leitura, extra_inicio: tuple = ()):
    cols = list(leitura.tipadas.columns)
    valores = [leitura.tipadas[c].tolist() for c in cols]
    for i, attr in enumerate(leitura.atributos):
        yield (rodada_id, *extra_inicio, *(_py(v[i]) for v in valores), Jsonb(attr))


def arquivos_do_municipio(pasta: Path, cod: int) -> dict[str, Path]:
    achados = {t: pasta / f"{t}_{cod}.csv" for t in TIPOS_MUNICIPIO}
    achados["geo"] = pasta / f"geo_{cod}.parquet"
    return {t: p for t, p in achados.items() if p.exists()}


def municipios_na_pasta(pasta: Path) -> list[int]:
    return sorted(
        int(m.group(1)) for p in pasta.glob("imoveis_*.csv") if (m := re.fullmatch(r"imoveis_(\d+)\.csv", p.name))
    )


def _hash_entradas(arquivos: dict[str, Path]) -> tuple[dict, str]:
    hashes = {p.name: sha256_arquivo(p) for p in arquivos.values()}
    junto = "\n".join(f"{k}:{v}" for k, v in sorted(hashes.items()))
    return hashes, hashlib.sha256(junto.encode()).hexdigest()


def _rodada_existente(con: Connection, h: str):
    return con.execute(text("select id, tipo, uf, cod_municipio, imoveis from funil.rodada where hash_entradas=:h"),
                       {"h": h}).first()  # fmt: skip


def _nova_rodada(con, tipo, uf, cod, origem, hashes, h, data_corte, motor_confirmado) -> int:
    return con.execute(
        text("""insert into funil.rodada (tipo, uf, cod_municipio, origem, arquivos, hash_entradas, motor_versao,
                motor_versao_confirmada, motor_commit, regras_versao, data_corte)
                values (:tipo, :uf, :cod, :origem, :arquivos, :h, :mv, :mc, :commit, :rv, :dc) returning id"""),
        dict(tipo=tipo, uf=uf, cod=cod, origem=origem, arquivos=json.dumps(hashes), h=h, mv=motor_versao(),
             mc=motor_confirmado, commit=motor_commit(), rv=regras_versao(), dc=data_corte),
    ).scalar_one()  # fmt: skip


def _fechar_rodada(con, rodada_id, imoveis, leituras: list[contrato.Leitura]) -> tuple[list, list, list]:
    novas = sorted({f"{lt.tipo}.{c}" for lt in leituras for c in lt.colunas_novas})
    faltando = sorted({f"{lt.tipo}.{c}" for lt in leituras for c in lt.colunas_faltando})
    avisos = [f"{lt.tipo}: {a}" for lt in leituras for a in lt.avisos]
    con.execute(text("update funil.rodada set imoveis=:n, colunas_novas=:cn, colunas_faltando=:cf, avisos=:av "
                     "where id=:id"), dict(n=imoveis, cn=novas, cf=faltando, av=avisos, id=rodada_id))  # fmt: skip
    if novas:
        log.warning("colunas novas do motor (guardadas em atributos; documentar em docs/colunas.md): %s", novas)
    for a in avisos:
        log.warning(a)
    return novas, faltando, avisos


def _carregar_geo(con: Connection, arquivo: Path) -> int:
    import geopandas as gpd
    import shapely

    g = gpd.read_parquet(arquivo)
    if g.crs is None:
        raise ValueError(f"{arquivo.name} sem sistema de coordenadas")
    g = g.to_crs(4674)
    geoms = shapely.normalize(g.geometry.values)
    wkb = shapely.to_wkb(geoms, output_dimension=2)
    linhas = ((c, w, hashlib.sha256(w).hexdigest()[:32]) for c, w in zip(g.cod_imovel.astype(str), wkb, strict=True))
    con.execute(text("create temp table _geo (cod_imovel text, wkb bytea, geom_hash text) on commit drop"))
    n = _copy(con, "_geo", ["cod_imovel", "wkb", "geom_hash"], linhas)
    con.execute(
        text("""
        insert into funil.imovel (cod_imovel, geom, geom_hash)
        select cod_imovel, ST_Multi(ST_CollectionExtract(ST_GeomFromWKB(wkb, 4674), 3)), geom_hash from _geo
        on conflict (cod_imovel) do update
        set geom = excluded.geom, geom_hash = excluded.geom_hash, atualizado_em = now()
        where funil.imovel.geom_hash is distinct from excluded.geom_hash""")
    )
    con.execute(text("drop table _geo"))
    return n


def carregar_municipio(con: Connection, pasta: str | Path, cod: int, data_corte: dt.date | None = None,
                       origem: str | None = None, motor_confirmado: bool = False) -> ResultadoCarga:  # fmt: skip
    """Carrega um município numa transação já aberta (con). Idempotente pelo hash dos arquivos."""
    pasta = Path(pasta)
    arquivos = arquivos_do_municipio(pasta, cod)
    if "imoveis" not in arquivos:
        raise FileNotFoundError(f"falta imoveis_{cod}.csv em {pasta}")
    hashes, h = _hash_entradas(arquivos)
    if ex := _rodada_existente(con, h):
        return ResultadoCarga(ex.id, False, ex.tipo, ex.uf, ex.cod_municipio, ex.imoveis or 0)

    leituras = {t: contrato.ler(p, t) for t, p in arquivos.items() if t != "geo"}
    im = leituras["imoveis"]
    ufs = im.tipadas["uf"].dropna().unique().tolist()
    uf = ufs[0] if ufs else pasta.name.upper()
    rid = _nova_rodada(con, "municipio", uf, cod, origem or str(pasta), hashes, h, data_corte or dt.date.today(),
                       motor_confirmado)  # fmt: skip

    cols = ["rodada_id"] + list(im.tipadas.columns) + ["atributos"]
    n = _copy(con, "funil.resultado_imovel", cols, _linhas_leitura(rid, im))
    if "filtros" in leituras:
        lf = leituras["filtros"]
        _copy(con, "funil.filtro_imovel", ["rodada_id", *lf.tipadas.columns, "atributos"], _linhas_leitura(rid, lf))
    for t in contrato.COMPLEMENTOS:
        if t in leituras:
            lt = leituras[t]
            linhas = ((rid, t, c, Jsonb(a)) for c, a in zip(lt.tipadas["cod_imovel"], lt.atributos, strict=True))
            _copy(con, "funil.complemento_imovel", ["rodada_id", "tipo", "cod_imovel", "atributos"], linhas)
    if "certidoes" in leituras:
        lc = leituras["certidoes"]
        _copy(con, "titulo.certidao_alvo", ["rodada_id", *lc.tipadas.columns, "atributos"], _linhas_leitura(rid, lc))

    con.execute(text("""
        insert into funil.imovel (cod_imovel, uf, cod_municipio_ibge)
        select cod_imovel, uf, cod_municipio_ibge from funil.resultado_imovel where rodada_id = :rid
        on conflict (cod_imovel) do update set uf = excluded.uf, cod_municipio_ibge = excluded.cod_municipio_ibge
        where (funil.imovel.uf, funil.imovel.cod_municipio_ibge)
              is distinct from (excluded.uf, excluded.cod_municipio_ibge)"""), {"rid": rid})  # fmt: skip
    if "geo" in arquivos:
        _carregar_geo(con, arquivos["geo"])

    novas, faltando, avisos = _fechar_rodada(con, rid, n, list(leituras.values()))
    log.info("município %s: rodada %s com %s imóveis", cod, rid, n)
    return ResultadoCarga(rid, True, "municipio", uf, cod, n, novas, faltando, avisos)


def carregar_resumo(con: Connection, arquivo: str | Path, uf: str, data_corte: dt.date | None = None,
                    origem: str | None = None) -> ResultadoCarga:  # fmt: skip
    arquivo = Path(arquivo)
    hashes, h = _hash_entradas({"resumo": arquivo})
    if ex := _rodada_existente(con, h):
        return ResultadoCarga(ex.id, False, ex.tipo, ex.uf, None, ex.imoveis or 0)
    lr = contrato.ler(arquivo, "resumo")
    rid = _nova_rodada(con, "resumo_uf", uf.upper(), None, origem or str(arquivo), hashes, h,
                       data_corte or dt.date.today(), False)  # fmt: skip
    n = _copy(con, "funil.resumo_municipio", ["rodada_id", *lr.tipadas.columns, "atributos"], _linhas_leitura(rid, lr))
    novas, faltando, avisos = _fechar_rodada(con, rid, n, [lr])
    return ResultadoCarga(rid, True, "resumo_uf", uf.upper(), None, n, novas, faltando, avisos)


def carregar_pasta(engine, pasta: str | Path, data_corte: dt.date | None = None, motor_confirmado: bool = False,
                   congelar: bool = True) -> list[ResultadoCarga]:  # fmt: skip
    """Carrega todos os municípios e o resumo de uma pasta saida/<UF>/ (cada município na sua transação) e congela
    as previsões do motor de cada rodada (E8 passo 1)."""
    from raiz.aprendizado.congelar import congelar_rodada

    pasta = Path(pasta)
    res = []
    for cod in municipios_na_pasta(pasta):
        with engine.begin() as con:
            r = carregar_municipio(con, pasta, cod, data_corte, motor_confirmado=motor_confirmado)
            if congelar:
                r.lote_previsoes, novo, n = congelar_rodada(con, r.rodada_id)
                r.previsoes_novas = n if novo else 0
            res.append(r)
    for p in sorted(pasta.glob("resumo_*.csv")):
        m = re.fullmatch(r"resumo_([A-Za-z]{2})\.csv", p.name)
        if m:
            with engine.begin() as con:
                res.append(carregar_resumo(con, p, m.group(1), data_corte))
    return res
