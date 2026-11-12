"""Quanto existe na base para o pedido e o melhor agrupamento em 3 opções (docs/cena-alvo.md, "Como escolher o lote").

- base(): filtra o mapa inteiro pelo pedido e responde fazendas, ha e créditos líquidos P10/P50/P90 por caminho da
  terra e por interesse do dono; sem alcançar a meta, quanto falta e o que afrouxar (do que mais soma ao que menos).
  Fazenda reservada por outro cliente nunca entra.
- opcoes(): o mesmo solver (HiGHS, pelo scipy.optimize.milp) com pesos diferentes: mais barata (custo por crédito),
  mais segura (risco da terra, chance de cumprir os marcos e de aceite do dono) e mais compacta (grupos de vizinhas;
  vazamento zero com fazenda de mitigação no grupo). Cada opção traz 10 a 20% de fazendas de reserva.
  Pequenas nunca saem por tamanho: entram agrupadas com as vizinhas.
- A faixa P10/P90 sai de simulação (custo e captura com parte comum entre fazendas, e o aceite do dono).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from raiz.pedidos import aceite as A
from raiz.pedidos.campos import CAMINHOS, METODOS, CamposPedido
from raiz.pedidos.premissas import premissas

Z90 = 1.2815515655446004
NOMES_CAMINHO = {
    "matricula_conferida": "matrícula conferida",
    "matricula_a_conferir": "matrícula a conferir no cartório",
    "concessao": "terra pública sob concessão",
    "assentamento": "lote de assentamento (depende de aval do INCRA)",
    "posse_em_titulacao": "posse em titulação (em espera até o título sair)",
}
NOMES_METODO = {
    "regeneracao_assistida": "regeneração assistida",
    "semeadura_direta": "semeadura direta",
    "plantio_total": "plantio total",
    "agrofloresta": "agrofloresta",
    "silvipastoril": "silvipastoril",
}
INTERESSADOS = ("interessado", "aceite_fase1", "contrato_firme")
COM_ACEITE = ("aceite_fase1", "contrato_firme")


# --- filtro do pedido ---------------------------------------------------------------------------------------------


def _km(lon1, lat1, lon2, lat2):
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl, dp = np.radians(lon2 - lon1), p2 - p1
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def quantidade(oferta: pd.DataFrame, tipo: str, q: str = "p50") -> np.ndarray:
    """O que cada fazenda soma na meta: créditos líquidos até o fim do contrato, hectares ou t FLAG por ano."""
    if tipo == "hectares":
        return oferta.area_ha.to_numpy(float)
    if tipo == "flag_t_ano":
        return oferta.flag_t_ano.fillna(0).to_numpy(float)
    return oferta[f"credito_{q}"].fillna(0).to_numpy(float)


def filtrar(oferta: pd.DataFrame, c: CamposPedido, niveis: dict[str, str] | None = None,
            fora: set[str] | None = None) -> pd.DataFrame:  # fmt: skip
    """As fazendas que atendem o pedido. fora = reservadas por outro cliente (somem de tudo)."""
    niveis, fora = niveis or {}, fora or set()
    o = oferta
    m = o.elegivel.astype(bool) & ~o.problema.astype(bool) & ~o.cod_imovel.isin(fora)
    if c.onde.ufs:
        m &= o.uf.isin(c.onde.ufs)
    if c.onde.municipios:
        m &= o.cod_ibge.astype("Int64").astype(str).isin([str(x) for x in c.onde.municipios])
    if c.onde.biomas:
        m &= o.bioma.isin(c.onde.biomas)
    if c.onde.raio is not None:
        d = _km(o.lon.to_numpy(float), o.lat.to_numpy(float), c.onde.raio.lon, c.onde.raio.lat)
        m &= pd.Series(np.nan_to_num(d, nan=np.inf) <= c.onde.raio.km, index=o.index)
    if c.onde.poligono:
        import shapely

        pol = shapely.Polygon(c.onde.poligono)
        pts = shapely.points(o.lon.fillna(0).to_numpy(float), o.lat.fillna(0).to_numpy(float))
        m &= pd.Series(shapely.contains(pol, pts) & o.lon.notna().to_numpy(), index=o.index)
    if c.onde.so_fornecedores_cadeia:
        m &= o.cod_imovel.isin(c.onde.fornecedores)
    met = set(c.metodos)
    m &= o.metodos.map(lambda xs: bool(met & set(xs or [])))
    m &= o.caminho.isin(c.terra)
    for ex in c.exclusoes:
        if ex in o:
            m &= ~o[ex].astype(bool)
    if c.dinheiro.custo_max_usd_credito is not None:
        m &= o.custo_credito_usd.fillna(np.inf) <= c.dinheiro.custo_max_usd_credito
    if c.dinheiro.tir_min is not None:
        m &= o.tir_p50.fillna(-np.inf) >= c.dinheiro.tir_min
    nivel = o.cod_imovel.map(lambda x: niveis.get(x, "sem_contato"))
    m &= nivel != "recusou"
    if c.interesse == "interessados":
        m &= nivel.isin(INTERESSADOS)
    elif c.interesse == "com_aceite":
        m &= nivel.isin(COM_ACEITE)
    m &= pd.Series(quantidade(o, c.meta.tipo) > 0, index=o.index)
    return o[m].copy()


# --- faixa de uma soma de fazendas ---------------------------------------------------------------------------------


def faixa_soma(p10, p50, p90, rho: float | None = None) -> dict[str, float]:
    """P10/P50/P90 da soma: metades normais por fazenda, com parte comum rho entre elas (conta fechada)."""
    rho = premissas()["otimizador"]["correlacao_captura"] if rho is None else rho
    p10, p50, p90 = (np.asarray(x, dtype=float) for x in (p10, p50, p90))
    lo, hi = np.maximum(p50 - p10, 0) / Z90, np.maximum(p90 - p50, 0) / Z90
    s_lo = math.sqrt(rho**2 * lo.sum() ** 2 + (1 - rho**2) * (lo**2).sum())
    s_hi = math.sqrt(rho**2 * hi.sum() ** 2 + (1 - rho**2) * (hi**2).sum())
    m = float(p50.sum())
    return {"p10": max(m - Z90 * s_lo, 0.0), "p50": m, "p90": m + Z90 * s_hi}


def _sorteios(n_faz: int, p: dict) -> np.ndarray:
    o = p["otimizador"]
    g = np.random.default_rng(int(o["semente"]))
    n = int(o["sorteios"])
    rho = float(o["correlacao_captura"])
    comum = g.standard_normal((n, 1))
    return rho * comum + math.sqrt(1 - rho**2) * g.standard_normal((n, n_faz))


def simular(sel: pd.DataFrame, chance: np.ndarray | None, p: dict, reserva: pd.DataFrame | None = None,
            meta: float | None = None) -> dict:  # fmt: skip
    """Créditos do grupo por sorteio (custo e captura) e, com a chance de aceite, os créditos dos que aceitam,
    com as reservas entrando na ordem no lugar de quem recusa até fechar a meta."""
    z = _sorteios(len(sel), p)
    p10, p50, p90 = (sel[f"credito_{q}"].to_numpy(float) for q in ("p10", "p50", "p90"))
    lo, hi = (p50 - p10) / Z90, (p90 - p50) / Z90
    cred = np.maximum(p50 + np.where(z < 0, z * lo, z * hi), 0.0)
    out = {"creditos": {q: float(np.percentile(cred.sum(axis=1), x)) for q, x in (("p10", 10), ("p50", 50),
                                                                                    ("p90", 90))}}  # fmt: skip
    out["creditos"]["p50"] = float(p50.sum())  # o P50 é o caminho do meio, como na ficha
    if chance is not None:
        g = np.random.default_rng(int(p["otimizador"]["semente"]) + 1)
        aceita = g.random(cred.shape) < chance[None, :]
        total = (cred * aceita).sum(axis=1)
        if reserva is not None and len(reserva) and meta:
            r50 = reserva.credito_p50.to_numpy(float)
            rch = reserva.chance_aceite.to_numpy(float)
            ra = g.random((cred.shape[0], len(r50))) < rch[None, :]
            for j in range(len(r50)):  # a reserva entra na ordem enquanto falta
                falta = total < meta
                total = total + np.where(falta & ra[:, j], r50[j], 0.0)
        out["com_aceite"] = {q: float(np.percentile(total, x)) for q, x in (("p10", 10), ("p50", 50), ("p90", 90))}
        out["chance_fechar"] = float((total >= (meta or 0)).mean()) if meta else None
    return out


# --- quanto existe na base -----------------------------------------------------------------------------------------


def _resumo_base(f: pd.DataFrame, c: CamposPedido, niveis: dict[str, str]) -> dict:
    tipo = c.meta.tipo
    q = quantidade(f, tipo)
    fx = faixa_soma(*(quantidade(f, tipo, x) for x in ("p10", "p50", "p90"))) if tipo == "creditos" else {
        "p10": float(q.sum()), "p50": float(q.sum()), "p90": float(q.sum())}  # fmt: skip
    cred = faixa_soma(f.credito_p10, f.credito_p50, f.credito_p90)
    nivel = f.cod_imovel.map(lambda x: niveis.get(x, "sem_contato"))
    por_caminho = []
    for cam in CAMINHOS:
        s = f[f.caminho == cam]
        if len(s):
            por_caminho.append({"caminho": cam, "fazendas": int(len(s)), "hectares": round(float(s.area_ha.sum()), 1),
                                "creditos": round(float(s.credito_p50.sum()), 0)})  # fmt: skip
    por_interesse = []
    for nv in ("sem_contato", "contatado", "interessado", "aceite_fase1", "contrato_firme", "sem_resposta"):
        s = f[nivel == nv]
        if len(s):
            por_interesse.append({"nivel": nv, "fazendas": int(len(s)), "creditos": round(float(s.credito_p50.sum()))})
    return {"fazendas": int(len(f)), "hectares": round(float(f.area_ha.sum()), 1),
            "creditos": {k: round(v, 0) for k, v in cred.items()}, "meta_faixa": fx, "por_caminho": por_caminho,
            "por_interesse": por_interesse}  # fmt: skip


def afrouxar(oferta: pd.DataFrame, c: CamposPedido, niveis: dict[str, str], fora: set[str], atual: float) -> list:
    """O que afrouxar no pedido, do que mais soma na meta ao que menos (exclusões nunca entram aqui)."""
    tipo = c.meta.tipo
    alternativas = []
    for cam in CAMINHOS:
        if cam not in c.terra:
            alternativas.append(("terra", f"Aceitar {NOMES_CAMINHO[cam]}",
                                 c.model_copy(update={"terra": [*c.terra, cam]})))  # fmt: skip
    for met in METODOS:
        if met not in c.metodos:
            alternativas.append(("metodos", f"Aceitar também {NOMES_METODO[met]}",
                                 c.model_copy(update={"metodos": [*c.metodos, met]})))  # fmt: skip
    if c.interesse != "qualquer":
        alternativas.append(("interesse", "Contar também fazendas sem interesse registrado (a Raíz busca o aceite)",
                             c.model_copy(update={"interesse": "qualquer"})))  # fmt: skip
    if c.dinheiro.custo_max_usd_credito is not None:
        alternativas.append(("dinheiro.custo_max_usd_credito", "Tirar o custo máximo por crédito",
                             c.model_copy(update={"dinheiro": c.dinheiro.model_copy(
                                 update={"custo_max_usd_credito": None})})))  # fmt: skip
    if c.dinheiro.tir_min is not None:
        alternativas.append(("dinheiro.tir_min", "Tirar a TIR mínima", c.model_copy(update={
            "dinheiro": c.dinheiro.model_copy(update={"tir_min": None})})))  # fmt: skip
    if c.onde.raio is not None or c.onde.poligono or c.onde.municipios:
        alternativas.append(("onde", "Buscar no estado inteiro, sem raio, polígono ou lista de municípios",
                             c.model_copy(update={"onde": c.onde.model_copy(
                                 update={"raio": None, "poligono": None, "municipios": []})})))  # fmt: skip
    if c.onde.biomas:
        alternativas.append(("onde.biomas", "Buscar em todos os biomas", c.model_copy(
            update={"onde": c.onde.model_copy(update={"biomas": []})})))  # fmt: skip
    if c.onde.ufs:
        alternativas.append(("onde.ufs", "Buscar nos outros estados já processados", c.model_copy(
            update={"onde": c.onde.model_copy(update={"ufs": []})})))  # fmt: skip
    if c.onde.so_fornecedores_cadeia:
        alternativas.append(("onde.so_fornecedores_cadeia", "Contar fazendas fora da cadeia de fornecedores",
                             c.model_copy(update={"onde": c.onde.model_copy(
                                 update={"so_fornecedores_cadeia": False})})))  # fmt: skip
    out = []
    for campo, texto, novo in alternativas:
        ganho = float(quantidade(filtrar(oferta, novo, niveis, fora), tipo).sum()) - atual
        if ganho > 0:
            out.append({"campo": campo, "texto": texto, "ganho": round(ganho, 0)})
    if not out:  # nada no pedido aumenta a base: a meta passa do que já foi processado
        out.append({"campo": "base", "ganho": 0,
                    "texto": "Nada no pedido aumenta a base hoje: a meta passa do que a Raíz já processou. Os "
                             "estados que forem entrando somam sozinhos, e o pedido salvo avisa quando o lote "
                             "melhorar."})  # fmt: skip
    return sorted(out, key=lambda x: -x["ganho"])


def base(oferta: pd.DataFrame, c: CamposPedido, niveis: dict[str, str] | None = None,
         fora: set[str] | None = None) -> dict:  # fmt: skip
    """Quanto existe na base para o pedido (BaseDisponivel do contrato com o front)."""
    niveis, fora = niveis or {}, fora or set()
    f = filtrar(oferta, c, niveis, fora)
    r = _resumo_base(f, c, niveis)
    total = r.pop("meta_faixa")["p50"]
    falta = max(c.meta.valor - total, 0.0)
    r.update({"alcanca_meta": falta == 0, "falta": round(falta, 0),
              "afrouxar": afrouxar(oferta, c, niveis, fora, total) if falta > 0 else [],
              "na_unidade_da_meta": round(total, 0)})  # fmt: skip
    if f.local_aproximado.any():
        r["observacao"] = (f"{int(f.local_aproximado.sum())} fazendas sem o contorno no mapa: o lugar delas é o da "
                           "sede do município (a distância entre fazendas fica aproximada).")  # fmt: skip
    return r


# --- grupos de vizinhas -------------------------------------------------------------------------------------------


def grupos(f: pd.DataFrame, diametro_km: float | None) -> np.ndarray:
    """Grupo de vizinhas de cada fazenda: com contorno, fazendas que cabem num círculo do diâmetro pedido; sem
    contorno, o lote de vizinhas já calculado (grupo_id) ou o município."""
    from raiz.restauracao import agrupar

    d = diametro_km or premissas()["otimizador"]["diametro_km_padrao"]
    exatos = f[~f.local_aproximado.astype(bool) & f.lon.notna()]
    rot: dict[str, str] = {}
    if len(exatos):
        g = agrupar([(c, x, y) for c, x, y in zip(exatos.cod_imovel, exatos.lon, exatos.lat, strict=True)],
                    {"agrupamento": {"diametro_max_km": d}})  # fmt: skip
        rot = {c: f"d{v}" for c, v in g.items()}
    out = []
    for cod, gid, mun in zip(f.cod_imovel, f.grupo_id, f.cod_ibge, strict=True):
        out.append(rot.get(cod) or (f"g{gid}" if isinstance(gid, str) and gid else f"m{mun}"))
    return np.array(out, dtype=object)


# --- o solver -----------------------------------------------------------------------------------------------------


class _Calado:
    """O HiGHS escreve mensagens de depuração direto no stdout do processo (fora do Python): cala o fd 1."""

    def __enter__(self):
        import os
        import sys

        sys.stdout.flush()
        self._fd = os.dup(1)
        self._nulo = os.open(os.devnull, os.O_WRONLY)
        os.dup2(self._nulo, 1)
        return self

    def __exit__(self, *a):
        import os

        os.dup2(self._fd, 1)
        os.close(self._fd)
        os.close(self._nulo)


def _risco_usd(f: pd.DataFrame, chance: np.ndarray, p: dict) -> np.ndarray:
    o = p["otimizador"]
    terra = f.risco_terra.map(lambda r: o["risco_terra"].get(r, o["risco_terra"]["alto"])).to_numpy(float)
    marcos = (1 - f.marcos_todos.fillna(1.0).to_numpy(float)) * o["risco_marcos_usd"]
    return terra + marcos + (1 - chance) * o["risco_aceite_usd"]


def _custo_usd(f: pd.DataFrame) -> np.ndarray:
    c = f.custo_credito_usd.to_numpy(float)
    return np.where(np.isfinite(c), c, np.nanmax(np.append(c[np.isfinite(c)], 100.0)) * 1.5)


def _abaixo_equilibrio(f: pd.DataFrame, preco_usd: float) -> np.ndarray:
    """Fazendas cujo preço de equilíbrio (o que paga a WACC do cenário) passa do preço do pedido."""
    eq = f.preco_equilibrio_usd.to_numpy(float)
    return np.isfinite(eq) & (eq > preco_usd + 1e-9)


def _penalidade_preco(f: pd.DataFrame, preco_usd: float, p: dict) -> np.ndarray:
    """US$ por crédito a mais na fazenda que o preço não paga (a diferença até o equilíbrio e a penalidade): todas as
    opções preferem a regeneração e só usam o plantio abaixo do equilíbrio quando falta crédito."""
    eq = f.preco_equilibrio_usd.to_numpy(float)
    ab = _abaixo_equilibrio(f, preco_usd)
    return np.where(ab, np.nan_to_num(eq - preco_usd) + float(p["otimizador"]["abaixo_equilibrio_usd"]), 0.0)


def resolver(f: pd.DataFrame, c: CamposPedido, opcao: str, chance: np.ndarray, p: dict | None = None,
             reserva_meta: float | None = None) -> dict:  # fmt: skip
    """Escolhe as fazendas da opção (índices de f) e as de reserva. f já filtrada pelo pedido. A reserva vai até
    `reserva_meta` (na unidade da meta) quando dada; senão, até a fração de reserva da meta."""
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import coo_matrix, vstack

    p = p or premissas()
    o = p["otimizador"]
    w = o["pesos"][opcao]
    meta = float(c.meta.valor)
    q = quantidade(f, c.meta.tipo)
    g = grupos(f, c.forma.distancia_max_km)
    cred = f.credito_p50.to_numpy(float)
    unit = w["custo"] * _custo_usd(f) + w["risco"] * _risco_usd(f, chance, p)  # US$ por crédito
    unit = unit + _penalidade_preco(f, float(c.dinheiro.preco_venda_usd), p)
    # mitigação: grupo com fazenda de mitigação tem vazamento zero (só na opção compacta, onde o grupo é o lote)
    mitig = np.zeros(len(f), dtype=bool)
    if opcao == "compacta" and f.mitigacao.any():
        gm = set(g[f.mitigacao.to_numpy(bool)])
        mitig = np.isin(g, list(gm))
        vaz = 0.10
        q = np.where(mitig & (c.meta.tipo == "creditos"), q / (1 - vaz), q)
        cred = np.where(mitig, cred / (1 - vaz), cred)
    a = unit * np.maximum(cred, 1e-6)
    usa_grupos = w["compacta"] > 0 or c.forma.distancia_max_km is not None or c.forma.area_min_contigua_ha
    # pré-seleção: as melhores por unidade da meta (e, na compacta, os melhores grupos inteiros)
    ordem = np.argsort(a / np.maximum(q, 1e-9))
    if usa_grupos:
        df = pd.DataFrame({"g": g, "a": a, "q": q})
        sg = df.groupby("g").agg(a=("a", "sum"), q=("q", "sum"))
        sg["r"] = (sg.a + w["compacta"] * o["custo_grupo_usd"]) / sg.q.clip(lower=1e-9)
        escolhidos, acc = [], 0.0
        for gid, row in sg.sort_values("r").iterrows():
            escolhidos.append(gid)
            acc += row.q
            if acc >= 3 * meta and len(escolhidos) >= 3:
                break
        cand = np.flatnonzero(np.isin(g, escolhidos))
        cand = cand[np.argsort(a[cand] / np.maximum(q[cand], 1e-9))][: int(o["candidatos_max"])]
    else:
        acc = np.cumsum(q[ordem])
        k = int(np.searchsorted(acc, 3 * meta)) + 1
        cand = ordem[: max(min(k, int(o["candidatos_max"])), min(len(ordem), 50))]
    if q[cand].sum() < meta:  # nem a pré-seleção alcança: pega tudo o que existe
        cand = ordem
    n = len(cand)
    gl = list(dict.fromkeys(g[cand])) if usa_grupos else []
    G = len(gl)
    gi = {x: i for i, x in enumerate(gl)}
    custo_obj = np.concatenate([a[cand], np.full(G, w["compacta"] * o["custo_grupo_usd"])])
    linhas, lb, ub = [], [], []
    linhas.append(coo_matrix(np.concatenate([q[cand], np.zeros(G)])[None, :]))
    lb.append(min(meta, q[cand].sum()))
    ub.append(np.inf)
    if c.forma.max_donos:
        linhas.append(coo_matrix(np.concatenate([np.ones(n), np.zeros(G)])[None, :]))
        lb.append(0)
        ub.append(c.forma.max_donos)
    if G:
        r_idx = np.arange(n)
        cols = np.concatenate([r_idx, n + np.array([gi[x] for x in g[cand]])])
        rows = np.concatenate([r_idx, r_idx])
        vals = np.concatenate([np.ones(n), -np.ones(n)])
        linhas.append(coo_matrix((vals, (rows, cols)), shape=(n, n + G)))  # x_i <= y_g
        lb += [-np.inf] * n
        ub += [0] * n
        if c.forma.distancia_max_km is not None:  # todas as fazendas num círculo do diâmetro pedido
            linhas.append(coo_matrix(np.concatenate([np.zeros(n), np.ones(G)])[None, :]))
            lb.append(1)
            ub.append(1)
        if c.forma.area_min_contigua_ha:
            area = f.area_ha.to_numpy(float)[cand]
            rows = np.concatenate([np.array([gi[x] for x in g[cand]]), np.arange(G)])
            cols = np.concatenate([np.arange(n), n + np.arange(G)])
            vals = np.concatenate([area, -np.full(G, c.forma.area_min_contigua_ha)])
            linhas.append(coo_matrix((vals, (rows, cols)), shape=(G, n + G)))
            lb += [0] * G
            ub += [np.inf] * G
        if mitig[cand].any():  # grupo usado leva a sua fazenda de mitigação
            mc = [i for i in range(n) if f.mitigacao.iloc[cand[i]]]
            rows = np.concatenate([np.arange(len(mc)), np.arange(len(mc))])
            cols = np.concatenate([np.array(mc), n + np.array([gi[g[cand[i]]] for i in mc])])
            vals = np.concatenate([np.ones(len(mc)), -np.ones(len(mc))])
            linhas.append(coo_matrix((vals, (rows, cols)), shape=(len(mc), n + G)))
            lb += [0] * len(mc)
            ub += [np.inf] * len(mc)
    A_ = vstack(linhas).tocsr()
    opcoes_milp = {"time_limit": float(o["tempo_limite_s"]), "mip_rel_gap": float(o["folga_gap"])}
    with _Calado():
        res = milp(c=custo_obj, constraints=[LinearConstraint(A_, lb=np.array(lb), ub=np.array(ub))],
                   integrality=np.ones(n + G), bounds=Bounds(0, 1), options=opcoes_milp)  # fmt: skip
    if res.x is not None:
        sel = cand[res.x[:n] > 0.5]
        estado = "otimo" if res.status == 0 else "limite_de_tempo"
    else:  # sem solução no tempo ou forma impossível: guloso pela ordem, respeitando o máximo de donos
        sel, acc = [], 0.0
        for i in cand if not usa_grupos else cand:
            if acc >= meta or (c.forma.max_donos and len(sel) >= c.forma.max_donos):
                break
            sel.append(i)
            acc += q[i]
        sel = np.array(sel, dtype=int)
        estado = "guloso" if res.status in (1,) else "inviavel"
    sel = sel[np.argsort(a[sel] / np.maximum(q[sel], 1e-9))]
    # reserva: as próximas, preferindo os mesmos grupos, até 10-20% da meta
    resto = np.setdiff1d(cand if len(cand) < len(f) else ordem, sel, assume_unique=False)
    if usa_grupos and len(sel):
        mesmos = np.isin(g[resto], g[sel])
        resto = np.concatenate([resto[mesmos], resto[~mesmos]])
    else:
        resto = resto[np.argsort(a[resto] / np.maximum(q[resto], 1e-9))]
    alvo_res = float(reserva_meta) if reserva_meta is not None else float(o["reserva_fracao"]) * meta
    k = int(np.searchsorted(np.cumsum(q[resto]), alvo_res)) + 1 if len(resto) and alvo_res > 0 else 0
    return {"sel": sel, "reserva": resto[:k], "estado": estado, "grupos": g, "mitigacao": mitig, "q": q}


# --- indicadores da opção (Opcao do contrato com o front) ----------------------------------------------------------


def _faixa_ponderada(f: pd.DataFrame, col: str, peso: np.ndarray) -> float | None:
    v = f[col].to_numpy(float)
    ok = np.isfinite(v) & (peso > 0)
    return float((v[ok] * peso[ok]).sum() / peso[ok].sum()) if ok.any() else None


def fazenda_do_lote(li: dict, papel: str, nivel: str, trocou: str | None = None) -> dict:
    return {
        "cod_imovel": li["cod_imovel"], "cod_ibge": str(li["cod_ibge"]) if li["cod_ibge"] is not None else "",
        "municipio": li.get("municipio") or "", "uf": li.get("uf") or "", "papel": papel,
        "hectares": round(float(li["area_ha"]), 2),
        "creditos": {q: round(float(li[f"credito_{q}"] or 0), 0) for q in ("p10", "p50", "p90")},
        "metodo": li["modo"], "caminho": li["caminho"],
        "custo_usd_credito": None if li["custo_credito_usd"] is None or (isinstance(li["custo_credito_usd"], float)
                                                                          and math.isnan(li["custo_credito_usd"]))
        else round(float(li["custo_credito_usd"]), 2),
        "pequena": bool(li["pequena"]), "interesse": nivel, "trocou": trocou,
        "lon": li["lon"], "lat": li["lat"], "local_aproximado": bool(li["local_aproximado"]),
        "risco_terra": li["risco_terra"],
    }  # fmt: skip


def cronograma_profloresta(sel: pd.DataFrame, c: CamposPedido) -> dict:
    """Marcos, multa e rescisão do lote no contrato do ProFloresta+ (restauracao.cronograma_lote): os créditos das
    fazendas até o fim do contrato (P50) contra o volume pedido."""
    from raiz import restauracao as R

    total = float(sel.credito_p50.sum())
    volume = float(c.meta.valor) if c.meta.tipo == "creditos" else total
    return R.cronograma_lote(total, volume=max(volume, 1e-9))


def marcos_do_lote(sel: pd.DataFrame, c: CamposPedido) -> list[dict]:
    """Chance de cumprir cada marco: no ProFloresta+, a do lote inteiro (cronograma_profloresta); com datas
    próprias, pela forma da curva e a faixa de cada fazenda."""
    if c.cronograma == "livre" or not len(sel):
        return []
    peso = sel.credito_p50.to_numpy(float)
    if c.cronograma == "profloresta":  # no lote inteiro, como o contrato mede (o erro da captura é comum às fazendas)
        cr = cronograma_profloresta(sel, c)
        return [{"ano": m["ano"], "fracao": m["fracao"], "chance": round(m["chance"], 3),
                 "multa_esperada_rs": round(m["multa_esperada_rs"], 0)} for m in cr["marcos"]]  # fmt: skip
    from raiz import restauracao as R

    forma = R.forma_curva()
    acum = np.cumsum(forma)
    tol = 0.25
    out = []
    for m in c.marcos_proprios or []:
        ano = min(m.ano, len(acum) - 1)
        parte = acum[ano] / acum[min(25, len(acum) - 1)]  # parte do volume do contrato capturada até o ano
        precisa = (1 - tol) * m.fracao / max(parte, 1e-9)  # múltiplo do P50 que a captura precisa atingir
        rel10 = (sel.credito_p10 / sel.credito_p50.where(sel.credito_p50 > 0)).fillna(1).to_numpy(float)
        sd = np.maximum(1 - rel10, 1e-6) / Z90
        from scipy.stats import norm

        ch = norm.sf((precisa - 1) / sd) if precisa > 1 else 1 - norm.cdf((precisa - 1) / sd)
        out.append({"ano": m.ano, "fracao": m.fracao, "chance": round(float((ch * peso).sum() / peso.sum()), 3)})
    return out


def indicadores(f: pd.DataFrame, sel_idx, res_idx, c: CamposPedido, opcao: str, chance: np.ndarray,
                niveis: dict[str, str], trocas: dict[str, str] | None = None,
                p: dict | None = None) -> dict:  # fmt: skip
    p = p or premissas()
    trocas = trocas or {}
    sel = f.iloc[list(sel_idx)].copy()
    res = f.iloc[list(res_idx)].copy()
    ch_sel = chance[list(sel_idx)] if len(sel_idx) else np.array([])
    res["chance_aceite"] = chance[list(res_idx)] if len(res_idx) else np.array([])
    meta = float(c.meta.valor)
    sim = simular(sel, ch_sel, p, res, meta if c.meta.tipo == "creditos" else None) if len(sel) else None
    cred = sim["creditos"] if sim else {"p10": 0.0, "p50": 0.0, "p90": 0.0}
    q = quantidade(sel, c.meta.tipo)
    total_meta = float(q.sum()) if c.meta.tipo != "creditos" else cred["p50"]
    falta = max(meta - total_meta, 0.0)
    peso = sel.credito_p50.to_numpy(float)
    cambio = float(sel.cambio.dropna().iloc[0]) if len(sel) and sel.cambio.notna().any() else 5.40
    custo50 = _faixa_ponderada(sel, "custo_credito_usd", peso)
    custo_total = (custo50 or 0) * cred["p50"]
    tir = {q_: _faixa_ponderada(sel, f"tir_{q_}", peso) for q_ in ("p10", "p50", "p90")}
    mistura = []
    for cam in CAMINHOS:
        s = sel.credito_p50[sel.caminho == cam].sum()
        if s > 0:
            mistura.append({"caminho": cam, "fracao": round(float(s / max(cred["p50"], 1e-9)), 3)})
    metodos = [{"metodo": m, "fazendas": int(n)} for m, n in sel.modo.value_counts().items()]
    itens = [fazenda_do_lote(li, "lote", niveis.get(li["cod_imovel"], "sem_contato"), trocas.get(li["cod_imovel"]))
             for li in sel.to_dict("records")]  # fmt: skip
    itens += [fazenda_do_lote(li, "reserva", niveis.get(li["cod_imovel"], "sem_contato"))
              for li in res.to_dict("records")]  # fmt: skip
    return {
        "id": opcao,
        "creditos": {k: round(v, 0) for k, v in cred.items()},
        "hectares": round(float(sel.area_ha.sum()), 1),
        "fazendas": int(len(sel)),
        "pequenas": int(sel.pequena.sum()),
        "tir": {k: (round(v, 1) if v is not None else None) for k, v in tir.items()},
        "custo_usd_credito": {
            "p10": round(custo_total / cred["p90"], 2) if cred["p90"] > 0 else None,
            "p50": round(custo50, 2) if custo50 is not None else None,
            "p90": round(custo_total / cred["p10"], 2) if cred["p10"] > 0 else None,
        },
        "pico_caixa_usd": round(float(sel.pico_rs.sum()) / cambio, 0),
        "marcos": marcos_do_lote(sel, c),
        "multa_esperada_usd": round(
            (
                cronograma_profloresta(sel, c)["multa_esperada_rs"]
                if c.cronograma == "profloresta" and len(sel)
                else float(sel.multa_rs.sum())
            )
            / cambio,
            0,
        ),
        "mistura_terra": mistura,
        "metodos": metodos,
        "itens": itens,
        "alcanca_meta": falta <= 0,
        "falta": round(falta, 0),
        "creditos_com_aceite": {k: round(v, 0) for k, v in (sim or {}).get("com_aceite", {}).items()} or None,
        "chance_fechar_com_aceite": None
        if not sim or sim.get("chance_fechar") is None
        else round(sim["chance_fechar"], 3),
        "aceite_medio": round(float(np.average(ch_sel, weights=np.maximum(peso, 1e-9))), 3) if len(sel) else None,
        "reserva_creditos": round(float(res.credito_p50.sum()), 0),
        "vpl_rs": round(float(sel.vpl_rs.sum()), 0),
        "abaixo_equilibrio": abaixo_equilibrio(f, sel, c),
    }


def abaixo_equilibrio(f: pd.DataFrame, sel: pd.DataFrame, c: CamposPedido) -> dict:
    """Quanto do lote vem de fazendas que o preço do pedido não paga (preço de equilíbrio acima dele) e se o lote só
    fecha com elas, com o aviso para o cliente."""
    preco = float(c.dinheiro.preco_venda_usd)
    ab = _abaixo_equilibrio(sel, preco) if len(sel) else np.zeros(0, dtype=bool)
    cred = sel.credito_p50.to_numpy(float) if len(sel) else np.zeros(0)
    total = float(cred.sum())
    q_base = quantidade(f, c.meta.tipo) if len(f) else np.zeros(0)
    pagas = float(q_base[~_abaixo_equilibrio(f, preco)].sum()) if len(f) else 0.0
    meta = float(c.meta.valor)
    n, cr = int(ab.sum()), float(cred[ab].sum())
    eq = sel.preco_equilibrio_usd.to_numpy(float)[ab] if n else np.zeros(0)
    eq_medio = float(np.average(eq, weights=np.maximum(cred[ab], 1e-9))) if n else None
    so_fecha = bool(n and pagas < meta)
    out = {
        "preco_usd": preco, "fazendas": n, "creditos": round(cr, 0),
        "fracao": round(cr / total, 3) if total > 0 else 0.0,
        "preco_equilibrio_medio_usd": round(eq_medio, 2) if eq_medio is not None else None,
        "metodos": {str(k): int(v) for k, v in sel.modo[ab].value_counts().items()} if n else {},
        "base_que_se_paga": round(pagas, 0), "so_fecha_com_elas": so_fecha, "aviso": None,
    }  # fmt: skip
    if n:

        def br(x: float) -> str:
            return f"{x:,.0f}".replace(",", ".")

        nomes = ", ".join(f"{v} de {NOMES_METODO.get(k, k)}" for k, v in out["metodos"].items())
        plantio = sum(v for k, v in out["metodos"].items() if k in ("plantio_total", "semeadura_direta"))
        oque = (
            "plantio abaixo do equilíbrio"
            if plantio == n
            else "fazendas abaixo do equilíbrio, inclusive plantio"
            if plantio
            else "fazendas abaixo do equilíbrio"
        )
        if so_fecha:
            out["aviso"] = (f"O lote só fecha com {oque}: {n} fazendas ({nomes}) somam "
                            f"{br(cr)} créditos ({out['fracao']:.0%} do lote) e pedem em média US$ {eq_medio:.0f} por "
                            f"crédito para pagar o retorno do capital; o pedido paga US$ {preco:.0f}. As fazendas que "
                            f"o preço paga somam {br(pagas)} créditos.")  # fmt: skip
        else:
            out["aviso"] = (
                f"{n} fazendas do lote ({nomes}, {out['fracao']:.0%} dos créditos) ficam abaixo do "
                f"equilíbrio a US$ {preco:.0f}; a base tem crédito que se paga para trocar por elas."
            )
    return out


def opcoes(oferta: pd.DataFrame, c: CamposPedido, niveis: dict[str, str] | None = None, fora: set[str] | None = None,
           historico: dict | None = None,
           pagamento: str = "participacao") -> tuple[dict, list[dict], pd.DataFrame]:  # fmt: skip
    """A base e as 3 opções. Devolve também a tabela filtrada (com a chance de aceite), para salvar o lote."""
    niveis, fora = niveis or {}, fora or set()
    p = premissas()
    b = base(oferta, c, niveis, fora)
    f = filtrar(oferta, c, niveis, fora).reset_index(drop=True)
    if not len(f):
        return b, [], f
    chance = A.chances(f, niveis, historico, pagamento)
    f["chance_aceite"] = chance
    out = []
    for op in ("barata", "segura", "compacta"):
        r = resolver(f, c, op, chance, p)
        ind = indicadores(f, r["sel"], r["reserva"], c, op, chance, niveis, p=p)
        ind["solver"] = r["estado"]
        out.append(ind)
    return b, out, f
