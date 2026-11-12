"""Busca nacional (código do CAR e nome de município) e manutenção das tabelas que ela usa.

O código do CAR aparece de vários jeitos (PA-1504950-00162AB1E0B34E339E65946061393F10, com pontos a cada quatro
letras na tela do SICAR, em minúsculas): a busca compara só letras e números, em maiúsculas. O nome do município é
comparado sem acento e em minúsculas.
"""

from __future__ import annotations

import re
import unicodedata

from sqlalchemy import Connection, text

_NAO_ALNUM = re.compile(r"[^0-9A-Za-z]")


def normalizar_codigo(cod: str) -> str:
    """Mesma regra do banco (migração 0013): só letras e números, em maiúsculas."""
    return _NAO_ALNUM.sub("", cod or "").upper()


def normalizar_nome(nome: str) -> str:
    s = unicodedata.normalize("NFKD", nome or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def parece_codigo(q: str) -> bool:
    """UF + dígitos (PA15...), ou só dígitos do município em diante: busca por código, não por nome."""
    n = normalizar_codigo(q)
    return len(n) >= 3 and (bool(re.match(r"^[A-Z]{2}\d", n)) or n.isdigit())


def atualizar_vigente(con: Connection, cod_municipio: int) -> int:
    """Aponta os imóveis do município para a rodada vigente dele (data de corte mais nova; empate, a última
    carregada). Imóvel que não está nessa rodada sai. Devolve quantos imóveis o município tem agora."""
    rid = con.execute(
        text("""select id from funil.rodada where tipo = 'municipio' and cod_municipio = :m
                order by data_corte desc, id desc limit 1"""),
        {"m": cod_municipio},
    ).scalar()
    if rid is None:
        return 0
    con.execute(
        text("delete from funil.vigente where cod_municipio_ibge = :m and rodada_id <> :r"),
        {"m": cod_municipio, "r": rid},
    )
    con.execute(
        text("""
        insert into funil.vigente (cod_imovel, rodada_id, cod_municipio_ibge, uf, cod_busca)
        select r.cod_imovel, r.rodada_id, ro.cod_municipio, ro.uf,
               upper(regexp_replace(r.cod_imovel, '[^0-9A-Za-z]', '', 'g'))
        from funil.resultado_imovel r join funil.rodada ro on ro.id = r.rodada_id
        where r.rodada_id = :r
        on conflict (cod_imovel) do update
        set rodada_id = excluded.rodada_id, cod_municipio_ibge = excluded.cod_municipio_ibge, uf = excluded.uf,
            cod_busca = excluded.cod_busca, atualizado_em = now()
        where funil.vigente.rodada_id is distinct from excluded.rodada_id"""),
        {"r": rid},
    )
    n, nome, uf = con.execute(
        text("""select count(*), max(r.municipio), max(v.uf) from funil.vigente v
                join funil.resultado_imovel r on r.rodada_id = v.rodada_id and r.cod_imovel = v.cod_imovel
                where v.cod_municipio_ibge = :m"""),
        {"m": cod_municipio},
    ).one()
    if nome:
        _municipio(con, cod_municipio, nome, uf, n, rid)
    return n


def _municipio(con: Connection, cod: int, nome: str, uf: str | None, imoveis: int | None, rid: int | None) -> None:
    con.execute(
        text("""
        insert into funil.municipio_busca (cod_ibge, municipio, uf, nome_busca, imoveis, rodada_id)
        values (:c, :n, :u, :b, coalesce(:i, 0), :r)
        on conflict (cod_ibge) do update
        set municipio = excluded.municipio, uf = coalesce(excluded.uf, funil.municipio_busca.uf),
            nome_busca = excluded.nome_busca,
            imoveis = case when :i is null then funil.municipio_busca.imoveis else excluded.imoveis end,
            rodada_id = coalesce(excluded.rodada_id, funil.municipio_busca.rodada_id), atualizado_em = now()"""),
        {"c": cod, "n": nome, "u": uf, "b": normalizar_nome(nome), "i": imoveis, "r": rid},
    )


def municipios_do_resumo(con: Connection, rodada_resumo: int) -> int:
    """Todo município do resumo da UF entra na busca por nome, mesmo antes de ter imóveis carregados."""
    linhas = con.execute(
        text("""select m.cod_ibge, m.municipio, ro.uf, m.imoveis from funil.resumo_municipio m
                join funil.rodada ro on ro.id = m.rodada_id where m.rodada_id = :r and m.municipio is not null"""),
        {"r": rodada_resumo},
    ).all()
    for cod, nome, uf, n in linhas:
        _municipio(con, int(cod), nome, uf, None, None)
        con.execute(
            text("update funil.municipio_busca set imoveis_resumo = :n where cod_ibge = :c"),
            {"n": None if n is None else int(n), "c": int(cod)},
        )
    return len(linhas)
