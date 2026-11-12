"""Estado de replicação por fonte e recorte (coleta.replicacao) e eventos de mudança (coleta.evento)."""

from __future__ import annotations

import datetime as dt
import json

from psycopg.types.json import Jsonb
from sqlalchemy import Connection, text

from raiz.coleta.manifesto import Manifesto, carregar, hash_manifesto
from raiz.privacidade import mascarar

CAMPOS = {
    "cursor",
    "etag",
    "last_modified",
    "contagem",
    "assinatura",
    "hash_conteudo",
    "sujo",
    "tentativas",
    "ultimo_erro",
    "verificado_em",
    "coletado_em",
}


def sincronizar_fontes(con: Connection, m: Manifesto | None = None) -> int:
    """Grava o manifesto em coleta.fonte (cria ou atualiza). Devolve quantas fontes."""
    m = m or carregar()
    h = hash_manifesto()
    for f in m.fontes:
        d = f.model_dump(mode="json")
        con.execute(
            text("""insert into coleta.fonte (id, nome, orgao, tipo, url, recorte, sinal, calendario, licenca,
                    pode_treinar, pendente, definicao, manifesto_versao, manifesto_hash)
                    values (:id, :nome, :orgao, :tipo, :url, :recorte, :sinal, :cal, :lic, :pt, :pend, :defn, :v, :h)
                    on conflict (id) do update set nome = excluded.nome, orgao = excluded.orgao, tipo = excluded.tipo,
                    url = excluded.url, recorte = excluded.recorte, sinal = excluded.sinal,
                    calendario = excluded.calendario, licenca = excluded.licenca, pode_treinar = excluded.pode_treinar,
                    pendente = excluded.pendente, definicao = excluded.definicao,
                    manifesto_versao = excluded.manifesto_versao, manifesto_hash = excluded.manifesto_hash,
                    atualizado_em = now()"""),
            dict(
                id=f.id,
                nome=f.nome,
                orgao=f.orgao,
                tipo=f.tipo,
                url=f.url,
                recorte=f.recorte,
                sinal=Jsonb(f.sinal),
                cal=Jsonb(f.calendario),
                lic=f.licenca,
                pt=f.pode_treinar,
                pend=f.pendente,
                defn=Jsonb(d),
                v=m.versao,
                h=h,
            ),
        )
    return len(m.fontes)


def estado(con: Connection, fonte: str, recorte: str):
    return con.execute(
        text("select * from coleta.replicacao where fonte = :f and recorte = :r"), {"f": fonte, "r": recorte}
    ).first()


def atualizar(con: Connection, fonte: str, recorte: str, **campos) -> None:
    desconhecidos = set(campos) - CAMPOS
    if desconhecidos:
        raise ValueError(f"campos desconhecidos: {sorted(desconhecidos)}")
    if "ultimo_erro" in campos and campos["ultimo_erro"]:
        campos["ultimo_erro"] = mascarar(str(campos["ultimo_erro"]))[:500]
    cols = ["fonte", "recorte", *campos]
    sets = ", ".join(f"{c} = excluded.{c}" for c in campos)
    con.execute(
        text(f"""insert into coleta.replicacao ({", ".join(cols)}) values ({", ".join(":" + c for c in cols)})
                 on conflict (fonte, recorte) do update set {sets}{", " if sets else ""}atualizado_em = now()"""),
        {"fonte": fonte, "recorte": recorte, **campos},
    )


def evento(
    con: Connection, fonte: str, recorte: str, tipo: str, quantidade: int | None = None, detalhe: dict | None = None
) -> None:
    con.execute(
        text("insert into coleta.evento (fonte, recorte, tipo, quantidade, detalhe) values (:f, :r, :t, :q, :d)"),
        dict(
            f=fonte,
            r=recorte,
            t=tipo,
            q=quantidade,
            d=Jsonb(json.loads(mascarar(json.dumps(detalhe or {}, default=str)))),
        ),
    )


def devidas(m: Manifesto | None = None, dia: dt.date | None = None) -> list[tuple[str, list[str] | None]]:
    """Fontes a olhar no dia: (id, UFs do rodízio ou None)."""
    m = m or carregar()
    dia = dia or dt.date.today()
    out = []
    for f in m.fontes:
        if not f.ativa:
            continue
        d = f.devida(dia)
        if d is True:
            out.append((f.id, None))
        elif isinstance(d, list) and d:
            out.append((f.id, d))
    return out
