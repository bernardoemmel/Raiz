"""Calibração por UF e porte (E8, rodada 10 passo 6): a chance prevista bate com o que acontece?

Para previsões de probabilidade (0 a 1) com gabarito sim ou não (1 ou 0):
  medir    por segmento (UF × porte pelo módulo fiscal: pequena até 4, média até 15, grande acima; Lei 8.629/1993) e
           no total: chance prevista média, taxa real (Hájek, pesada por 1/chance do sorteio quando o gabarito veio
           de sorteio), a diferença com intervalo de 95%, ECE (erro de calibração em 10 faixas) e Brier. Segmento fora
           da tolerância e com intervalo que não cobre a previsão é marcado.
  ajustar  mapa de recalibração: regressão isotônica (pool adjacent violators, ponderada) no total e em cada
           segmento, com o segmento puxado para o total quando tem pouco gabarito (peso n / (n + K)).
  calibrar a chance recalibrada de uma previsão pelo mapa.
O MCGrad (multicalibração da Meta) ficou de fora até conferir a licença; a isotônica por segmento faz o mesmo papel no
tamanho de hoje. O mapa leva a versão (hash do conteúdo) e vira o desafiante do modelo sem calibração
(raiz/aprendizado/campeao.py), testado por tempo (raiz/aprendizado/folds.py).
"""

from __future__ import annotations

import bisect
import datetime as dt
import hashlib
import json
import math
from dataclasses import dataclass

from sqlalchemy import Connection, text

VERSAO = "calibracao-2026a"
K_ENCOLHE = 50.0
TOLERANCIA = 0.05
FAIXAS = 10
Z95 = 1.959964


def porte(m_fiscal) -> str:
    try:
        m = float(m_fiscal)
    except (TypeError, ValueError):
        return "sem_porte"
    if math.isnan(m):
        return "sem_porte"
    return "pequena" if m <= 4 else ("media" if m <= 15 else "grande")


@dataclass
class Ponto:
    cod_imovel: str
    p: float
    y: float
    peso: float
    uf: str
    porte: str
    data_corte: dt.date
    observado_em: dt.date

    @property
    def segmento(self) -> str:
        return f"{self.uf}|{self.porte}"


def pontos(
    con: Connection,
    modelo: str,
    alvo: str,
    ate: dt.date | None = None,
    corte_de: dt.date | None = None,
    corte_ate: dt.date | None = None,
    tipo: str = "ao_vivo",
    pelo_registro: bool = False,
) -> list[Ponto]:
    """Previsões de probabilidade com gabarito 0 ou 1. ate: só gabarito observado até a data; com pelo_registro, só
    o que também já estava registrado na Raíz até a data (o mais estrito; gabarito lançado depois, como certidão
    lida hoje sobre fato antigo, fica de fora). corte_de/corte_ate: previsões com corte em (corte_de, corte_ate]."""
    rs = con.execute(
        text("""
        select pg.cod_imovel, pg.valor_num as p, pg.real_num as y, pg.data_corte, g.observado_em,
               g.probabilidade_escolha as prob, r.m_fiscal
        from aprendizado.previsao_contra_gabarito pg
        join aprendizado.gabarito g on g.id = pg.gabarito_id
        left join funil.resultado_vigente r on r.cod_imovel = pg.cod_imovel
        where pg.modelo = :m and pg.alvo = :a and pg.tipo = :t
          and pg.valor_num between 0 and 1 and pg.real_num in (0, 1)
          and (cast(:ate as date) is null or g.observado_em <= :ate)
          and (cast(:ate as date) is null or not :reg or g.registrado_em::date <= :ate)
          and (cast(:de as date) is null or pg.data_corte > :de)
          and (cast(:cate as date) is null or pg.data_corte <= :cate)"""),
        {"m": modelo, "a": alvo, "t": tipo, "ate": ate, "de": corte_de, "cate": corte_ate, "reg": pelo_registro},
    ).all()
    return [
        Ponto(
            r.cod_imovel,
            float(r.p),
            float(r.y),
            1.0 / r.prob if r.prob else 1.0,
            r.cod_imovel.split("-")[0],
            porte(r.m_fiscal),
            r.data_corte,
            r.observado_em,
        )  # fmt: skip
        for r in rs
    ]


# --- isotônica ---------------------------------------------------------------------------------------------------


def pav(xs: list[float], ys: list[float], ws: list[float]) -> list[list[float]]:
    """Regressão isotônica ponderada (pool adjacent violators). Devolve os pontos [x médio, y médio] dos blocos."""
    ordem = sorted(range(len(xs)), key=lambda i: xs[i])
    blocos: list[list[float]] = []  # [soma w·x, soma w·y, soma w]
    for i in ordem:
        blocos.append([ws[i] * xs[i], ws[i] * ys[i], ws[i]])
        while len(blocos) > 1 and blocos[-2][1] / blocos[-2][2] >= blocos[-1][1] / blocos[-1][2]:
            b = blocos.pop()
            for k in range(3):
                blocos[-1][k] += b[k]
    return [[b[0] / b[2], b[1] / b[2]] for b in blocos if b[2] > 0]


def _interp(mapa: list[list[float]], p: float) -> float:
    if not mapa:
        return p
    xs = [x for x, _ in mapa]
    if p <= xs[0]:
        return mapa[0][1]
    if p >= xs[-1]:
        return mapa[-1][1]
    i = bisect.bisect_right(xs, p)
    (x0, y0), (x1, y1) = mapa[i - 1], mapa[i]
    return y0 if x1 == x0 else y0 + (y1 - y0) * (p - x0) / (x1 - x0)


def ajustar(ps: list[Ponto], k: float = K_ENCOLHE) -> dict:
    glob = pav([x.p for x in ps], [x.y for x in ps], [x.peso for x in ps])
    segs = {}
    por: dict[str, list[Ponto]] = {}
    for x in ps:
        por.setdefault(x.segmento, []).append(x)
    for s, xs in por.items():
        segs[s] = {"n": len(xs), "mapa": pav([x.p for x in xs], [x.y for x in xs], [x.peso for x in xs])}
    mapa = {"versao_regra": VERSAO, "k": k, "n": len(ps), "global": glob, "segmentos": segs}
    corpo = json.dumps(mapa, sort_keys=True, separators=(",", ":"))
    mapa["versao"] = f"{VERSAO}+{hashlib.sha256(corpo.encode()).hexdigest()[:10]}"
    return mapa


def calibrar(mapa: dict, p: float, uf: str | None = None, porte_: str | None = None) -> float:
    g = _interp(mapa.get("global") or [], p)
    s = (mapa.get("segmentos") or {}).get(f"{uf}|{porte_}")
    if not s:
        return min(1.0, max(0.0, g))
    lam = s["n"] / (s["n"] + mapa.get("k", K_ENCOLHE))
    return min(1.0, max(0.0, lam * _interp(s["mapa"], p) + (1 - lam) * g))


# --- medidas -----------------------------------------------------------------------------------------------------


def _media(vs, ws) -> float:
    return sum(v * w for v, w in zip(vs, ws, strict=True)) / sum(ws)


def ece(ps: list[float], ys: list[float], ws: list[float], faixas: int = FAIXAS) -> float:
    tot = sum(ws)
    out = 0.0
    for b in range(faixas):
        idx = [i for i, p in enumerate(ps) if (b / faixas <= p < (b + 1) / faixas) or (b == faixas - 1 and p == 1.0)]
        if not idx:
            continue
        w = [ws[i] for i in idx]
        out += sum(w) / tot * abs(_media([ps[i] for i in idx], w) - _media([ys[i] for i in idx], w))
    return out


def _resumo(xs: list[Ponto], mapa: dict | None) -> dict:
    ws = [x.peso for x in xs]
    ps = [calibrar(mapa, x.p, x.uf, x.porte) if mapa else x.p for x in xs]
    ys = [x.y for x in xs]
    prev, real = _media(ps, ws), _media(ys, ws)
    dif = [(y - p) for p, y in zip(ps, ys, strict=True)]
    gap = _media(dif, ws)
    v = sum((w * (d - gap)) ** 2 for w, d in zip(ws, dif, strict=True)) / sum(ws) ** 2
    if len(xs) > 1:
        v *= len(xs) / (len(xs) - 1)
    ep = math.sqrt(v)
    ic = (gap - Z95 * ep, gap + Z95 * ep)
    return {
        "n": len(xs),
        "prevista": prev,
        "real": real,
        "diferenca": gap,
        "ic95": ic,
        "ece": ece(ps, ys, ws),
        "brier": _media([(p - y) ** 2 for p, y in zip(ps, ys, strict=True)], ws),
        "fora": abs(gap) > TOLERANCIA and not (ic[0] <= 0 <= ic[1]),
    }


def medir(ps: list[Ponto], mapa: dict | None = None) -> dict:
    """{"total": resumo, "segmentos": {uf|porte: resumo}}; com mapa, mede as chances já recalibradas."""
    if not ps:
        return {"total": None, "segmentos": {}}
    por: dict[str, list[Ponto]] = {}
    for x in ps:
        por.setdefault(x.segmento, []).append(x)
    return {"total": _resumo(ps, mapa), "segmentos": {s: _resumo(xs, mapa) for s, xs in sorted(por.items())}}
