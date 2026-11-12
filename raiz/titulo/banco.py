"""Achados e confirmações no banco (titulo.achado, titulo.confirmacao, view titulo.achado_vigente).

- carregar_achados: grava o achados_<mun>.csv de uma rodada (a carga chama, raiz/carga.py);
- confirmar: registra quem confirmou, descartou ou corrigiu um achado (identificador do operador, nunca nome);
- pendentes: achados vigentes de gravidade reprova ou confirmar ainda sem confirmação, os mais graves primeiro.
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import Connection, text

from raiz.titulo.achados import COLUNAS

DECISOES = ("confirmado", "descartado", "corrigido")
# identificador de operador: minúsculas, números e hífen (ex.: fundador, conferente-02); nome de pessoa não passa
_QUEM = re.compile(r"^[a-z][a-z0-9-]{1,39}$")


def carregar_achados(con: Connection, rodada_id: int | None, arquivo: str | Path) -> int:
    import pandas as pd

    df = pd.read_csv(arquivo, dtype=str, keep_default_na=False)
    if df.empty:
        return 0
    faltam = set(COLUNAS) - set(df.columns)
    if faltam:
        raise ValueError(f"achados sem as colunas {sorted(faltam)}")
    linhas = [{**{c: (r[c] or None) for c in COLUNAS}, "rodada_id": rodada_id} for r in df[COLUNAS].to_dict("records")]
    con.execute(
        text(f"""insert into titulo.achado (rodada_id, {", ".join(COLUNAS)})
                 values (:rodada_id, {", ".join(":" + c for c in COLUNAS)})"""),
        linhas,
    )
    return len(linhas)


def confirmar(con: Connection, achado_id: int, quem: str, decisao: str, nota: str | None = None) -> int:
    if decisao not in DECISOES:
        raise ValueError(f"decisão deve ser uma de {', '.join(DECISOES)}")
    if not _QUEM.match(quem or ""):
        raise ValueError("quem: identificador do operador (ex.: fundador, conferente-02), nunca nome")
    a = con.execute(text("select cod_imovel, regra, valor from titulo.achado where id = :i"), {"i": achado_id}).first()
    if a is None:
        raise ValueError(f"achado {achado_id} não existe")
    from raiz.privacidade import mascarar

    return con.execute(
        text("""insert into titulo.confirmacao (achado_id, cod_imovel, regra, valor, decisao, quem, nota)
                values (:a, :c, :r, :v, :d, :q, :n) returning id"""),
        dict(a=achado_id, c=a.cod_imovel, r=a.regra, v=a.valor, d=decisao, q=quem, n=mascarar(nota) if nota else None),
    ).scalar_one()


def pendentes(con: Connection, cod_imovel: str | None = None, limite: int = 200) -> list:
    return con.execute(
        text("""select id, cod_imovel, fase, regra, situacao, gravidade, mensagem, valor
                from titulo.achado_vigente
                where gravidade in ('reprova', 'confirmar') and confirmacao_decisao is null
                  and (cast(:c as text) is null or cod_imovel = :c)
                order by case gravidade when 'reprova' then 0 else 1 end, cod_imovel, fase, regra
                limit :l"""),
        {"c": cod_imovel, "l": limite},
    ).all()


def do_imovel(con: Connection, cod_imovel: str) -> list:
    """Todos os achados vigentes do imóvel, com a confirmação que vale (para o laudo)."""
    return con.execute(
        text("select * from titulo.achado_vigente where cod_imovel = :c order by fase, regra"), {"c": cod_imovel}
    ).all()
