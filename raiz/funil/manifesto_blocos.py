"""Manifesto de blocos (E2 passo 4): recalcular só os blocos que a coleta tocou.

Para cada camada do espelho (CAR, SIGEF, embargos do Ibama) e cada recorte da coleta (município), guarda o hash do
que a camada tem em cada bloco de 0,5 grau (raiz/funil/grade.py). O hash de cada feição é o mesmo do histórico
(bruto.linhas: atributos estáveis + geometria normalizada), então mudança só de campo volátil não suja o bloco.
Uma feição que toca vários blocos entra em todos. Quando o hash de um bloco muda (ou a camada sai dele), o bloco
fica sujo até o funil marcar o cálculo.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections import defaultdict

import geopandas as gpd
from sqlalchemy import Connection, Engine, text

from raiz.coleta import car
from raiz.funil import grade

# camada do espelho -> chave da feição e campos voláteis (mesmos do histórico)
CAMADAS = {
    "car": ("cod_imovel", car.VOLATEIS),
    "sigef": ("parcela_codigo", ()),
    "ibama": ("SEQ_TAD", ()),
}


def hashes_por_bloco(g: gpd.GeoDataFrame, chave: str, volateis: tuple[str, ...] = ()) -> dict[str, tuple[str, int]]:
    """bloco -> (hash do conteúdo da camada no bloco, número de feições)."""
    from raiz.coleta import bruto

    if not len(g):
        return {}
    volateis = tuple(v for v in volateis if v in g.columns)
    hs = bruto.linhas(g, chave, 0, volateis)["_hash"].tolist()
    graus = g.geometry.values if g.crs is None or g.crs.is_geographic else g.geometry.to_crs(4674).values
    por_bloco: dict[str, list[str]] = defaultdict(list)
    for h, geom in zip(hs, graus, strict=True):
        for b in grade.blocos_tocados(geom):
            por_bloco[b].append(h)
    return {b: (hashlib.sha256("|".join(sorted(v)).encode()).hexdigest()[:32], len(v)) for b, v in por_bloco.items()}


def atualizar(
    con: Connection, camada: str, recorte: str, novos: dict[str, tuple[str, int]], agora: dt.datetime
) -> set[str]:
    """Grava a parte de um recorte no manifesto. Devolve os blocos em que a camada mudou."""
    atuais = dict(
        con.execute(
            text("select bloco, hash from funil.bloco_manifesto where camada = :c and recorte = :r"),
            {"c": camada, "r": recorte},
        ).all()
    )
    mudaram = {b for b, (h, _) in novos.items() if atuais.get(b) != h}
    sairam = {b for b, h in atuais.items() if b not in novos and h != ""}
    linhas = [(b, *novos[b]) for b in novos] + [(b, "", 0) for b in sairam]
    for b, h, n in linhas:
        con.execute(
            text("""
            insert into funil.bloco_manifesto (bloco, camada, recorte, hash, n, visto_em, mudou_em)
            values (:b, :c, :r, :h, :n, :agora, :agora)
            on conflict (bloco, camada, recorte) do update
            set hash = excluded.hash, n = excluded.n, visto_em = excluded.visto_em,
                mudou_em = case when funil.bloco_manifesto.hash is distinct from excluded.hash
                                then excluded.mudou_em else funil.bloco_manifesto.mudou_em end"""),
            {"b": b, "c": camada, "r": recorte, "h": h, "n": n, "agora": agora},
        )
    return mudaram | sairam


def atualizar_do_espelho(engine: Engine, espelho, uf: str, cods: list[int], agora: dt.datetime | None = None) -> dict:
    """Lê do espelho os arquivos que mudaram desde a última leitura e atualiza o manifesto. Devolve
    {camada: blocos que mudaram}."""
    from raiz.versoes import sha256_arquivo

    agora = agora or dt.datetime.now(dt.UTC)
    out: dict[str, set[str]] = defaultdict(set)
    for cod in cods:
        recorte = f"{uf.upper()}/{cod}"
        for camada, (chave, volateis) in CAMADAS.items():
            f = espelho.caminho(camada, uf, cod)
            if not f.exists():
                continue
            sha = sha256_arquivo(f)
            with engine.begin() as con:
                lido = con.execute(
                    text("select arquivo_sha from funil.bloco_recorte where camada = :c and recorte = :r"),
                    {"c": camada, "r": recorte},
                ).scalar()
                if lido == sha:
                    continue
                g = espelho.ler(camada, uf, cod)
                out[camada] |= atualizar(con, camada, recorte, hashes_por_bloco(g, chave, volateis), agora)
                con.execute(
                    text("""insert into funil.bloco_recorte values (:c, :r, :s, :agora)
                            on conflict (camada, recorte) do update set arquivo_sha = :s, lido_em = :agora"""),
                    {"c": camada, "r": recorte, "s": sha, "agora": agora},
                )
    return dict(out)


def sujos(con: Connection) -> list[str]:
    """Blocos com alguma camada que mudou depois do último cálculo (ou nunca calculados)."""
    return [
        r[0]
        for r in con.execute(
            text("""
            select m.bloco from funil.bloco_manifesto m
            left join funil.bloco_calculo c on c.bloco = m.bloco
            group by m.bloco, c.calculado_em
            having c.calculado_em is null or max(m.mudou_em) > c.calculado_em
            order by m.bloco""")
        ).all()
    ]


def marcar_calculados(con: Connection, blocos: list[str], quando: dt.datetime, rodada_id: int | None = None) -> None:
    for b in blocos:
        con.execute(
            text("""insert into funil.bloco_calculo values (:b, :q, :r)
                    on conflict (bloco) do update set calculado_em = :q, rodada_id = :r"""),
            {"b": b, "q": quando, "r": rodada_id},
        )
