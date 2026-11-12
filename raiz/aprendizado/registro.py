"""Registro de previsões congeladas e de gabaritos. Serve a qualquer modelo da Raíz (motor, carbono, título,
rebanho, agentes): toda previsão entra aqui com a data de corte, o horizonte e as versões, e nunca mais muda.

O lote é identificado pelo sha256 das suas linhas em forma canônica (hash do lote): dá para provar depois que
nenhuma previsão foi trocada.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
from collections.abc import Iterable
from dataclasses import dataclass

from psycopg.types.json import Jsonb
from sqlalchemy import Connection, text


@dataclass(frozen=True)
class Previsao:
    cod_imovel: str
    alvo: str
    horizonte_dias: int
    valor_num: float | None = None
    valor_texto: str | None = None
    p10: float | None = None
    p50: float | None = None
    p90: float | None = None
    distribuicao: dict | None = None


@dataclass(frozen=True)
class Versoes:
    modelo: str
    modelo_versao: str
    entradas_versao: str
    data_corte: dt.date
    regras_versao: str | None = None
    receita_hash: str | None = None
    tipo: str = "ao_vivo"  # ao_vivo | backtest
    rodada_id: int | None = None


def _num(v: float | None) -> str:
    return "" if v is None else repr(float(v))


def _linha(p: Previsao, v: Versoes) -> str:
    return "|".join(
        [
            v.tipo,
            p.cod_imovel,
            p.alvo,
            _num(p.valor_num),
            p.valor_texto or "",
            _num(p.p10),
            _num(p.p50),
            _num(p.p90),
            v.data_corte.isoformat(),
            str(p.horizonte_dias),
            v.modelo,
            v.modelo_versao,
            v.entradas_versao,
            v.regras_versao or "",
            v.receita_hash or "",
        ]
    )


def hash_lote(previsoes: Iterable[Previsao], v: Versoes) -> str:
    h = hashlib.sha256()
    for linha in sorted(_linha(p, v) for p in previsoes):
        h.update(linha.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _valida(p: Previsao) -> None:
    for x in (p.valor_num, p.p10, p.p50, p.p90):
        if x is not None and (not isinstance(x, int | float) or math.isnan(x) or math.isinf(x)):
            raise ValueError(f"valor inválido em {p.cod_imovel}/{p.alvo}: {x!r}")
    if p.valor_num is None and p.valor_texto is None and p.p50 is None:
        raise ValueError(f"previsão vazia: {p.cod_imovel}/{p.alvo}")


def registrar_lote(
    con: Connection, previsoes: list[Previsao], v: Versoes, descricao: str | None = None
) -> tuple[str, bool]:
    """Congela um lote. Devolve (lote_hash, novo). Registrar o mesmo lote de novo não faz nada."""
    for p in previsoes:
        _valida(p)
    lh = hash_lote(previsoes, v)
    if con.execute(text("select 1 from aprendizado.lote_previsao where lote_hash = :h"), {"h": lh}).first():
        return lh, False
    con.execute(
        text("""insert into aprendizado.lote_previsao (lote_hash, tipo, modelo, modelo_versao, entradas_versao,
                regras_versao, data_corte, rodada_id, n_previsoes, descricao)
                values (:h, :tipo, :m, :mv, :ev, :rv, :dc, :rid, :n, :d)"""),
        dict(
            h=lh,
            tipo=v.tipo,
            m=v.modelo,
            mv=v.modelo_versao,
            ev=v.entradas_versao,
            rv=v.regras_versao,
            dc=v.data_corte,
            rid=v.rodada_id,
            n=len(previsoes),
            d=descricao,
        ),
    )
    cols = [
        "lote_hash",
        "tipo",
        "cod_imovel",
        "alvo",
        "valor_num",
        "valor_texto",
        "p10",
        "p50",
        "p90",
        "distribuicao",
        "data_corte",
        "horizonte_dias",
        "modelo",
        "modelo_versao",
        "entradas_versao",
        "regras_versao",
        "receita_hash",
        "rodada_id",
    ]
    raw = con.connection.driver_connection
    with raw.cursor() as cur, cur.copy(f"COPY aprendizado.previsao ({', '.join(cols)}) FROM STDIN") as cp:
        for p in previsoes:
            cp.write_row(
                (
                    lh,
                    v.tipo,
                    p.cod_imovel,
                    p.alvo,
                    p.valor_num,
                    p.valor_texto,
                    p.p10,
                    p.p50,
                    p.p90,
                    Jsonb(p.distribuicao) if p.distribuicao is not None else None,
                    v.data_corte,
                    p.horizonte_dias,
                    v.modelo,
                    v.modelo_versao,
                    v.entradas_versao,
                    v.regras_versao,
                    v.receita_hash,
                    v.rodada_id,
                )
            )
    return lh, True


def conferir_lote(con: Connection, lote_hash: str) -> bool:
    """Refaz o hash a partir das linhas gravadas e compara com o hash do lote."""
    lote = con.execute(text("select * from aprendizado.lote_previsao where lote_hash = :h"), {"h": lote_hash}).first()
    if lote is None:
        return False
    rows = con.execute(text("select * from aprendizado.previsao where lote_hash = :h"), {"h": lote_hash}).all()
    if len(rows) != lote.n_previsoes:
        return False
    v = Versoes(
        lote.modelo,
        lote.modelo_versao,
        lote.entradas_versao,
        lote.data_corte,
        lote.regras_versao,
        rows[0].receita_hash if rows else None,
        lote.tipo,
        lote.rodada_id,
    )
    ps = [
        Previsao(r.cod_imovel, r.alvo, r.horizonte_dias, r.valor_num, r.valor_texto, r.p10, r.p50, r.p90) for r in rows
    ]
    return hash_lote(ps, v) == lote_hash


def registrar_gabarito(
    con: Connection,
    cod_imovel: str,
    alvo: str,
    observado_em: dt.date,
    fonte: str,
    valor_num: float | None = None,
    valor_texto: str | None = None,
    referencia: str | None = None,
) -> int:
    """Registra o resultado real. Correção = registrar de novo (vale o último registrado para a mesma data)."""
    if valor_num is None and valor_texto is None:
        raise ValueError("gabarito sem valor")
    return con.execute(
        text("""insert into aprendizado.gabarito
                (cod_imovel, alvo, valor_num, valor_texto, observado_em, fonte, referencia)
                values (:c, :a, :vn, :vt, :o, :f, :r) returning id"""),
        dict(c=cod_imovel, a=alvo, vn=valor_num, vt=valor_texto, o=observado_em, f=fonte, r=referencia),
    ).scalar_one()


def placar(con: Connection):
    """Acerto por modelo, versão e alvo (só previsões com gabarito)."""
    return con.execute(
        text("""
        select modelo, modelo_versao, alvo, count(*) as previsoes, count(gabarito_id) as com_gabarito,
               count(*) filter (where maturou) as maturadas,
               avg(acertou::int) filter (where acertou is not null) as taxa_acerto,
               avg(erro_abs) as erro_abs_medio,
               avg(dentro_p10_p90::int) filter (where dentro_p10_p90 is not null) as cobertura_p10_p90
        from aprendizado.previsao_contra_gabarito
        group by 1, 2, 3 order by 1, 2, 3""")
    ).all()
