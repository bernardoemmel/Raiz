"""Valor de cada fazenda para quem restaura com crédito de carbono (o desenvolvedor), por imóvel.

Calculado pelo produto, fora do motor (motor/ não se edita): lê as colunas do motor pelo nome e as entradas
geográficas de raiz/restauracao_geo.py, aplica as premissas de raiz/regras/padroes/restauracao.yaml e o cenário
de raiz/regras/padroes/cenarios_restauracao.yaml, e grava desenvolvedor_<mun>.csv (docs/colunas.md).

Passo a passo por imóvel:
 1. modo de restauração (regeneração assistida, semeadura direta, plantio total) pela regra de pontos, por faixa de
    distância do pasto à mata;
 2. custo por ha P10/P50/P90 do modo, com ajustes de acesso, declividade e degradação do pasto;
 3. captura por ha P10/P50/P90 do modo, com ajustes de chuva e solo;
 4. desconto da linha de base dinâmica (VM0047): quanto viraria mata sozinho;
 5. crédito líquido = (captura - linha de base) x (1 - reserva de risco) x (1 - incerteza) x (1 - vazamento);
 6. fluxo de caixa por ha no cenário (VPL, TIR sem e com financiamento, pico de capital próprio), em faixa P10-P90
    por Monte Carlo;
 7. lote de fazendas vizinhas (agrupar).
Tudo é estimativa a calibrar com dado real de cliente (raiz/restauracao_aprendizado.py).
"""

from __future__ import annotations

import copy
import hashlib
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

PADROES = Path(__file__).parent / "regras" / "padroes"
ARQ_REGRA = PADROES / "restauracao.yaml"
ARQ_CENARIOS = PADROES / "cenarios_restauracao.yaml"
ARQ_CALIBRACAO = PADROES / "restauracao_calibracao.yaml"
C2CO2 = 44 / 12
RAIZ = 0.24  # raízes / parte aérea, igual ao motor
Z90 = 1.2815515655446004
FAIXAS = ("d0", "d1", "d2", "d3")  # até 100 m, 100 a 300 m, 300 m a 1 km, acima de 1 km (limites no YAML)


# --- regra, cenário e versão ---------------------------------------------------------------------------------------


@lru_cache
def _ler(regra: Path, cenarios: Path, calibracao: Path, _marcas: tuple = ()) -> dict:
    textos = [regra.read_bytes(), cenarios.read_bytes()]
    r = yaml.safe_load(textos[0])
    r["cenarios"] = yaml.safe_load(textos[1])
    r["calibracao"] = {}
    if calibracao.exists():
        textos.append(calibracao.read_bytes())
        r["calibracao"] = yaml.safe_load(textos[2]) or {}
    h = hashlib.sha256(b"\n--\n".join(textos)).hexdigest()[:8]
    r["versao_completa"] = f"{r['versao']}+{r['cenarios']['versao']}+{h}"
    return r


def _marca(p: Path) -> tuple:
    try:
        st = p.stat()
    except FileNotFoundError:
        return (str(p), None)
    return (str(p), st.st_mtime_ns, st.st_size)


def regra(regra: Path | None = None, cenarios: Path | None = None, calibracao: Path | None = None) -> dict:
    """As premissas (restauracao.yaml), os cenários e a calibração, com versao_completa = versões + hash dos três.
    Relê quando um dos arquivos muda (a recalibração grava enquanto a API está de pé)."""
    arqs = (Path(regra or ARQ_REGRA), Path(cenarios or ARQ_CENARIOS), Path(calibracao or ARQ_CALIBRACAO))
    return _ler(*arqs, tuple(_marca(a) for a in arqs))


def versao() -> str:
    return regra()["versao_completa"]


def cenario(nome: str | None = None, r: dict | None = None, **muda) -> dict:
    """Parâmetros do cenário (valores puros, sem a fonte), com herança e as mudanças do simulador."""
    r = r or regra()
    cs = r["cenarios"]["cenarios"]
    nome = nome or r["cenarios"]["padrao"]
    if nome not in cs:
        raise ValueError(f"cenário desconhecido: {nome}")
    bruto = copy.deepcopy(cs[nome])
    if "herda" in bruto:
        base = copy.deepcopy(cs[bruto.pop("herda")])
        base.update(bruto)
        bruto = base
    c = {k: (v["valor"] if isinstance(v, dict) and "valor" in v else v) for k, v in bruto.items()}
    c["cenario"] = nome
    for k, v in muda.items():
        if v is None:
            continue
        if k not in c:
            raise ValueError(f"parâmetro desconhecido no cenário: {k}")
        c[k] = v
    c["entregas_anos"] = sorted(int(a) for a in c["entregas_anos"] if 0 < int(a) <= int(c["prazo_anos"]))
    c["desembolso_custo"] = [float(x) for x in c["desembolso_custo"]]
    return c


def fontes_cenario(nome: str | None = None, r: dict | None = None) -> dict[str, str]:
    r = r or regra()
    cs = r["cenarios"]["cenarios"]
    nome = nome or r["cenarios"]["padrao"]
    bruto = dict(cs[cs[nome]["herda"]]) if "herda" in cs[nome] else {}
    bruto.update(cs[nome])
    return {k: v["fonte"] for k, v in bruto.items() if isinstance(v, dict) and "fonte" in v}


# --- leitura das colunas pelo nome -------------------------------------------------------------------------------


def _num(linha: dict, c: str) -> float | None:
    v = linha.get(c)
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _primeiro(linha: dict, *cols: str) -> float | None:
    for c in cols:
        x = _num(linha, c)
        if x is not None:
            return x
    return None


def _mb(linha: dict, indicador: str) -> float | None:
    from raiz.flag import _mb as mb

    return mb(linha, indicador)


def _verdade(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "sim", "t")
    try:
        return bool(v) and not (isinstance(v, float) and math.isnan(v))
    except (TypeError, ValueError):
        return False


def area_restauravel(linha: dict) -> float:
    """Pasto aberto fora da reserva legal e da APP (o pasto livre da conta FLAG; uso alternativo, nunca somado)."""
    alem = _num(linha, "alem_RL_ha") or 0.0
    app = _primeiro(linha, "app_recompor_ha", "app_desmatada_ha") or 0.0
    livre = max(alem - app, 0.0)
    pasto = _num(linha, "pasto_ha")
    pasto = _mb(linha, "pasto") if pasto is None else pasto
    return max(min(pasto if pasto is not None else livre, livre), 0.0)


def fracoes_distancia(linha: dict) -> tuple[list[float], str]:
    """Parte do pasto em cada faixa de distância à mata (d0..d3). Vem do raster (pasto_<faixa>_ha); sem ele, usa o
    pasto a até 1 km do motor, posto na faixa de 300 m a 1 km (conservador)."""
    ha = [_num(linha, f"pasto_{f}_ha") for f in FAIXAS]
    if all(x is not None for x in ha) and sum(ha) > 0:
        s = sum(ha)
        return [x / s for x in ha], "raster"
    pasto = _num(linha, "pasto_ha") or 0.0
    perto = _num(linha, "pasto_ate1km_ha")
    if pasto > 0 and perto is not None:
        p = min(perto / pasto, 1.0)
        return [0.0, 0.0, p, 1.0 - p], "motor"
    return [0.0, 0.0, 0.0, 1.0], "sem_dado"


def _idade_pasto(linha: dict) -> float | None:
    return _primeiro(linha, "mb_pasto_idade_anos_media", "pasto_idade_anos_media")


def _vigor_pasto(linha: dict) -> int | None:
    v = _num(linha, "mb_pasto_vigor_principal")
    if v is None:
        m = _num(linha, "pasto_vigor_media")
        v = None if m is None else round(m)
    return None if v is None or v < 1 else int(min(v, 3))


def pontos_imovel(linha: dict, r: dict | None = None) -> tuple[int, list[dict]]:
    """Pontos que valem para o imóvel inteiro (idade e vigor do pasto, fogo, declividade), com o porquê."""
    r = r or regra()
    m = r["regra_modo"]
    pts, det = 0, []
    idade = _idade_pasto(linha)
    p = 0
    if idade is not None:
        if idade <= m["idade_pasto"]["jovem_ate_anos"]:
            p = m["idade_pasto"]["pontos_jovem"]
        elif idade > m["idade_pasto"]["velho_acima_anos"]:
            p = m["idade_pasto"]["pontos_velho"]
    det.append({"fator": "idade_pasto", "valor": idade, "pontos": p})
    pts += p
    vigor = _vigor_pasto(linha)
    p = int(m["vigor_pasto"]["pontos"].get(vigor, 0)) if vigor is not None else 0
    det.append({"fator": "vigor_pasto", "valor": vigor, "pontos": p})
    pts += p
    fogo = _num(linha, "fogo_anos_media")
    p = 0
    if fogo is not None:
        if fogo <= m["fogo"]["pouco_ate"]:
            p = m["fogo"]["pontos_pouco"]
        elif fogo > m["fogo"]["muito_acima"]:
            p = m["fogo"]["pontos_muito"]
    det.append({"fator": "fogo_anos_media", "valor": fogo, "pontos": p})
    pts += p
    decl = _num(linha, "declividade_media_pct")
    p = m["declividade"]["pontos_ingreme"] if decl is not None and decl > m["declividade"]["ingreme_acima_pct"] else 0
    det.append({"fator": "declividade_media_pct", "valor": decl, "pontos": p})
    pts += p
    return pts, det


def modo_por_pontos(pontos: int, r: dict | None = None) -> str:
    r = r or regra()
    c = r["regra_modo"]["corte"]
    if pontos >= c["regeneracao_assistida"]:
        return "regeneracao_assistida"
    if pontos >= c["semeadura_direta"]:
        return "semeadura_direta"
    return "plantio_total"


def modos(linha: dict, r: dict | None = None) -> dict:
    """Área de cada modo, o modo do imóvel (maior área) e a regra aplicada, por faixa de distância."""
    r = r or regra()
    area = area_restauravel(linha)
    fr, fonte = fracoes_distancia(linha)
    base, det = pontos_imovel(linha, r)
    por_modo = {m: 0.0 for m in r["modos"]}
    faixas = []
    for f, frac, pd_ in zip(FAIXAS, fr, r["regra_modo"]["pontos_distancia"], strict=True):
        md = modo_por_pontos(base + pd_, r)
        por_modo[md] += area * frac
        faixas.append({"faixa": f, "fracao": round(frac, 4), "pontos": base + pd_, "modo": md})
    # empate: o modo mais barato com área (a ordem do YAML vai do mais barato ao mais caro)
    dominante = max(r["modos"], key=lambda md: (round(por_modo[md], 6), -r["modos"].index(md)))
    if area <= 0:  # sem área, o modo é o que a distância e o histórico indicariam
        dominante = max(faixas, key=lambda x: x["fracao"])["modo"]
    return {
        "area_ha": area,
        "por_modo_ha": por_modo,
        "modo": dominante,
        "fracoes": fr,
        "distancia_fonte": fonte,
        "pontos_imovel": base,
        "fatores": det,
        "faixas": faixas,
    }


# --- custo, captura, linha de base, líquido ---------------------------------------------------------------------


def _pesos(m: dict) -> dict[str, float]:
    a = sum(m["por_modo_ha"].values())
    if a <= 0:
        return {md: (1.0 if md == m["modo"] else 0.0) for md in m["por_modo_ha"]}
    return {md: v / a for md, v in m["por_modo_ha"].items()}


def _cal(r: dict, grupo: str, modo: str) -> float:
    return float((r.get("calibracao") or {}).get(grupo, {}).get(modo, {}).get("fator", 1.0))


def fator_custo(linha: dict, r: dict | None = None) -> tuple[float, list[dict]]:
    """Multiplicador do custo por acesso (OSM), declividade (Copernicus) e degradação do pasto."""
    r = r or regra()
    a = r["ajustes_custo"]
    f, det = 1.0, []
    ac = a["acesso"]
    km = _num(linha, "estrada_acesso_km")
    if km is not None:
        x = min(1 + ac["estrada_por_km"] * max(km - ac["estrada_livre_km"], 0), ac["estrada_teto"])
        det.append({"ajuste": "estrada", "valor": km, "fator": round(x, 4)})
        f *= x
    km = _num(linha, "cidade_proxima_km")
    if km is not None:
        x = min(1 + ac["cidade_por_km"] * max(km - ac["cidade_livre_km"], 0), ac["cidade_teto"])
        det.append({"ajuste": "cidade", "valor": km, "fator": round(x, 4)})
        f *= x
    decl = _num(linha, "declividade_media_pct")
    if decl is not None:
        i = sum(decl > lim for lim in a["declividade"]["limites_pct"])
        x = a["declividade"]["fatores"][i]
        det.append({"ajuste": "declividade", "valor": decl, "fator": x})
        f *= x
    if _vigor_pasto(linha) == 1:
        det.append({"ajuste": "vigor_baixo", "valor": 1, "fator": a["degradacao"]["vigor_baixo"]})
        f *= a["degradacao"]["vigor_baixo"]
    fogo = _num(linha, "fogo_anos_media")
    if fogo is not None and fogo > r["regra_modo"]["fogo"]["muito_acima"]:
        det.append({"ajuste": "fogo_frequente", "valor": fogo, "fator": a["degradacao"]["fogo_frequente"]})
        f *= a["degradacao"]["fogo_frequente"]
    return f, det


def custo(linha: dict, m: dict | None = None, r: dict | None = None) -> dict:
    """R$/ha P10/P50/P90: média dos modos pela área de cada um, vezes os ajustes."""
    r = r or regra()
    m = m or modos(linha, r)
    f, det = fator_custo(linha, r)
    w = _pesos(m)
    out = {}
    for q in ("p10", "p50", "p90"):
        out[q] = sum(w[md] * r["custo_rs_ha"][md][q] * _cal(r, "custo", md) for md in w) * f
    return {**out, "fator": f, "ajustes": det}


def _bioma(linha: dict, r: dict) -> str:
    b = linha.get("bioma")
    t = r["captura_tco2_ha_ano"]["plantio_total"]
    return b if isinstance(b, str) and b in t else r["captura_tco2_ha_ano"]["bioma_padrao"]


def taxa_regeneracao(linha: dict) -> float:
    """tCO2/ha/ano da regeneração natural que o motor já usa (taxa_tco2_ha_ano); sem ela, Heinrich leste."""
    t = _num(linha, "taxa_tco2_ha_ano")
    return t if t is not None and t > 0 else 1.3 * (1 + RAIZ) * C2CO2


def fator_captura(linha: dict, r: dict | None = None) -> tuple[float, list[dict]]:
    """Multiplicador da captura por chuva (CHIRPS) e solo (SoilGrids)."""
    r = r or regra()
    a = r["ajustes_captura"]
    f, det = 1.0, []
    chuva = _num(linha, "chuva_mm_ano")
    if chuva is not None and chuva > 0:
        ref = a["chuva"]["referencia_mm"].get(linha.get("bioma"), a["chuva"]["referencia_mm"]["Amazônia"])
        x = min(max((chuva / ref) ** a["chuva"]["elasticidade"], a["chuva"]["minimo"]), a["chuva"]["maximo"])
        det.append({"ajuste": "chuva", "valor": chuva, "fator": round(x, 4)})
        f *= x
    cec = _num(linha, "solo_cec_cmolc_kg")
    if cec is not None:
        s = a["solo"]
        x = min(max(1 + s["por_unidade"] * (cec - s["referencia_cec"]), s["minimo"]), s["maximo"])
        det.append({"ajuste": "solo", "valor": cec, "fator": round(x, 4)})
        f *= x
    return f, det


def captura_por_modo(linha: dict, r: dict | None = None) -> dict[str, dict[str, float]]:
    """tCO2/ha/ano P10/P50/P90 de cada modo, antes dos ajustes de chuva e solo."""
    r = r or regra()
    c = r["captura_tco2_ha_ano"]
    reg = c["regeneracao_assistida"]
    t = taxa_regeneracao(linha)
    p50 = t * reg["ganho_assistencia"]
    amz = (linha.get("bioma") or c["bioma_padrao"]) == "Amazônia"
    p10 = reg["p10_elias_tc_ha_ano"] * (1 + RAIZ) * C2CO2 if amz else p50 * reg["fator_p10"]
    out = {"regeneracao_assistida": {"p10": min(p10, p50), "p50": p50, "p90": p50 * reg["fator_p90"]}}
    b = _bioma(linha, r)
    for md in ("semeadura_direta", "plantio_total"):
        out[md] = {q: float(c[md][b][q]) for q in ("p10", "p50", "p90")}
    return out


def captura(linha: dict, m: dict | None = None, r: dict | None = None) -> dict:
    r = r or regra()
    m = m or modos(linha, r)
    f, det = fator_captura(linha, r)
    w = _pesos(m)
    pm = captura_por_modo(linha, r)
    out = {q: sum(w[md] * pm[md][q] * _cal(r, "captura", md) for md in w) * f for q in ("p10", "p50", "p90")}
    return {**out, "fator": f, "ajustes": det, "por_modo": pm}


def taxas_linha_base(linha: dict, r: dict | None = None) -> tuple[list[float], str]:
    """Taxa por ano com que o pasto vira mata sozinho em cada faixa (do município, medida no YbYrá; ou padrão)."""
    r = r or regra()
    lb = r["linha_base"]
    tx = [_num(linha, f"linha_base_taxa_{f}") for f in FAIXAS]
    if all(x is not None for x in tx):
        return [min(max(x, 0.0), lb["taxa_ano_maxima"]) for x in tx], str(linha.get("linha_base_fonte") or "ybyra")
    return [float(x) for x in lb["taxa_ano_padrao"]], "padrao"


def linha_base(linha: dict, anos: int, m: dict | None = None, r: dict | None = None) -> dict:
    """Desconto da linha de base dinâmica (VM0047): sem projeto, uma fração do pasto vira mata sozinha e captura à
    taxa da regeneração natural. Média por ano no prazo: taxa_regeneração x média de F(t), com F(t) = 1 - (1-q)^t."""
    r = r or regra()
    m = m or modos(linha, r)
    taxas, fonte = taxas_linha_base(linha, r)
    persist = r["linha_base"]["persistencia"]
    t = np.arange(1, anos + 1)
    media, final = 0.0, 0.0
    for frac, q in zip(m["fracoes"], taxas, strict=True):
        F = 1 - (1 - q) ** t
        media += frac * float(F.mean()) * persist
        final += frac * float(F[-1]) * persist
    g = taxa_regeneracao(linha)
    return {
        "tco2_ha_ano": g * media,
        "fracao_media": media,  # parte do pasto que, em média no prazo, está regenerando sozinha
        "regenera_ate_o_fim": final,  # parte que estaria em mata no fim do prazo
        "taxas_ano": taxas,
        "fonte": fonte,
    }


def liquido(captura_t: float, base_t: float, r: dict | None = None) -> float:
    r = r or regra()
    q = r["liquido"]
    return max(captura_t - base_t, 0.0) * (1 - q["reserva_risco"]) * (1 - q["incerteza"]) * (1 - q["vazamento"])


# --- fluxo de caixa por hectare ----------------------------------------------------------------------------------


def coeficientes(c: dict) -> dict[str, np.ndarray]:
    """O fluxo por ha é linear no custo e no crédito: fluxo_t = custo x A_t + crédito x B_t + C_t (projeto) e
    custo x (A_t + D_t) + crédito x B_t + C_t (com financiamento). Devolve A, B, C, D por ano (0..prazo)."""
    T = int(c["prazo_anos"])
    A, B, C, D = (np.zeros(T + 1) for _ in range(4))
    for i, f in enumerate(c["desembolso_custo"]):
        if i <= T:
            A[i] -= f
    preco = c["preco_usd_t"] * c["cambio_brl_usd"]
    unit = preco * (1 - c["tributos_receita"]) - c["taxa_registro_usd_t"] * c["cambio_brl_usd"]
    ant = 0
    for e in c["entregas_anos"]:
        B[e] += (e - ant) * unit  # entrega o acumulado desde a anterior
        C[e] -= c["verificacao_rs_ha_entrega"]
        ant = e
    for t in range(1, T + 1):
        C[t] -= c["monitoramento_rs_ha_ano"] + c["arrendamento_rs_ha_ano"]
        if t >= c["manutencao_desde_ano"]:
            C[t] -= c["manutencao_rs_ha_ano"]
    # financiamento de uma fração de cada desembolso; juros pagos na carência; depois SAC ou Price
    fin, j, car, amo = c["fracao_financiada"], c["juros_ano"], int(c["carencia_anos"]), int(c["amortizacao_anos"])
    saldo, L = 0.0, 0.0
    for t in range(T + 1):
        juros = saldo * j
        if 1 <= t <= car:
            D[t] -= juros
        elif car < t <= car + amo and saldo > 1e-12:
            n = car + amo - t + 1
            if c["sistema_amortizacao"] == "price":
                pmt = saldo * j / (1 - (1 + j) ** -n) if j > 0 else saldo / n
                D[t] -= pmt
                saldo -= pmt - juros
            else:
                if t == car + 1:
                    L = saldo
                a = min(L / amo, saldo)
                D[t] -= a + juros
                saldo -= a
        if t < len(c["desembolso_custo"]):
            D[t] += fin * c["desembolso_custo"][t]
            saldo += fin * c["desembolso_custo"][t]
    if saldo > 1e-9 and T >= 0:  # o que sobrar da dívida no fim do prazo é quitado no último ano
        D[T] -= saldo
    return {"A": A, "B": B, "C": C, "D": D}


def _tir(custo: np.ndarray, credito: np.ndarray, X: np.ndarray, B: np.ndarray, C: np.ndarray) -> np.ndarray:
    """TIR por bisseção, vetorizada nos sorteios. NaN onde não há troca de sinal no intervalo (-99%, 300%)."""
    t = np.arange(len(B))

    def vpl(r):
        d = (1 + r[:, None]) ** -t[None, :] if np.ndim(r) else (1 + r) ** -t
        if np.ndim(r):
            return custo * (d @ X) + credito * (d @ B) + (d @ C)
        return custo * (X @ d) + credito * (B @ d) + (C @ d)

    n = len(custo)
    lo, hi = np.full(n, -0.99), np.full(n, 3.0)
    flo, fhi = vpl(lo), vpl(hi)
    ok = np.sign(flo) != np.sign(fhi)
    for _ in range(64):
        mid = (lo + hi) / 2
        fm = vpl(mid)
        mesmo = np.sign(fm) == np.sign(flo)
        lo = np.where(mesmo, mid, lo)
        flo = np.where(mesmo, fm, flo)
        hi = np.where(mesmo, hi, mid)
    return np.where(ok, (lo + hi) / 2, np.nan)


def indicadores(custo, credito, c: dict, k: dict | None = None) -> dict[str, np.ndarray]:
    """VPL na taxa do cenário, TIR do projeto, TIR com financiamento e pico de capital próprio (R$/ha, positivo),
    para vetores de custo (R$/ha) e crédito líquido (t/ha/ano)."""
    k = k or coeficientes(c)
    custo = np.atleast_1d(np.asarray(custo, dtype=float))
    credito = np.atleast_1d(np.asarray(credito, dtype=float))
    custo, credito = np.broadcast_arrays(custo, credito)
    t = np.arange(len(k["B"]))
    d = (1 + c["taxa_desconto"]) ** -t
    vpl = custo * (k["A"] @ d) + credito * (k["B"] @ d) + k["C"] @ d
    X = k["A"] + k["D"]
    acum = np.cumsum(custo[:, None] * X[None, :] + credito[:, None] * k["B"][None, :] + k["C"][None, :], axis=1)
    return {
        "vpl_rs_ha": vpl,
        "tir_projeto": _tir(custo, credito, k["A"], k["B"], k["C"]),
        "tir_alavancada": _tir(custo, credito, X, k["B"], k["C"]),
        "pico_capital_proprio_rs_ha": np.maximum(-acum.min(axis=1), 0.0),
    }


def fluxo_caixa(custo_rs_ha: float, credito_tco2_ha_ano: float, c: dict | None = None) -> dict:
    """Fluxo por ha, ano a ano, e os indicadores (TIR em fração ao ano; None se não existir)."""
    c = c or cenario()
    k = coeficientes(c)
    ind = indicadores(custo_rs_ha, credito_tco2_ha_ano, c, k)
    proj = custo_rs_ha * k["A"] + credito_tco2_ha_ano * k["B"] + k["C"]
    alav = proj + custo_rs_ha * k["D"]

    def f(x):
        x = float(x[0])
        return None if math.isnan(x) else x

    return {
        "anos": list(range(len(proj))),
        "projeto_rs_ha": [round(float(x), 2) for x in proj],
        "com_financiamento_rs_ha": [round(float(x), 2) for x in alav],
        "vpl_rs_ha": f(ind["vpl_rs_ha"]),
        "tir_projeto": f(ind["tir_projeto"]),
        "tir_alavancada": f(ind["tir_alavancada"]),
        "pico_capital_proprio_rs_ha": f(ind["pico_capital_proprio_rs_ha"]),
        "cenario": c,
    }


@lru_cache
def _sorteios(n: int, semente: int) -> tuple[np.ndarray, np.ndarray]:
    g = np.random.default_rng(semente)
    return g.standard_normal(n), g.standard_normal(n)


def _dois_lados(z: np.ndarray, p10: float, p50: float, p90: float) -> np.ndarray:
    """Normal de dois lados que respeita P10, P50 e P90 (largura diferente abaixo e acima da mediana)."""
    lo, hi = (p50 - p10) / Z90, (p90 - p50) / Z90
    return np.maximum(p50 + np.where(z < 0, z * lo, z * hi), 0.0)


def faixa_fluxo(cus: dict, cap: dict, base_t: float, c: dict, r: dict | None = None) -> dict:
    """P10/P50/P90 do VPL, das TIRs (em %) e do pico de capital próprio, por Monte Carlo (sorteios comuns a todos os
    imóveis: a ordem entre fazendas não depende da sorte)."""
    r = r or regra()
    mc = r["cenarios"]["monte_carlo"]
    zc, zk = _sorteios(int(mc["sorteios"]), int(mc["semente"]))
    custos = _dois_lados(zc, cus["p10"], cus["p50"], cus["p90"])
    capt = _dois_lados(zk, cap["p10"], cap["p50"], cap["p90"])
    q = r["liquido"]
    cred = np.maximum(capt - base_t, 0.0) * (1 - q["reserva_risco"]) * (1 - q["incerteza"]) * (1 - q["vazamento"])
    ind = indicadores(custos, cred, c)
    out = {}
    for nome, v in ind.items():
        if nome.startswith("tir"):
            v = np.where(np.isnan(v), -1.0, v) * 100  # sem TIR = perde tudo
        for p in (10, 50, 90):
            out[f"{nome}_p{p}"] = float(np.percentile(v, p))
    return out


# --- por imóvel ------------------------------------------------------------------------------------------------


def faltou(linha: dict) -> list[str]:
    """Entradas que faltaram e viraram premissa neutra (fator 1, taxa padrão...): a ficha mostra."""
    f = []
    if fracoes_distancia(linha)[1] != "raster":
        f.append("distancia_mata")
    for c, nome in (
        ("declividade_media_pct", "declividade"),
        ("chuva_mm_ano", "chuva"),
        ("solo_cec_cmolc_kg", "solo"),
        ("estrada_acesso_km", "acesso"),
        ("fogo_anos_media", "fogo"),
    ):
        if _num(linha, c) is None:
            f.append(nome)
    if _idade_pasto(linha) is None:
        f.append("idade_pasto")
    if _vigor_pasto(linha) is None:
        f.append("vigor_pasto")
    if taxas_linha_base(linha)[1] == "padrao":
        f.append("linha_base_municipio")
    return f


def por_imovel(linha: dict, c: dict | None = None, r: dict | None = None) -> dict:
    """Colunas de desenvolvedor_<mun>.csv para um imóvel (sem as do lote, que dependem dos vizinhos)."""
    r = r or regra()
    c = c or cenario(r=r)
    m = modos(linha, r)
    cus = custo(linha, m, r)
    cap = captura(linha, m, r)
    lb = linha_base(linha, int(c["prazo_anos"]), m, r)
    base_t = lb["tco2_ha_ano"]
    cred = {q: liquido(cap[q], base_t, r) for q in ("p10", "p50", "p90")}
    fx = faixa_fluxo(cus, cap, base_t, c, r)
    area = m["area_ha"]
    out = {
        "restauracao_area_ha": round(area, 4),
        "modo_restauracao": m["modo"],
        "modo_restauracao_pontos": m["pontos_imovel"],
        "modo_restauracao_regra": "; ".join(
            f"{x['faixa']} {x['fracao']:.0%} {x['pontos']} pts {x['modo']}" for x in m["faixas"] if x["fracao"] > 0
        ),
        **{f"restauracao_{md}_ha": round(v, 4) for md, v in m["por_modo_ha"].items()},
        "distancia_fonte": m["distancia_fonte"],
        "custo_restauracao_ha_p10": round(cus["p10"], 0),
        "custo_restauracao_ha_p50": round(cus["p50"], 0),
        "custo_restauracao_ha_p90": round(cus["p90"], 0),
        "custo_fator_ajuste": round(cus["fator"], 4),
        "captura_tco2_ha_ano_p10": round(cap["p10"], 2),
        "captura_tco2_ha_ano_p50": round(cap["p50"], 2),
        "captura_tco2_ha_ano_p90": round(cap["p90"], 2),
        "captura_fator_ajuste": round(cap["fator"], 4),
        "desconto_linha_base": round(base_t, 3),
        "desconto_linha_base_pct": round(100 * base_t / cap["p50"], 1) if cap["p50"] > 0 else 0.0,
        "linha_base_regenera_pct": round(100 * lb["regenera_ate_o_fim"], 1),
        "linha_base_fonte": lb["fonte"],
        "credito_liquido_tco2_ha_ano": round(cred["p50"], 3),
        "credito_liquido_tco2_ha_ano_p10": round(cred["p10"], 3),
        "credito_liquido_tco2_ha_ano_p90": round(cred["p90"], 3),
        "credito_liquido_tco2_ano": round(cred["p50"] * area, 1),
        "vpl_rs_ha_p10": round(fx["vpl_rs_ha_p10"], 0),
        "vpl_rs_ha_p50": round(fx["vpl_rs_ha_p50"], 0),
        "vpl_rs_ha_p90": round(fx["vpl_rs_ha_p90"], 0),
        "tir_projeto_pct_p10": round(fx["tir_projeto_p10"], 1),
        "tir_projeto_pct_p50": round(fx["tir_projeto_p50"], 1),
        "tir_projeto_pct_p90": round(fx["tir_projeto_p90"], 1),
        "tir_alavancada_pct_p10": round(fx["tir_alavancada_p10"], 1),
        "tir_alavancada_pct_p50": round(fx["tir_alavancada_p50"], 1),
        "tir_alavancada_pct_p90": round(fx["tir_alavancada_p90"], 1),
        "pico_capital_proprio_rs_ha_p10": round(fx["pico_capital_proprio_rs_ha_p10"], 0),
        "pico_capital_proprio_rs_ha_p50": round(fx["pico_capital_proprio_rs_ha_p50"], 0),
        "pico_capital_proprio_rs_ha_p90": round(fx["pico_capital_proprio_rs_ha_p90"], 0),
        "valor_desenvolvedor_rs": round(fx["vpl_rs_ha_p50"] * area, 0),
        "restauracao_faltou": ",".join(faltou(linha)),
        "restauracao_cenario": c["cenario"],
        "restauracao_versao": r["versao_completa"],
    }
    return out


# --- lote de fazendas vizinhas ---------------------------------------------------------------------------------


def elegivel(linha: dict) -> bool:
    """Entra no lote: tem área para restaurar e nada que bloqueie o contrato (pequena nunca sai por tamanho)."""
    if area_restauravel(linha) <= 0:
        return False
    if _verdade(linha.get("problema")):
        return False
    # terra pública sem destinação e terra indígena ou tradicional só aparecem no mapa: não entram em lote
    if linha.get("caminho_terra") in ("publica_sem_destinacao", "terra_indigena_ou_tradicional"):
        return False
    return str(linha.get("filtro_territorial") or "").lower() != "bloqueio"


def agrupar(pontos: list[tuple[str, float, float]], r: dict | None = None) -> dict[str, int]:
    """Lotes por ligação completa: fazendas cujos pontos (lon, lat) cabem num diâmetro de diametro_max_km.
    Municípios grandes são cortados em quadros de 0,5 grau antes, para a conta caber na memória."""
    from scipy.cluster.hierarchy import fcluster, linkage

    r = r or regra()
    if not pontos:
        return {}
    dmax = float(r["agrupamento"]["diametro_max_km"])
    cods = [p[0] for p in pontos]
    xy = np.array([[p[1], p[2]] for p in pontos], dtype=float)
    lat0 = float(np.radians(np.nanmean(xy[:, 1])))
    km = np.column_stack([xy[:, 0] * 111.32 * math.cos(lat0), xy[:, 1] * 110.57])
    quadro = [f"{math.floor(x / 0.5)}_{math.floor(y / 0.5)}" for x, y in xy]
    out, prox = {}, 1
    for q in sorted(set(quadro)):
        idx = [i for i, qq in enumerate(quadro) if qq == q]
        if len(idx) == 1:
            out[cods[idx[0]]] = prox
            prox += 1
            continue
        rot = fcluster(linkage(km[idx], method="complete"), t=dmax, criterion="distance")
        mapa = {}
        for i, g in zip(idx, rot, strict=True):
            if g not in mapa:
                mapa[g] = prox
                prox += 1
            out[cods[i]] = mapa[g]
    return out


def colunas_do_lote(df, cod_municipio: int, c: dict, r: dict | None = None):
    """Soma por lote: imóveis, ha, crédito por ano, créditos no prazo e se fecha o contrato de referência."""
    r = r or regra()
    alvo = float(r["agrupamento"]["contrato_creditos"])
    prazo = int(c["prazo_anos"])
    g = df[df.grupo_id.notna()].groupby("grupo_id")
    soma = g.agg(
        grupo_imoveis=("cod_imovel", "count"),
        grupo_ha=("restauracao_area_ha", "sum"),
        grupo_credito_tco2_ano=("credito_liquido_tco2_ano", "sum"),
    )
    soma["grupo_creditos_prazo"] = soma.grupo_credito_tco2_ano * prazo
    soma["grupo_fecha_contrato"] = soma.grupo_creditos_prazo >= alvo
    taxa = (soma.grupo_credito_tco2_ano / soma.grupo_ha).where(soma.grupo_ha > 0)
    soma["grupo_ha_para_contrato"] = (alvo / (taxa * prazo)).where(taxa > 0)
    casas = {"grupo_ha": 2, "grupo_credito_tco2_ano": 1, "grupo_creditos_prazo": 0, "grupo_ha_para_contrato": 0}
    soma = soma.round(casas)
    return df.merge(soma, left_on="grupo_id", right_index=True, how="left")


# --- por município (saida/<UF>/desenvolvedor_<mun>.csv) ----------------------------------------------------------

ENTRADAS = ("filtros", "mapbiomas", "extras", "direto", "ficha", "terra")
COLS_FICHA = ("estrada_acesso_km", "cidade_proxima_km")


def linhas_do_municipio(pasta: Path, cod: int):
    """imoveis_<mun>.csv com os complementos que existirem (lidos pelo nome; sem colunas pessoais)."""
    import pandas as pd

    from raiz.privacidade import remover_colunas_pessoais

    im, _ = remover_colunas_pessoais(pd.read_csv(pasta / f"imoveis_{cod}.csv", low_memory=False))
    for tipo in ENTRADAS:
        f = pasta / f"{tipo}_{cod}.csv"
        if f.exists():
            extra = pd.read_csv(f, low_memory=False)
            if tipo == "ficha":
                extra = extra[[c for c in extra.columns if c == "cod_imovel" or c in COLS_FICHA]]
            if tipo == "terra":
                extra = extra[[c for c in extra.columns if c in ("cod_imovel", "caminho_terra")]]
            novas = [c for c in extra.columns if c == "cod_imovel" or c not in im.columns]
            im = im.merge(extra[novas].drop_duplicates("cod_imovel"), on="cod_imovel", how="left")
    im["cod_imovel"] = im.cod_imovel.astype(str)
    return im


def calcular_municipio(
    pasta: str | Path,
    cod: int,
    cache_motor: Path | None = None,
    cache: Path | None = None,
    nome_cenario: str | None = None,
    fontes_geo: tuple[str, ...] = ("faixas", "declividade", "chuva", "solo"),
):
    """desenvolvedor_<mun>.csv (DataFrame) a partir das saídas do motor e das entradas geográficas."""
    import geopandas as gpd
    import pandas as pd

    from raiz import restauracao_geo as G

    pasta = Path(pasta)
    r = regra()
    c = cenario(nome_cenario, r)
    im = linhas_do_municipio(pasta, cod)
    geo_f = pasta / f"geo_{cod}.parquet"
    por, mun, pontos = {}, {}, {}
    if geo_f.exists():
        import shapely

        geo = gpd.read_parquet(geo_f)[["cod_imovel", "geometry"]]
        g4326 = geo.to_crs(4326)
        pts = shapely.point_on_surface(g4326.geometry.values)
        pontos = {str(c): (float(p.x), float(p.y)) for c, p in zip(g4326.cod_imovel, pts, strict=True)}
        if fontes_geo:
            uf = pasta.name.upper()
            cob = sorted((Path(cache_motor) / "mapbiomas" / uf).glob(f"{uf}_cobertura_2*.tif")) if cache_motor else []
            cob = [f for f in cob if f.stem.count("_") == 2]  # PA_cobertura_2025.tif (não as séries por ano)
            por, mun = G.entradas_municipio(geo, cod, cob[-1] if cob else None, cache, fontes_geo)
            mun.pop("pontos", None)
    linhas = []
    for linha in im.to_dict("records"):
        cod_im = linha["cod_imovel"]
        linha = {**linha, **por.get(cod_im, {}), **{k: v for k, v in mun.items() if k.startswith("linha_base_")}}
        calc = por_imovel(linha, c, r)
        geo_cols = {k: por.get(cod_im, {}).get(k) for k in (
            "pasto_d0_ha", "pasto_d1_ha", "pasto_d2_ha", "pasto_d3_ha",
            "declividade_media_pct", "chuva_mm_ano", "solo_cec_cmolc_kg")}  # fmt: skip
        linhas.append({"cod_imovel": cod_im, **geo_cols, **calc, "_elegivel": elegivel(linha)})
    df = pd.DataFrame(linhas)
    for f in FAIXAS:
        df[f"linha_base_taxa_{f}"] = mun.get(f"linha_base_taxa_{f}")
    # lote: só quem pode entrar e tem ponto no mapa
    eleg = [(cd, *pontos[cd]) for cd, ok in zip(df.cod_imovel, df._elegivel, strict=True) if ok and cd in pontos]
    rot = agrupar(eleg, r)
    df["grupo_id"] = [f"{cod}-{rot[cd]:04d}" if cd in rot else None for cd in df.cod_imovel]
    df = colunas_do_lote(df.drop(columns="_elegivel"), cod, c, r)
    return df


def versao_do_arquivo(f: Path) -> str | None:
    import pandas as pd

    if not f.exists():
        return None
    v = pd.read_csv(f, usecols=lambda col: col == "restauracao_versao", nrows=1)
    return str(v.restauracao_versao.iloc[0]) if len(v) and "restauracao_versao" in v else None


def escrever_municipio(pasta: Path, cod: int, cache_motor: Path | None = None, cache: Path | None = None) -> dict:
    t = calcular_municipio(pasta, cod, cache_motor, cache)
    f = Path(pasta) / f"desenvolvedor_{cod}.csv"
    tmp = f.with_suffix(".tmp")
    t.to_csv(tmp, index=False)
    tmp.replace(f)
    return {
        "imoveis": len(t),
        "area_ha": round(float(t.restauracao_area_ha.sum()), 1),
        "credito_tco2_ano": round(float(t.credito_liquido_tco2_ano.sum()), 1),
        "lotes": int(t.grupo_id.nunique()),
        "lotes_fecham_contrato": int(t.drop_duplicates("grupo_id").grupo_fecha_contrato.fillna(False).sum()),
    }


def recalcular(saida: str | Path, ufs: list[str] | None = None, cache_motor: Path | None = None,
               cache: Path | None = None) -> dict:  # fmt: skip
    """Refaz desenvolvedor_<mun>.csv onde falta ou foi calculado com outra versão das premissas ou do cenário."""
    from raiz.carga import municipios_na_pasta

    saida = Path(saida)
    atual = versao()
    out = {"refeitos": [], "em_dia": 0, "erros": []}
    for uf in ufs or sorted(p.name for p in saida.iterdir() if p.is_dir() and len(p.name) == 2):
        pasta = saida / uf
        for cod in municipios_na_pasta(pasta):
            if versao_do_arquivo(pasta / f"desenvolvedor_{cod}.csv") == atual:
                out["em_dia"] += 1
                continue
            try:
                escrever_municipio(pasta, cod, cache_motor, cache)
                out["refeitos"].append(f"{uf}/{cod}")
            except Exception as e:  # noqa: BLE001 - um município com problema não para o estado
                out["erros"].append(f"{uf}/{cod}: {e}")
    return out


# --- ficha e simulador (API) -------------------------------------------------------------------------------------

TEXTO_FALTOU = {
    "distancia_mata": "distância do pasto à mata (sem o raster de cobertura: usado o pasto a até 1 km do motor)",
    "declividade": "declividade (Copernicus GLO-30): custo sem ajuste de relevo",
    "chuva": "chuva (CHIRPS): captura sem ajuste de chuva",
    "solo": "solo (SoilGrids): captura sem ajuste de solo",
    "acesso": "distância da estrada e da cidade (OpenStreetMap): custo sem ajuste de acesso",
    "fogo": "histórico de fogo: modo sem o fator fogo",
    "idade_pasto": "idade do pasto: modo sem o fator idade",
    "vigor_pasto": "vigor do pasto: modo e custo sem o fator vigor",
    "linha_base_municipio": "linha de base medida no município (YbYrá): usada a taxa padrão das premissas",
}
CENARIO_EDITAVEL = (
    "preco_usd_t", "prazo_anos", "entregas_anos", "fracao_financiada", "juros_ano", "carencia_anos",
    "amortizacao_anos", "sistema_amortizacao", "taxa_desconto", "cambio_brl_usd", "manutencao_rs_ha_ano",
    "monitoramento_rs_ha_ano", "verificacao_rs_ha_entrega", "taxa_registro_usd_t", "tributos_receita",
    "arrendamento_rs_ha_ano",
)  # fmt: skip


def _faixa(linha: dict, base: str, nd: int = 1) -> dict | None:
    v = {q: _num(linha, f"{base}_{q}") for q in ("p10", "p50", "p90")}
    if v["p50"] is None:
        return None
    return {q: (round(x, nd) if x is not None else None) for q, x in v.items()}


def bloco_ficha(linha: dict, r: dict | None = None) -> dict:
    """Bloco "Para quem restaura" da ficha, a partir das colunas de desenvolvedor_<mun>.csv já carregadas."""
    r = r or regra()
    modo = linha.get("modo_restauracao")
    if not isinstance(modo, str) or modo not in r["modos"]:
        return {
            "disponivel": False,
            "mensagem": "O valor para quem restaura ainda não foi calculado para este município.",
            "aviso": r["aviso"],
        }
    c = cenario(linha.get("restauracao_cenario") or None, r)
    area = _num(linha, "restauracao_area_ha") or 0.0
    fl = [x for x in str(linha.get("restauracao_faltou") or "").split(",") if x]
    base_pct = _num(linha, "desconto_linha_base_pct") or 0.0
    regenera = _num(linha, "linha_base_regenera_pct") or 0.0
    cred = {
        "p10": _num(linha, "credito_liquido_tco2_ha_ano_p10"),
        "p50": _num(linha, "credito_liquido_tco2_ha_ano"),
        "p90": _num(linha, "credito_liquido_tco2_ha_ano_p90"),
    }
    grupo = linha.get("grupo_id")
    tem_grupo = isinstance(grupo, str) and bool(grupo)
    q = r["liquido"]
    return {
        "disponivel": True,
        "aviso": r["aviso"],
        "versao": linha.get("restauracao_versao"),
        "area_ha": round(area, 2),
        "area_regra": r["area"]["regra"],
        "modo": {
            "id": modo,
            "nome": r["nomes_modos"][modo],
            "pontos_imovel": _num(linha, "modo_restauracao_pontos"),
            "por_faixa": linha.get("modo_restauracao_regra"),
            "por_modo_ha": {md: _num(linha, f"restauracao_{md}_ha") for md in r["modos"]},
            "regra": r["regra_modo"]["texto"],
        },
        "custo_rs_ha": {
            **(_faixa(linha, "custo_restauracao_ha", 0) or {}),
            "fator_ajuste": _num(linha, "custo_fator_ajuste"),
        },  # fmt: skip
        "captura_tco2_ha_ano": {
            **(_faixa(linha, "captura_tco2_ha_ano", 2) or {}),
            "fator_ajuste": _num(linha, "captura_fator_ajuste"),
        },  # fmt: skip
        "linha_base": {
            "desconto_tco2_ha_ano": _num(linha, "desconto_linha_base"),
            "desconto_pct_da_captura": base_pct,
            "regenera_sozinha_ate_o_fim_pct": regenera,
            "fonte": linha.get("linha_base_fonte"),
            "metodo": r["linha_base"]["metodo"],
            "explicacao": (
                f"Sem projeto, cerca de {regenera:.0f}% deste pasto viraria mata sozinho em {c['prazo_anos']} anos. "
                f"Esse carbono não vira crédito: o desconto é de {base_pct:.0f}% da captura."
            ),
        },
        "credito_liquido_tco2_ha_ano": cred,
        "credito_liquido_tco2_ano": _num(linha, "credito_liquido_tco2_ano"),
        "do_bruto_ao_liquido": {
            "reserva_risco": q["reserva_risco"],
            "incerteza": q["incerteza"],
            "vazamento": q["vazamento"],
            "vazamento_situacao": "pendente: gado deslocado (VMD0054) ainda não medido" if q["vazamento"] == 0 else "",
        },
        "vpl_rs_ha": _faixa(linha, "vpl_rs_ha", 0),
        "tir_projeto_pct": _faixa(linha, "tir_projeto_pct", 1),
        "tir_alavancada_pct": _faixa(linha, "tir_alavancada_pct", 1),
        "pico_capital_proprio_rs_ha": _faixa(linha, "pico_capital_proprio_rs_ha", 0),
        "valor_desenvolvedor_rs": _num(linha, "valor_desenvolvedor_rs"),
        "cenario": {k: c[k] for k in ("cenario", "nome", *CENARIO_EDITAVEL) if k in c},
        "lote": {
            "grupo_id": grupo,
            "imoveis": _num(linha, "grupo_imoveis"),
            "ha": _num(linha, "grupo_ha"),
            "credito_tco2_ano": _num(linha, "grupo_credito_tco2_ano"),
            "creditos_no_prazo": _num(linha, "grupo_creditos_prazo"),
            "fecha_contrato": _verdade(linha.get("grupo_fecha_contrato")),
            "contrato_creditos": r["agrupamento"]["contrato_creditos"],
            "ha_para_contrato": _num(linha, "grupo_ha_para_contrato"),
        }
        if tem_grupo
        else None,
        "faltou": [{"id": x, "texto": TEXTO_FALTOU.get(x, x)} for x in fl],
        "premissas": {
            "custo": {md: r["custo_rs_ha"][md]["fonte"] for md in r["modos"]},
            "captura": {md: r["captura_tco2_ha_ano"][md]["fonte"] for md in r["modos"]},
            "modo": r["regra_modo"]["fonte"],
            "linha_base": r["linha_base"]["fonte"],
            "liquido": r["liquido"]["fonte"],
            "cenario": fontes_cenario(c["cenario"], r),
        },
    }


def simular(linha: dict, nome_cenario: str | None = None, r: dict | None = None, **muda) -> dict:
    """Simulador da ficha: refaz o imóvel com os parâmetros do cenário editados, com o fluxo ano a ano (P50)."""
    r = r or regra()
    c = cenario(nome_cenario or linha.get("restauracao_cenario") or None, r, **muda)
    calc = por_imovel(linha, c, r)
    fx = fluxo_caixa(calc["custo_restauracao_ha_p50"], calc["credito_liquido_tco2_ha_ano"], c)
    bloco = bloco_ficha({**linha, **calc}, r)
    bloco["cenario"] = {k: c[k] for k in ("cenario", "nome", *CENARIO_EDITAVEL) if k in c}
    bloco["fluxo_p50"] = {k: fx[k] for k in ("anos", "projeto_rs_ha", "com_financiamento_rs_ha")}
    return bloco


ORDENS = {
    "valor_desenvolvedor": "valor_desenvolvedor_rs",
    "vpl_ha": "vpl_rs_ha_p50",
    "tir_alavancada": "tir_alavancada_pct_p50",
    "credito": "credito_liquido_tco2_ano",
}
_INTEIROS = ("prazo_anos", "carencia_anos", "amortizacao_anos", "manutencao_desde_ano")
_LIMITES = {
    "preco_usd_t": (0.01, 1000), "prazo_anos": (1, 60), "fracao_financiada": (0, 1), "juros_ano": (0, 1),
    "carencia_anos": (0, 60), "amortizacao_anos": (1, 60), "taxa_desconto": (0, 1), "cambio_brl_usd": (0.01, 100),
    "manutencao_rs_ha_ano": (0, 1e5), "monitoramento_rs_ha_ano": (0, 1e5), "verificacao_rs_ha_entrega": (0, 1e5),
    "taxa_registro_usd_t": (0, 100), "tributos_receita": (0, 0.9), "arrendamento_rs_ha_ano": (0, 1e5),
}  # fmt: skip


def parametros_da_consulta(q: dict[str, str]) -> tuple[str | None, dict]:
    """Lê os parâmetros do simulador da URL (nome do cenário e os campos editáveis), com limites."""
    nome = q.pop("cenario", None) or None
    if nome is not None and nome not in regra()["cenarios"]["cenarios"]:
        raise ValueError(f"cenário desconhecido: {nome}")
    muda = {}
    for k, v in q.items():
        if k not in CENARIO_EDITAVEL:
            raise ValueError(f"parâmetro desconhecido: {k}")
        if k == "entregas_anos":
            try:
                muda[k] = [int(x) for x in str(v).replace(";", ",").split(",") if x.strip()]
            except ValueError as ex:
                raise ValueError("entregas_anos: anos separados por vírgula, como 7,12,17,22,25") from ex
            if not muda[k]:
                raise ValueError("entregas_anos: pelo menos um ano de entrega")
        elif k == "sistema_amortizacao":
            if v not in ("sac", "price"):
                raise ValueError("sistema_amortizacao: sac ou price")
            muda[k] = v
        else:
            try:
                x = float(str(v).replace(",", "."))
            except ValueError as ex:
                raise ValueError(f"{k}: número inválido ({v})") from ex
            lo, hi = _LIMITES[k]
            if not (lo <= x <= hi) or not math.isfinite(x):
                raise ValueError(f"{k}: fora do intervalo de {lo:g} a {hi:g}")
            muda[k] = int(x) if k in _INTEIROS else x
    return nome, muda


def cenarios_publicos(r: dict | None = None) -> dict:
    r = r or regra()
    out = {}
    for nome in r["cenarios"]["cenarios"]:
        c = cenario(nome, r)
        out[nome] = {"nome": c["nome"], "parametros": {k: c[k] for k in CENARIO_EDITAVEL if k in c},
                     "fontes": fontes_cenario(nome, r)}  # fmt: skip
    return {"padrao": r["cenarios"]["padrao"], "versao": versao(), "cenarios": out, "editaveis": list(CENARIO_EDITAVEL)}


def ordenar_filtrar(lista: list[dict], ordem: str | None = None, modo: str | None = None,
                    tir_min: float | None = None, so_lote_fecha: bool = False) -> list[dict]:  # fmt: skip
    """Ordena e filtra os imóveis do painel do município pelo valor para quem restaura (sem cortar ninguém quando
    nenhum parâmetro vem). Imóvel ainda sem o cálculo vai para o fim da ordem."""
    if ordem is not None and ordem not in ORDENS:
        raise ValueError(f"ordem desconhecida: {ordem} (use {', '.join(ORDENS)})")
    if modo is not None and modo not in regra()["modos"]:
        raise ValueError(f"modo desconhecido: {modo}")
    out = lista
    if modo is not None:
        out = [x for x in out if x.get("modo_restauracao") == modo]
    if tir_min is not None:
        out = [x for x in out if (_num(x, "tir_alavancada_pct_p50") or -1e9) >= tir_min]
    if so_lote_fecha:
        out = [x for x in out if _verdade(x.get("grupo_fecha_contrato"))]
    if ordem is not None:
        col = ORDENS[ordem]
        out = sorted(out, key=lambda x: (_num(x, col) is None, -(_num(x, col) or 0.0)))
    return out


def lotes(lista: list[dict]) -> list[dict]:
    """Um item por lote (grupo_id), do que mais crédito fecha ao que menos, sem nome nem CPF."""
    por: dict[str, dict] = {}
    for x in lista:
        g = x.get("grupo_id")
        if not isinstance(g, str) or not g:
            continue
        d = por.setdefault(g, {"grupo_id": g, "imoveis": [], "ha": _num(x, "grupo_ha"),
                               "credito_tco2_ano": _num(x, "grupo_credito_tco2_ano"),
                               "creditos_no_prazo": _num(x, "grupo_creditos_prazo"),
                               "fecha_contrato": _verdade(x.get("grupo_fecha_contrato")),
                               "ha_para_contrato": _num(x, "grupo_ha_para_contrato"), "modos_ha": {}})  # fmt: skip
        d["imoveis"].append(x.get("cod_imovel"))
        for md in regra()["modos"]:
            d["modos_ha"][md] = round(d["modos_ha"].get(md, 0.0) + (_num(x, f"restauracao_{md}_ha") or 0.0), 2)
    out = list(por.values())
    for d in out:
        d["n_imoveis"] = len(d["imoveis"])
    return sorted(out, key=lambda d: -(d["credito_tco2_ano"] or 0.0))
