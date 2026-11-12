"""Custo dos modelos por tarefa, por fazenda (código do CAR) ou por município, a partir de operacao.chamada_modelo
(o mesmo número que o Langfuse mostra por sessão), e o gasto do mês contra o orçamento."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Connection, text

AGRUPAR = {"tarefa": "tarefa", "fazenda": "cod_imovel", "municipio": "cod_municipio", "modelo": "modelo"}


def custo_por(con: Connection, por: str = "tarefa", desde: dt.date | None = None, limite: int = 50):
    if por not in AGRUPAR:
        raise ValueError(f"agrupar por {sorted(AGRUPAR)}")
    col = AGRUPAR[por]
    return con.execute(
        text(f"""select {col}::text as chave, count(*) as chamadas, count(*) filter (where not ok) as falhas,
                 coalesce(sum(custo_usd), 0) as custo_usd,
                 count(*) filter (where custo_fonte = 'sem_preco') as sem_preco,
                 coalesce(sum(tokens_entrada + tokens_saida), 0) as tokens
                 from operacao.chamada_modelo where criado_em >= :d
                 group by 1 order by custo_usd desc nulls last limit :l"""),
        {"d": desde or dt.date(1970, 1, 1), "l": limite},
    ).all()


def gasto_do_mes(con: Connection, hoje: dt.date | None = None) -> float:
    hoje = hoje or dt.date.today()
    inicio = hoje.replace(day=1)
    v = con.execute(
        text("select coalesce(sum(custo_usd), 0) from operacao.chamada_modelo where criado_em >= :d"), {"d": inicio}
    ).scalar()
    return float(v)
