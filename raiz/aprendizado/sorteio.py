"""Sorteio das conferências (E8, rodada 10 passo 6) e as estimativas que ele permite.

Conferir custa (uma certidão, uma visita, uma ligação). Conferir só o que se escolheu a dedo ensina errado: a
amostra fica torta. O sorteio faz as duas coisas ao mesmo tempo, sobre a mesma população (as previsões vigentes de
um alvo que ainda não têm gabarito):
  aleatório  cada imóvel entra com a mesma chance (Bernoulli, n_aleatorio / N): mede o erro sem viés;
  dirigido   cada imóvel entra com chance proporcional à dúvida da previsão (PPS de Poisson, com teto 1 e piso de
             dúvida, para ninguém ficar com chance zero): aprende onde o modelo mais erra.
A chance total de cada imóvel, 1 − (1 − p_aleatório)(1 − p_dirigido), fica gravada (aprendizado.sorteio_item) e vai
para o gabarito quando ele chegar (registrar_gabarito). Com ela:
  estimar    taxa real, taxa prevista, Brier, acerto e erro médio da população, pesando cada gabarito por 1/chance
             (estimador de Hájek), com intervalo de 95%;
  olofsson   área de cada classe real com intervalo, estratificada pela classe prevista (Olofsson et al. 2014,
             "Good practices for estimating area and assessing accuracy of land change"), com os pesos do sorteio e a
             área de cada imóvel; dá também o acerto do usuário e do produtor por classe.

Dúvida de cada previsão (0 a 1): com P10 e P90, a largura relativa da faixa; com probabilidade (0 a 1), 4·p·(1 − p);
sem medida de dúvida, 1 (o dirigido vira aleatório).
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass

from sqlalchemy import Connection, text

VERSAO = "sorteio-2026a"
PISO_INCERTEZA = 0.05
Z95 = 1.959964


@dataclass
class Candidato:
    previsao_id: int
    cod_imovel: str
    valor_num: float | None
    valor_texto: str | None
    p10: float | None
    p50: float | None
    p90: float | None
    data_corte: object = None


def incerteza(c: Candidato) -> float:
    if c.p10 is not None and c.p90 is not None:
        base = abs(c.p50 if c.p50 is not None else (c.valor_num or 0.0)) or 1.0
        u = (c.p90 - c.p10) / (2 * base)
    elif c.valor_num is not None and 0.0 <= c.valor_num <= 1.0 and c.valor_texto is None:
        u = 4 * c.valor_num * (1 - c.valor_num)
    else:
        u = 1.0
    return max(PISO_INCERTEZA, min(1.0, u))


def pps(us: list[float], n: float) -> list[float]:
    """Chances proporcionais a us, somando n, com teto 1 (quem bate no teto sai da conta e o resto se reparte)."""
    p = [0.0] * len(us)
    if n <= 0 or not us:
        return p
    livres = set(range(len(us)))
    falta = float(n)
    while livres:
        soma = sum(us[i] for i in livres)
        if soma <= 0:
            break
        cheios = {i for i in livres if falta * us[i] / soma >= 1.0}
        if not cheios:
            for i in livres:
                p[i] = falta * us[i] / soma
            break
        for i in cheios:
            p[i] = 1.0
        falta -= len(cheios)
        livres -= cheios
        if falta <= 0:
            break
    return p


def populacao(
    con: Connection, alvo: str, modelo: str | None = None, uf: str | None = None, cod_municipio: int | None = None
) -> list[Candidato]:
    """Previsão vigente (a de corte mais novo) de cada imóvel para o alvo, sem gabarito depois do corte e fora de
    sorteio ainda aberto para o mesmo alvo."""
    rs = con.execute(
        text("""
        with vig as (
            select distinct on (p.cod_imovel) p.id, p.cod_imovel, p.valor_num, p.valor_texto, p.p10, p.p50, p.p90,
                   p.data_corte
            from aprendizado.previsao p
            where p.alvo = :a and p.tipo = 'ao_vivo' and (cast(:m as text) is null or p.modelo = :m)
              and (cast(:uf as text) is null or split_part(p.cod_imovel, '-', 1) = :uf)
              and (cast(:mun as text) is null or split_part(p.cod_imovel, '-', 2) = :mun)
            order by p.cod_imovel, p.data_corte desc, p.id desc
        )
        select v.* from vig v
        where not exists (select 1 from aprendizado.gabarito g
                          where g.cod_imovel = v.cod_imovel and g.alvo = :a and g.observado_em > v.data_corte)
          and not exists (select 1 from aprendizado.sorteio_item i where i.cod_imovel = v.cod_imovel and i.alvo = :a)
        order by v.cod_imovel"""),
        {"a": alvo, "m": modelo, "uf": uf, "mun": str(cod_municipio) if cod_municipio else None},
    ).all()
    return [Candidato(r.id, r.cod_imovel, r.valor_num, r.valor_texto, r.p10, r.p50, r.p90, r.data_corte) for r in rs]


def _classe(valor_num, valor_texto) -> str | None:
    """Classe prevista para estratificar: o texto, ou a probabilidade cortada em 0,5."""
    if valor_texto is not None:
        return str(valor_texto)
    if valor_num is not None and 0.0 <= valor_num <= 1.0:
        return "sim" if valor_num >= 0.5 else "não"
    return None


def _areas(con: Connection, cods: list[str]) -> dict[str, float]:
    if not cods:
        return {}
    rs = con.execute(
        text("select cod_imovel, ha from funil.resultado_vigente where cod_imovel = any(:c) and ha is not null"),
        {"c": cods},
    ).all()
    return {c: float(h) for c, h in rs}


def sortear(
    con: Connection,
    alvo: str,
    n: int,
    quem: str,
    semente: int | None = None,
    modelo: str | None = None,
    uf: str | None = None,
    cod_municipio: int | None = None,
    fracao_aleatoria: float = 0.5,
) -> dict:
    """Sorteia cerca de n conferências (n·fração no aleatório, o resto no dirigido; o tamanho exato varia, como em
    todo sorteio de Poisson). Grava o sorteio e os itens; devolve o resumo e os itens."""
    from raiz.titulo.banco import _QUEM

    if not _QUEM.match(quem):
        raise ValueError("quem: identificador do operador (ex.: fundador, conferente-02), nunca nome")
    pop = populacao(con, alvo, modelo, uf, cod_municipio)
    N = len(pop)
    if N == 0:
        return {"sorteio_id": None, "populacao": 0, "itens": []}
    semente = semente if semente is not None else random.SystemRandom().randrange(1, 2**31)
    rnd = random.Random(semente)
    n = min(int(n), N)
    na = round(n * fracao_aleatoria)
    nd = n - na
    pa = na / N
    us = [incerteza(c) for c in pop]
    pds = pps(us, nd)
    itens = []
    for c, u, pd in zip(pop, us, pds, strict=True):
        em_a = rnd.random() < pa
        em_d = rnd.random() < pd
        if not (em_a or em_d):
            continue
        prob = 1 - (1 - pa) * (1 - pd)
        itens.append(
            dict(
                cod_imovel=c.cod_imovel,
                previsao_id=c.previsao_id,
                desenho="aleatorio" if em_a else "dirigido",
                incerteza=round(u, 6),
                probabilidade_escolha=min(1.0, max(prob, 1e-9)),
            )
        )
    # estratos (classe prevista): número de imóveis e área, para a estimativa de Olofsson
    areas = _areas(con, [c.cod_imovel for c in pop])
    estratos: dict[str, dict] = {}
    for c in pop:
        k = _classe(c.valor_num, c.valor_texto) or "sem_classe"
        e = estratos.setdefault(k, {"n": 0, "area_ha": 0.0})
        e["n"] += 1
        e["area_ha"] += areas.get(c.cod_imovel, 0.0)
    filtro = {"modelo": modelo, "uf": uf, "cod_municipio": cod_municipio, "fracao_aleatoria": fracao_aleatoria,
              "estratos": estratos}  # fmt: skip
    sid = con.execute(
        text("""insert into aprendizado.sorteio (alvo, modelo, filtro, semente, n_populacao, n_aleatorio,
                                                  n_dirigido_esperado, versao, quem)
                values (:a, :m, cast(:f as jsonb), :s, :N, :na, :nd, :v, :q) returning id"""),
        dict(
            a=alvo,
            m=modelo,
            f=json.dumps(filtro),
            s=semente,
            N=N,
            na=sum(i["desenho"] == "aleatorio" for i in itens),
            nd=nd,
            v=VERSAO,
            q=quem,
        ),  # fmt: skip
    ).scalar_one()
    if itens:
        con.execute(
            text("""insert into aprendizado.sorteio_item (sorteio_id, cod_imovel, alvo, previsao_id, desenho,
                                                           incerteza, probabilidade_escolha)
                    values (:s, :cod_imovel, :a, :previsao_id, :desenho, :incerteza, :probabilidade_escolha)"""),
            [{**i, "s": sid, "a": alvo} for i in itens],
        )
    return {"sorteio_id": sid, "populacao": N, "semente": semente, "itens": itens}


def desenho_do_imovel(con: Connection, cod_imovel: str, alvo: str, observado_em) -> tuple[str, float] | None:
    """(desenho, chance) do sorteio mais novo em que o imóvel entrou para o alvo, com corte antes da observação."""
    r = con.execute(
        text("""select i.desenho, i.probabilidade_escolha from aprendizado.sorteio_item i
                join aprendizado.previsao p on p.id = i.previsao_id
                where i.cod_imovel = :c and i.alvo = :a and p.data_corte < :o
                order by i.sorteio_id desc limit 1"""),
        {"c": cod_imovel, "a": alvo, "o": observado_em},
    ).first()
    return (r.desenho, float(r.probabilidade_escolha)) if r else None


def itens(con: Connection, sorteio_id: int) -> list:
    return con.execute(
        text("""select i.*, s.criado_em from aprendizado.sorteio_item i
                join aprendizado.sorteio s on s.id = i.sorteio_id
                where i.sorteio_id = :s order by i.desenho, i.probabilidade_escolha desc, i.cod_imovel"""),
        {"s": sorteio_id},
    ).all()


# --- estimativas ---------------------------------------------------------------------------------------------------


def _hajek(ys: list[float], ws: list[float]) -> dict | None:
    if not ys:
        return None
    sw = sum(ws)
    m = sum(w * y for w, y in zip(ws, ys, strict=True)) / sw
    v = sum((w * (y - m)) ** 2 for w, y in zip(ws, ys, strict=True)) / sw**2
    if len(ys) > 1:
        v *= len(ys) / (len(ys) - 1)
    ep = math.sqrt(v)
    return {"valor": m, "ep": ep, "ic95": (m - Z95 * ep, m + Z95 * ep), "n": len(ys)}


def _respostas(con: Connection, sorteio_id: int) -> list:
    return con.execute(
        text("""select i.cod_imovel, i.desenho, i.probabilidade_escolha as prob, pg.valor_num, pg.valor_texto,
                       pg.real_num, pg.real_texto, pg.acertou, pg.erro, pg.erro_abs
                from aprendizado.sorteio_item i
                join aprendizado.previsao_contra_gabarito pg on pg.previsao_id = i.previsao_id
                where i.sorteio_id = :s and pg.gabarito_id is not null"""),
        {"s": sorteio_id},
    ).all()


def estimar(con: Connection, sorteio_id: int) -> dict:
    """Estimativas da população pelos gabaritos do sorteio, pesados por 1/chance (Hájek), e as mesmas contas sem
    peso, para ver o viés que o peso corrige."""
    s = con.execute(text("select * from aprendizado.sorteio where id = :s"), {"s": sorteio_id}).first()
    if s is None:
        raise ValueError(f"sorteio {sorteio_id} não existe")
    rs = _respostas(con, sorteio_id)
    n_itens = con.execute(
        text("select count(*) from aprendizado.sorteio_item where sorteio_id = :s"), {"s": sorteio_id}
    ).scalar()
    out = {"sorteio_id": sorteio_id, "alvo": s.alvo, "populacao": s.n_populacao, "sorteados": n_itens,
           "com_gabarito": len(rs)}  # fmt: skip
    w = [1 / r.prob for r in rs]
    binaria = [r.valor_num is not None and r.real_num is not None and 0 <= r.valor_num <= 1
               and r.real_num in (0.0, 1.0) and r.valor_texto is None for r in rs]  # fmt: skip
    prob = [(r, x) for r, x, b in zip(rs, w, binaria, strict=True) if b]
    if prob:
        ws = [x for _, x in prob]
        out["taxa_real"] = _hajek([r.real_num for r, _ in prob], ws)
        out["taxa_prevista"] = _hajek([r.valor_num for r, _ in prob], ws)
        out["brier"] = _hajek([(r.valor_num - r.real_num) ** 2 for r, _ in prob], ws)
        out["taxa_real_sem_peso"] = _hajek([r.real_num for r, _ in prob], [1.0] * len(prob))
    tx = [(r, x) for r, x in zip(rs, w, strict=True) if r.acertou is not None]
    if tx:
        out["acerto"] = _hajek([float(r.acertou) for r, _ in tx], [x for _, x in tx])
        out["acerto_sem_peso"] = _hajek([float(r.acertou) for r, _ in tx], [1.0] * len(tx))
    nm = [(r, x) for r, x, b in zip(rs, w, binaria, strict=True) if r.erro is not None and not b]
    if nm:
        out["erro_medio"] = _hajek([r.erro for r, _ in nm], [x for _, x in nm])
        out["erro_abs_medio"] = _hajek([r.erro_abs for r, _ in nm], [x for _, x in nm])
    return out


def olofsson(con: Connection, sorteio_id: int) -> dict:
    """Área de cada classe real, estratificada pela classe prevista, com intervalo de 95%; acerto do usuário (da
    classe prevista) e do produtor (da classe real). Pesos: 1/chance do sorteio vezes a área do imóvel."""
    s = con.execute(text("select * from aprendizado.sorteio where id = :s"), {"s": sorteio_id}).first()
    if s is None:
        raise ValueError(f"sorteio {sorteio_id} não existe")
    estratos = (s.filtro or {}).get("estratos") or {}
    rs = _respostas(con, sorteio_id)
    areas = _areas(con, [r.cod_imovel for r in rs])
    amostra: dict[str, list] = {}
    for r in rs:
        h = _classe(r.valor_num, r.valor_texto)
        j = _classe(r.real_num, r.real_texto)
        a = areas.get(r.cod_imovel)
        if h is None or j is None or not a:
            continue
        amostra.setdefault(h, []).append((j, a / r.prob))
    classes = sorted({j for xs in amostra.values() for j, _ in xs} | set(amostra))
    A = sum(e["area_ha"] for e in estratos.values())
    if not A or not amostra:
        return {"sorteio_id": sorteio_id, "area_total_ha": A, "classes": {}, "com_gabarito": len(rs)}
    # proporção de área de cada classe real dentro de cada estrato (razão ponderada) e variância linearizada
    p_hj, v_hj = {}, {}
    for h, xs in amostra.items():
        sw = sum(w for _, w in xs)
        for j in classes:
            p = sum(w for jj, w in xs if jj == j) / sw
            v = sum((w * ((jj == j) - p)) ** 2 for jj, w in xs) / sw**2
            if len(xs) > 1:
                v *= len(xs) / (len(xs) - 1)
            p_hj[(h, j)], v_hj[(h, j)] = p, v
    # estrato sem gabarito fica de fora: os pesos dos outros são renormalizados (fracao_area_coberta diz quanto)
    W = {h: estratos.get(h, {}).get("area_ha", 0.0) / A for h in amostra}
    cobertos = sum(W.values()) or 1.0
    Wn = {h: x / cobertos for h, x in W.items()}
    At = A * cobertos
    out = {}
    for j in classes:
        p = sum(Wn[h] * p_hj[(h, j)] for h in amostra)
        ep = math.sqrt(sum(Wn[h] ** 2 * v_hj[(h, j)] for h in amostra))
        out[j] = {
            "area_ha": p * At,
            "ic95_ha": (max(0.0, (p - Z95 * ep) * At), (p + Z95 * ep) * At),
            "area_prevista_ha": estratos.get(j, {}).get("area_ha", 0.0),
            "acerto_usuario": p_hj.get((j, j)),
            "acerto_produtor": Wn[j] * p_hj[(j, j)] / p if p > 0 and j in Wn else None,
        }
    return {"sorteio_id": sorteio_id, "area_total_ha": A, "estratos_com_amostra": sorted(amostra),
            "fracao_area_coberta": cobertos, "classes": out, "com_gabarito": len(rs)}  # fmt: skip
