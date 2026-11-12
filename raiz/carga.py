"""Carga das saídas do motor (saida/<UF>/) no banco, pelo contrato de colunas.

Unidade de carga = um município (imoveis_<mun>.csv e o que houver junto: filtros, extras, extras_direto, direto,
ajustes, alertas, certidoes, geo_<mun>.parquet). Cada município vira uma rodada; recarregar os mesmos arquivos não
duplica nada (a rodada é identificada pelo hash dos arquivos). O resumo da UF é uma rodada à parte.
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
from raiz.busca import atualizar_vigente, municipios_do_resumo
from raiz.funil import grade
from raiz.versoes import motor_commit, motor_versao, regras_versao, sha256_arquivo

log = logging.getLogger(__name__)

TIPOS_MUNICIPIO = (
    "imoveis", "filtros", "extras", "extras_direto", "direto", "ajustes", "alertas", "certidoes", "flag", "ficha",
    "serie_uso",
)  # fmt: skip


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
    achados["mapbiomas"] = pasta / f"mapbiomas_{cod}.csv"  # motor/raiz_mapbiomas.py (colunas mb_*, opcionais)
    achados["camadas"] = pasta / f"camadas_{cod}.parquet"  # raiz/imovel_dados.py (polígonos dentro do imóvel)
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
    return con.execute(
        text("select id, tipo, uf, cod_municipio, imoveis from funil.rodada where hash_entradas=:h"), {"h": h}
    ).first()


def _nova_rodada(con, tipo, uf, cod, origem, hashes, h, data_corte, motor_confirmado) -> int:
    return con.execute(
        text("""insert into funil.rodada (tipo, uf, cod_municipio, origem, arquivos, hash_entradas, motor_versao,
                motor_versao_confirmada, motor_commit, regras_versao, data_corte)
                values (:tipo, :uf, :cod, :origem, :arquivos, :h, :mv, :mc, :commit, :rv, :dc) returning id"""),
        dict(
            tipo=tipo,
            uf=uf,
            cod=cod,
            origem=origem,
            arquivos=json.dumps(hashes),
            h=h,
            mv=motor_versao(),
            mc=motor_confirmado,
            commit=motor_commit(),
            rv=regras_versao(),
            dc=data_corte,
        ),
    ).scalar_one()


def _fechar_rodada(con, rodada_id, imoveis, leituras: list[contrato.Leitura], mb=None) -> tuple[list, list, list]:
    novas = sorted({f"{lt.tipo}.{c}" for lt in leituras for c in lt.colunas_novas})
    faltando = sorted({f"{lt.tipo}.{c}" for lt in leituras for c in lt.colunas_faltando})
    avisos = [f"{lt.tipo}: {a}" for lt in leituras for a in lt.avisos]
    if mb is not None:
        novas = sorted(set(novas) | {f"mapbiomas.{c}" for c in mb.indicadores_novos})
        avisos += [f"mapbiomas: {a}" for a in mb.avisos]
    con.execute(
        text("update funil.rodada set imoveis=:n, colunas_novas=:cn, colunas_faltando=:cf, avisos=:av where id=:id"),
        dict(n=imoveis, cn=novas, cf=faltando, av=avisos, id=rodada_id),
    )
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
    blocos = grade.chaves(geoms)
    linhas = (
        (c, w, hashlib.sha256(w).hexdigest()[:32], b)
        for c, w, b in zip(g.cod_imovel.astype(str), wkb, blocos, strict=True)
    )
    con.execute(text("create temp table _geo (cod_imovel text, wkb bytea, geom_hash text, bloco text) on commit drop"))
    n = _copy(con, "_geo", ["cod_imovel", "wkb", "geom_hash", "bloco"], linhas)
    con.execute(
        text("""
        insert into funil.imovel (cod_imovel, geom, geom_hash, bloco)
        select cod_imovel, ST_Multi(ST_CollectionExtract(ST_GeomFromWKB(wkb, 4674), 3)), geom_hash, bloco from _geo
        on conflict (cod_imovel) do update
        set geom = excluded.geom, geom_hash = excluded.geom_hash, bloco = excluded.bloco, atualizado_em = now()
        where (funil.imovel.geom_hash, funil.imovel.bloco) is distinct from (excluded.geom_hash, excluded.bloco)""")
    )
    con.execute(text("drop table _geo"))
    return n


def _carregar_camadas(con: Connection, arquivo: Path, cod: int, rid: int) -> int:
    """Polígonos dentro do imóvel (raiz/imovel_dados.py): troca os do município pelos novos."""
    import geopandas as gpd
    import shapely

    g = gpd.read_parquet(arquivo).to_crs(4674)
    con.execute(text("delete from geo.camada_imovel where cod_ibge = :c"), {"c": cod})
    linhas = (
        (str(c), cod, k, float(h), w, rid)
        for c, k, h, w in zip(
            g.cod_imovel, g.camada, g.ha, shapely.to_wkb(g.geometry.values, output_dimension=2), strict=True
        )
    )
    con.execute(
        text("create temp table _cam (cod_imovel text, cod_ibge bigint, camada text, ha float8, wkb bytea, rid bigint)"
             " on commit drop")
    )  # fmt: skip
    n = _copy(con, "_cam", ["cod_imovel", "cod_ibge", "camada", "ha", "wkb", "rid"], linhas)
    con.execute(
        text("""insert into geo.camada_imovel (cod_imovel, cod_ibge, camada, ha, geom, rodada_id)
                select cod_imovel, cod_ibge, camada, ha, ST_SetSRID(ST_GeomFromWKB(wkb), 4674), rid from _cam""")
    )
    con.execute(text("drop table _cam"))
    return n


def _carregar_serie_uso(con: Connection, arquivo: Path) -> int:
    """serie_uso_<mun>.csv (raiz/serie_uso.py): % de mata, pasto, lavoura e água por ano de cada imóvel."""
    df = pd.read_csv(arquivo)
    cods = df.cod_imovel.astype(str).unique().tolist()
    con.execute(text("delete from funil.serie_uso where cod_imovel = any(:c)"), {"c": cods})
    cols = ["cod_imovel", "ano", "mata_pct", "pasto_pct", "lavoura_pct", "agua_pct", "colecao"]
    df = df.reindex(columns=cols)
    return _copy(con, "funil.serie_uso", cols, (tuple(_py(v) for v in r) for r in df.itertuples(index=False)))


def _marcar_blocos(con: Connection, rid: int) -> None:
    """Copia a chave de bloco do imóvel (raiz/funil/grade.py, gravada com a geometria) para as tabelas da rodada."""
    for t in ("funil.resultado_imovel", "funil.filtro_imovel", "funil.mapbiomas_imovel"):
        con.execute(
            text(f"""update {t} r set bloco = i.bloco from funil.imovel i
                     where r.rodada_id = :rid and r.cod_imovel = i.cod_imovel and i.bloco is not null"""),
            {"rid": rid},
        )


def carregar_municipio(
    con: Connection,
    pasta: str | Path,
    cod: int,
    data_corte: dt.date | None = None,
    origem: str | None = None,
    motor_confirmado: bool = False,
) -> ResultadoCarga:
    """Carrega um município numa transação já aberta (con). Idempotente pelo hash dos arquivos."""
    pasta = Path(pasta)
    arquivos = arquivos_do_municipio(pasta, cod)
    if "imoveis" not in arquivos:
        raise FileNotFoundError(f"falta imoveis_{cod}.csv em {pasta}")
    hashes, h = _hash_entradas(arquivos)
    if ex := _rodada_existente(con, h):
        atualizar_vigente(con, cod)
        return ResultadoCarga(ex.id, False, ex.tipo, ex.uf, ex.cod_municipio, ex.imoveis or 0)

    leituras = {
        t: contrato.ler(p, t) for t, p in arquivos.items() if t not in ("geo", "mapbiomas", "camadas", "serie_uso")
    }
    im = leituras["imoveis"]
    ufs = im.tipadas["uf"].dropna().unique().tolist()
    uf = ufs[0] if ufs else pasta.name.upper()
    rid = _nova_rodada(
        con, "municipio", uf, cod, origem or str(pasta), hashes, h, data_corte or dt.date.today(), motor_confirmado
    )

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
    mb = contrato.ler_mapbiomas(arquivos["mapbiomas"]) if "mapbiomas" in arquivos else None
    if mb is not None and len(mb.longa):
        lg = mb.longa
        _copy(
            con,
            "funil.mapbiomas_imovel",
            ["rodada_id", "cod_imovel", "indicador", "ano", "valor_num", "valor_texto"],
            ((rid, c, i, _py(a), _py(v), _py(t)) for c, i, a, v, t in lg.itertuples(index=False, name=None)),
        )

    con.execute(
        text("""
        insert into funil.imovel (cod_imovel, uf, cod_municipio_ibge)
        select cod_imovel, uf, cod_municipio_ibge from funil.resultado_imovel where rodada_id = :rid
        on conflict (cod_imovel) do update set uf = excluded.uf, cod_municipio_ibge = excluded.cod_municipio_ibge
        where (funil.imovel.uf, funil.imovel.cod_municipio_ibge)
              is distinct from (excluded.uf, excluded.cod_municipio_ibge)"""),
        {"rid": rid},
    )
    if "geo" in arquivos:
        _carregar_geo(con, arquivos["geo"])
    if "camadas" in arquivos:
        _carregar_camadas(con, arquivos["camadas"], cod, rid)
    if "serie_uso" in arquivos:
        _carregar_serie_uso(con, arquivos["serie_uso"])
    _marcar_blocos(con, rid)

    novas, faltando, avisos = _fechar_rodada(con, rid, n, list(leituras.values()), mb)
    atualizar_vigente(con, cod)  # só este município muda; as rodadas antigas ficam guardadas
    log.info("município %s: rodada %s com %s imóveis", cod, rid, n)
    return ResultadoCarga(rid, True, "municipio", uf, cod, n, novas, faltando, avisos)


def carregar_resumo(
    con: Connection, arquivo: str | Path, uf: str, data_corte: dt.date | None = None, origem: str | None = None
) -> ResultadoCarga:
    arquivo = Path(arquivo)
    hashes, h = _hash_entradas({"resumo": arquivo})
    if ex := _rodada_existente(con, h):
        return ResultadoCarga(ex.id, False, ex.tipo, ex.uf, None, ex.imoveis or 0)
    lr = contrato.ler(arquivo, "resumo")
    rid = _nova_rodada(
        con, "resumo_uf", uf.upper(), None, origem or str(arquivo), hashes, h, data_corte or dt.date.today(), False
    )
    n = _copy(con, "funil.resumo_municipio", ["rodada_id", *lr.tipadas.columns, "atributos"], _linhas_leitura(rid, lr))
    novas, faltando, avisos = _fechar_rodada(con, rid, n, [lr])
    municipios_do_resumo(con, rid)  # busca por nome acha o município mesmo antes de ter imóveis
    return ResultadoCarga(rid, True, "resumo_uf", uf.upper(), None, n, novas, faltando, avisos)


def carregar_pasta(
    engine, pasta: str | Path, data_corte: dt.date | None = None, motor_confirmado: bool = False, congelar: bool = True
) -> list[ResultadoCarga]:
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
