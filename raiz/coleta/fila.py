"""Fila de recortes (municípios) a coletar, no desenho do nfhl.py (osm-geoparquet, MIT; desenho, sem código copiado):

- no máximo 200 recortes por rodada, os sujos primeiro (menos tentativas e verificados há mais tempo);
- nova tentativa na rodada seguinte para quem falhou, até 5 vezes (depois só com alerta e decisão humana);
- disjuntor: se mais de 15% dos recortes estiverem sujos, algo grande mudou (ou o sinal quebrou) e a rodada roda
  completa, sem limite;
- reconciliação completa mensal: todos os recortes de novo, ignorando a assinatura, para pegar o que o sinal perdeu.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import Connection, text

MAX_POR_RODADA = 200
LIMIAR_DISJUNTOR = 0.15
DIAS_RECONCILIACAO = 30
MAX_TENTATIVAS = 5


@dataclass
class Plano:
    modo: str  # incremental | completo | reconciliacao
    recortes: list[str]
    sujos: int
    total: int
    desistidos: list[str]


def _ultima_reconciliacao(con: Connection, fonte: str) -> dt.datetime | None:
    return con.execute(
        text(
            "select max(em) from coleta.evento where fonte = :f and recorte = '*' "
            "and detalhe->>'reconciliacao' = 'completa'"
        ),
        {"f": fonte},
    ).scalar()


def planejar(
    con: Connection,
    fonte: str,
    recortes: list[str],
    agora: dt.datetime | None = None,
    max_por_rodada: int = MAX_POR_RODADA,
    limiar: float = LIMIAR_DISJUNTOR,
) -> Plano:
    agora = agora or dt.datetime.now(dt.UTC)
    est = {
        r.recorte: r
        for r in con.execute(
            text("select recorte, sujo, tentativas, verificado_em from coleta.replicacao where fonte = :f"),
            {"f": fonte},
        )
    }
    nunca = [r for r in recortes if r not in est]
    sujos = [r for r in recortes if r in est and est[r].sujo]
    desistidos = [r for r in sujos if est[r].tentativas >= MAX_TENTATIVAS]
    candidatos = nunca + [r for r in sujos if r not in desistidos]
    total = len(recortes)
    ultima = _ultima_reconciliacao(con, fonte)
    if ultima is None or (agora - ultima) >= dt.timedelta(days=DIAS_RECONCILIACAO):
        return Plano("reconciliacao", list(recortes), len(candidatos), total, desistidos)
    if total and len(candidatos) / total > limiar:
        return Plano("completo", candidatos, len(candidatos), total, desistidos)

    def prioridade(r):
        e = est.get(r)
        return (e.tentativas if e else -1, e.verificado_em.timestamp() if e and e.verificado_em else 0)

    return Plano("incremental", sorted(candidatos, key=prioridade)[:max_por_rodada], len(candidatos), total, desistidos)


def registrar_reconciliacao(con: Connection, fonte: str) -> None:
    from raiz.coleta.replicacao import evento

    evento(con, fonte, "*", "sem_mudanca", detalhe={"reconciliacao": "completa"})
