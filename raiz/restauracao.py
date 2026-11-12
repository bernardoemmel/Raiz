"""Valor de cada fazenda para quem restaura com crédito de carbono (o desenvolvedor), por imóvel.

Calculado pelo produto, fora do motor (motor/ não se edita): lê as colunas do motor pelo nome e as entradas
geográficas de raiz/restauracao_geo.py, aplica as premissas e o cenário de um só arquivo,
raiz/regras/padroes/restauracao.yaml (rodada 11 unificada), e grava desenvolvedor_<mun>.csv (docs/colunas.md).

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
ARQ_CALIBRACAO = PADROES / "restauracao_calibracao.yaml"
ARQ_CAMBIO = PADROES / "restauracao_cambio.yaml"
C2CO2 = 44 / 12
RAIZ = 0.24  # raízes / parte aérea, igual ao motor
Z90 = 1.2815515655446004
Q = ("p10", "p50", "p90")
FAIXAS = ("d0", "d1", "d2", "d3")  # até 100 m, 100 a 300 m, 300 m a 1 km, acima de 1 km (limites no YAML)


# --- regra, cenário e versão ---------------------------------------------------------------------------------------


@lru_cache
def _ler(regra: Path, calibracao: Path, cambio: Path | None = None, _marcas: tuple = ()) -> dict:
    """Um só arquivo de premissas (restauracao.yaml, com os cenários); a calibração e a PTAX gravada são dados que o
    produto escreve e entram na versão."""
    textos = [regra.read_bytes()]
    r = yaml.safe_load(textos[0])
    r["cenarios"] = {"padrao": r.pop("padrao"), "cenarios": r["cenarios"], "monte_carlo": r.pop("monte_carlo")}
    r["calibracao"], r["cambio"] = {}, {}
    if calibracao.exists():
        textos.append(calibracao.read_bytes())
        r["calibracao"] = yaml.safe_load(textos[-1]) or {}
    if cambio is not None and cambio.exists():  # PTAX gravada por `raiz restauracao cambio --gravar`
        textos.append(cambio.read_bytes())
        r["cambio"] = yaml.safe_load(textos[-1]) or {}
    h = hashlib.sha256(b"\n--\n".join(textos)).hexdigest()[:8]
    r["versao_completa"] = f"{r['versao']}+{h}"
    return r


def _marca(p: Path) -> tuple:
    try:
        st = p.stat()
    except FileNotFoundError:
        return (str(p), None)
    return (str(p), st.st_mtime_ns, st.st_size)


def regra(regra: Path | None = None, calibracao: Path | None = None, cambio: Path | None = None) -> dict:
    """As premissas (restauracao.yaml, um arquivo só, com os cenários), a calibração e a PTAX gravada, com
    versao_completa = versão + hash dos arquivos. Relê quando um deles muda (a recalibração grava com a API de pé)."""
    arqs = (Path(regra or ARQ_REGRA), Path(calibracao or ARQ_CALIBRACAO), Path(cambio or ARQ_CAMBIO))
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
        if k not in c and k not in PADRAO_CENARIO:
            raise ValueError(f"parâmetro desconhecido no cenário: {k}")
        c[k] = v
    if muda.get("cambio_brl_usd") is not None:  # câmbio digitado no simulador vale mais que a PTAX gravada
        c["cambio_ptax"] = False
    return _normalizar(c, r)


PADRAO_CENARIO = {  # o que um cenário antigo (sem a rodada 11) não traz
    "modelo": "constante", "tabela_custo": "faixa_mercado", "horizonte_anos": None, "marcos_pct": None,
    "tolerancia_marco": 0.25, "multa_credito_dia_rs": 0.0, "multa_carencia_dias": 180, "multa_marco_dia_rs": 0.0,
    "rescisao_multa_fracao": 0.20, "volume_contratado": None, "preco_pos_contrato_usd_t": 0.0,
    "entregas_pos_contrato_anos": [], "fracao_financiada_minima": 0.0, "icsd_minimo": 1.3,
    "manutencao_usd_ha_ano": 0.0, "registro_venda_receita": 0.0, "pagamento_dono": "arrendamento",
    "participacao_dono": 0.0, "piso_dono_rs_ha_ano": 0.0, "fase1_rs_ha_ano": 0.0, "fase1_anos": 0,
    "linha_base_piso": 0.0, "vazamento": 0.0, "vazamento_com_mitigacao": 0.0, "reserva_risco": 0.20,
    "incerteza": 0.10, "cambio_ptax": False, "juros_carencia": "pagos", "arrendamento_rs_ha_ano": 0.0,
    "tolerancia_ultimo_marco": None, "rescisao_atraso_marco_dias": None, "multas_no_fluxo": True,
    "reserva_por_fazenda": False,
    "desembolso_custo": [1.0],
}  # fmt: skip


def _normalizar(c: dict, r: dict) -> dict:
    """Completa e confere o cenário: anos de entrega dentro do prazo, cada um com o seu marco (% acumulado do volume
    contratado), vendas depois do contrato dentro do horizonte e o câmbio da PTAX quando o cenário pede."""
    for k, v in PADRAO_CENARIO.items():
        if c.get(k) is None and v is not None:
            c[k] = copy.deepcopy(v)
        c.setdefault(k, v)
    c["reserva_risco"] = max(float(c["reserva_risco"]), float(r["nao_permanencia"].get("piso", 0.20)), 0.20)
    T = int(c["prazo_anos"])
    c["horizonte_anos"] = max(int(c.get("horizonte_anos") or T), T)
    H = c["horizonte_anos"]
    entregas = [int(a) for a in c["entregas_anos"]]
    marcos = c.get("marcos_pct")
    if marcos is None:  # sem marcos: a entrega leva o acumulado e o último marco é 100%
        marcos = [100.0 * a / max(entregas) for a in entregas] if entregas else []
    if len(marcos) != len(entregas):
        raise ValueError("marcos_pct precisa ter um valor por ano de entrega (entregas_anos)")
    pares = sorted((a, float(m)) for a, m in zip(entregas, marcos, strict=True) if 0 < a <= T)
    c["entregas_anos"] = [a for a, _ in pares]
    c["marcos_pct"] = [m for _, m in pares]
    c["entregas_pos_contrato_anos"] = sorted(int(a) for a in c["entregas_pos_contrato_anos"] if T < int(a) <= H)
    c["desembolso_custo"] = [float(x) for x in c["desembolso_custo"]]
    if c.get("cambio_ptax") and (r.get("cambio") or {}).get("ptax"):
        c["cambio_brl_usd"] = float(r["cambio"]["ptax"])
        c["cambio_data"] = r["cambio"].get("data")
    return c


def fontes_cenario(nome: str | None = None, r: dict | None = None) -> dict[str, str]:
    r = r or regra()
    cs = r["cenarios"]["cenarios"]
    nome = nome or r["cenarios"]["padrao"]
    bruto = dict(cs[cs[nome]["herda"]]) if "herda" in cs[nome] else {}
    bruto.update(cs[nome])
    return {k: v["fonte"] for k, v in bruto.items() if isinstance(v, dict) and "fonte" in v}


PTAX_URL = (
    "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
    "CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
)


def ptax(hoje=None, cliente=None) -> dict:
    """PTAX de venda do dólar mais recente no Banco Central (últimos 15 dias), com a data da cotação."""
    import datetime as dt

    import httpx

    hoje = hoje or dt.date.today()
    ini = hoje - dt.timedelta(days=15)
    params = {
        "@dataInicial": f"'{ini:%m-%d-%Y}'",
        "@dataFinalCotacao": f"'{hoje:%m-%d-%Y}'",
        "$format": "json",
        "$select": "cotacaoVenda,dataHoraCotacao",
    }
    cli = cliente or httpx.Client(timeout=30, headers={"User-Agent": "Mozilla/5.0 (raiz)"})
    resp = cli.get(PTAX_URL, params=params)
    resp.raise_for_status()
    valores = resp.json().get("value") or []
    if not valores:
        raise ValueError("o Banco Central não devolveu cotação nos últimos 15 dias")
    ult = max(valores, key=lambda v: v["dataHoraCotacao"])
    return {"ptax": round(float(ult["cotacaoVenda"]), 4), "data": ult["dataHoraCotacao"][:10],
            "fonte": "Banco Central do Brasil, PTAX de venda (olinda.bcb.gov.br)"}  # fmt: skip


def gravar_cambio(c: dict, arquivo: Path | None = None) -> Path:
    """Grava a PTAX em restauracao_cambio.yaml: entra na versão das premissas e o recalcular refaz os municípios."""
    arquivo = Path(arquivo or ARQ_CAMBIO)
    txt = (
        "# PTAX gravada por `raiz restauracao cambio --gravar`. Os cenários com cambio_ptax usam este valor no lugar\n"
        "# do câmbio fixo; mudar este arquivo muda a versão das premissas e o recalcular refaz os municípios.\n"
        + yaml.safe_dump(c, allow_unicode=True, sort_keys=False)
    )
    arquivo.write_text(txt, encoding="utf-8")
    return arquivo


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


def custo(linha: dict, m: dict | None = None, r: dict | None = None, c: dict | None = None) -> dict:
    """R$/ha P10/P50/P90 (soma dos anos) e o P50 ano a ano, média dos modos pela área de cada um, vezes os ajustes.
    Tabela do SFB (cenário central): implantação no ano 0 e manutenção inicial nos anos seguintes. Faixa de mercado
    (cenário otimista): o custo sai no ano 0 (desembolso_custo do cenário)."""
    r = r or regra()
    c = c or cenario(r=r)
    m = m or modos(linha, r)
    f, det = fator_custo(linha, r)
    w = _pesos(m)
    if c.get("tabela_custo") == "sfb_bom_futuro":
        t = r["custo_sfb_rs_ha"]
        vec = np.zeros(1 + max(len(t[md]["manutencao_inicial"]) for md in w))
        p10 = p90 = 0.0
        for md, wi in w.items():
            v = np.array([t[md]["implantacao"], *t[md]["manutencao_inicial"]], dtype=float) * _cal(r, "custo", md)
            vec[: len(v)] += wi * v
            p10 += wi * float(t[md]["p10"]) * _cal(r, "custo", md)
            p90 += wi * float(t[md]["p90"]) * _cal(r, "custo", md)
        vec *= f
        out = {"p10": p10 * f, "p50": float(vec.sum()), "p90": p90 * f}
    else:
        out = {q: sum(w[md] * r["custo_rs_ha"][md][q] * _cal(r, "custo", md) for md in w) * f for q in Q}
        vec = out["p50"] * np.array(c["desembolso_custo"], dtype=float)
    return {**out, "por_ano_p50": vec, "fator": f, "ajustes": det}


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


def forma_curva(r: dict | None = None) -> np.ndarray:
    """Forma da curva de captura (fração do total em cada ano, anos 0..N, soma 1): linear entre os pontos da curva
    anual oficial da URTX (Anexo 20 da concessão), escalada depois para o total de 40 anos de cada método."""
    r = r or regra()
    cc = r["captura_curva"]
    n_anos = int(cc["anos"])
    pts = sorted((int(a), float(v)) for a, v in cc["pontos"])
    v = np.zeros(n_anos + 1)
    for (a0, v0), (a1, v1) in zip(pts, pts[1:], strict=False):
        for t in range(a0 + 1, a1 + 1):
            v[t] = v0 + (v1 - v0) * (t - a0) / (a1 - a0)
    ap, vp = pts[-1]
    if ap < n_anos:  # sem ponto no último ano: fica no último valor
        v[ap + 1 :] = vp
    return v / v.sum()


def _com_teto(anual: np.ndarray, teto: float) -> np.ndarray:
    """O estoque acumulado não passa do teto do bioma: o que passaria some dos últimos anos."""
    return np.diff(np.minimum(np.cumsum(anual, axis=-1), teto), axis=-1, prepend=0.0)


def captura(linha: dict, m: dict | None = None, r: dict | None = None, c: dict | None = None) -> dict:
    """Captura bruta. p10/p50/p90 = média por ano no horizonte do cenário (tCO2/ha/ano); bruto_ano = P50 ano a ano
    (anos 0..horizonte, sem o teto, que o fluxo aplica depois de sortear); rel10/rel90 = faixa em relação ao P50."""
    r = r or regra()
    c = c or cenario(r=r)
    m = m or modos(linha, r)
    f, det = fator_captura(linha, r)
    w = _pesos(m)
    pm = captura_por_modo(linha, r)
    H = int(c["horizonte_anos"])
    b = _bioma(linha, r)
    bruto = np.zeros(H + 1)
    if c.get("modelo") == "curva":
        cc = r["captura_curva"]
        forma = forma_curva(r)
        k = min(H, len(forma) - 1)
        total = sum(w[md] * cc["total_tco2_ha"][md] * _cal(r, "captura", md) for md in w) * f
        teto = float(cc["teto_tco2_ha"].get(b, cc["teto_tco2_ha"]["Amazônia"]))
        total = min(total, teto)  # vale o menor entre o total do método e o teto do bioma (a forma fica)
        bruto[: k + 1] = total * forma[: k + 1]
        rel10, rel90 = float(cc["incerteza_captura"]["p10"]), float(cc["incerteza_captura"]["p90"])
    else:
        p = {q: sum(w[md] * pm[md][q] * _cal(r, "captura", md) for md in w) * f for q in Q}
        bruto[1:] = p["p50"]
        rel10 = p["p10"] / p["p50"] if p["p50"] > 0 else 1.0
        rel90 = p["p90"] / p["p50"] if p["p50"] > 0 else 1.0
        teto = math.inf
    out = {q: float(_com_teto(bruto * x, teto).sum()) / H for q, x in (("p10", rel10), ("p50", 1.0), ("p90", rel90))}
    return {**out, "total_p50": out["p50"] * H, "bruto_ano": bruto, "rel10": rel10, "rel90": rel90, "teto": teto,
            "modelo": c.get("modelo") or "constante", "fator": f, "ajustes": det, "por_modo": pm}  # fmt: skip


def _texto_reserva(linha: dict, c: dict) -> str:
    """Explica a reserva de não permanência da fazenda (ou diz que é a do cenário)."""
    piso = max(float(c["reserva_risco"]), 0.20)
    if str(linha.get("reserva_risco_fonte")) != "fazenda":
        return f"Reserva mínima ({100 * piso:.0f}%): falta o histórico de fogo e de derrubada; piso Raíz de 20%."
    fogo, der, perda = (_num(linha, k) for k in ("fogo_risco_ano_pct", "derrubada_risco_ano_pct",
                                                 "perda_natural_40a_pct"))  # fmt: skip
    partes = []
    if fogo is not None:
        partes.append(f"fogo em {fogo:.1f}% da área por ano (MapBiomas Fogo, 1985 a 2024)")
    if der is not None:
        partes.append(f"derrubada de {der:.1f}% da vegetação secundária do município por ano (MapBiomas)")
    txt = "; ".join(partes)
    if perda is not None:
        txt += (
            f". Perda esperada em 40 anos, com aceiro, brigada e contrato averbado: {perda:.1f}%. A reserva "
            f"nunca fica abaixo dos {100 * piso:.0f}% (cenário e piso Raíz de 20%)."
        )
    return txt[:1].upper() + txt[1:]


def _r(x: float | None, mult: float = 1.0, nd: int = 2) -> float | None:
    return None if x is None else round(float(x) * mult, nd)


def nao_permanencia(linha: dict, c: dict, r: dict | None = None) -> dict:
    """Reserva de não permanência da fazenda (E3 passo 4): frequência vezes severidade do fogo (MapBiomas Fogo) e da
    derrubada da vegetação secundária no município (MapBiomas desmatamento), menos a mitigação do projeto, somadas ao
    risco interno e externo; nunca abaixo de 20% (política Raíz) nem da reserva do cenário. Sem dado, mantém o piso."""
    r = r or regra()
    npm = r["nao_permanencia"]
    base = max(float(c["reserva_risco"]), float(npm.get("piso", 0.20)), 0.20)
    out = {"reserva": base, "fonte": "cenario", "fogo_ano": None, "derrubada_ano": None, "perda_40a": None}
    if not c.get("reserva_por_fazenda"):
        return out
    fogo, sup = _num(linha, "fogo_anos_media"), _num(linha, "taxa_supressao_secundaria_municipio")
    if fogo is None and sup is None:
        return out
    lf = max(fogo or 0.0, 0.0) / float(npm["anos_serie_fogo"])
    ld = max(sup or 0.0, 0.0)
    taxa = lf * float(npm["severidade_fogo"]) * (1 - float(npm["mitigacao_fogo"]))
    taxa += ld * float(npm["severidade_derrubada"]) * (1 - float(npm["mitigacao_derrubada"]))
    perda = 1 - math.exp(-taxa * float(npm["horizonte_anos"]))
    risco = float(npm["risco_interno_externo"]) + perda
    res = max(base, min(max(risco, float(npm["piso_vcs"])), float(npm["teto"])))
    return {"reserva": res, "fonte": "fazenda", "fogo_ano": lf, "derrubada_ano": ld, "perda_40a": perda}


def descontos(linha: dict, cap: dict, lb: dict, c: dict, r: dict | None = None) -> dict:
    """Do bruto ao líquido, nesta ordem: linha de base (a medida no YbYrá, nunca abaixo do piso do cenário),
    vazamento (VMD0054; o do cenário, ou zero com fazenda vizinha de mitigação no lote), reserva de não permanência
    (a da fazenda pelo fogo e pela derrubada, nunca abaixo da do cenário) e incerteza."""
    medida = lb["tco2_ha_ano"] / cap["p50"] if cap["p50"] > 0 else 0.0
    base = min(max(medida, float(c.get("linha_base_piso") or 0.0)), 1.0)
    mitig = _verdade(linha.get("vazamento_mitigacao")) or _verdade(linha.get("mitigacao_vizinha"))
    vaz = float(c["vazamento_com_mitigacao"] if mitig else c["vazamento"])
    npm = nao_permanencia(linha, c, r)
    res, inc = npm["reserva"], float(c["incerteza"])
    return {
        "nao_permanencia": npm,
        "linha_base": base,
        "linha_base_medida": medida,
        "vazamento": vaz,
        "vazamento_mitigacao": mitig,
        "reserva_risco": res,
        "incerteza": inc,
        "fator": (1 - base) * (1 - vaz) * (1 - res) * (1 - inc),
    }


def liquido(captura_t: float, fator: float) -> float:
    return max(captura_t, 0.0) * fator


# --- fluxo de caixa por hectare ----------------------------------------------------------------------------------


_GRADE_TIR = np.concatenate([np.arange(-0.95, 0.0, 0.05), np.arange(0.0, 0.5, 0.01), np.arange(0.5, 3.01, 0.1)])


@lru_cache
def _desconto_grade(T: int) -> np.ndarray:
    return (1 + _GRADE_TIR[:, None]) ** -np.arange(T, dtype=float)[None, :]


def _tir(F: np.ndarray) -> np.ndarray:
    """TIR vetorizada nas linhas de F (fluxo por ano nas colunas): a maior taxa em que o VPL passa de positivo para
    negativo numa grade de -95% a 300%, refinada por bisseção. NaN se o VPL não cruza o zero (perde tudo)."""
    F = np.atleast_2d(np.asarray(F, dtype=float))
    T = F.shape[1]
    g = _GRADE_TIR
    V = F @ _desconto_grade(T).T
    cruza = (V[:, :-1] > 0) & (V[:, 1:] <= 0)
    ok = cruza.any(axis=1)
    i = np.where(ok, cruza.shape[1] - 1 - np.argmax(cruza[:, ::-1], axis=1), 0)
    lo, hi = g[i].astype(float), g[i + 1].astype(float)
    rows = np.arange(len(F))
    vlo, vhi = V[rows, i], V[rows, np.minimum(i + 1, len(g) - 1)]
    t = np.arange(T, dtype=float)
    # falsa posição (Illinois) dentro do intervalo da grade: converge em poucas rodadas, com a mesma garantia de
    # ficar entre lo e hi da bisseção
    lado = np.zeros(len(F))
    for _ in range(8):
        den = np.where(ok, vlo - vhi, 1.0)
        mid = np.where(np.abs(den) > 1e-12, lo + (hi - lo) * vlo / np.where(np.abs(den) > 1e-12, den, 1.0),
                       (lo + hi) / 2)  # fmt: skip
        mid = np.clip(mid, lo, hi)
        vm = (F * (1 + mid[:, None]) ** -t[None, :]).sum(axis=1)
        pos = vm > 0
        lo, vlo = np.where(pos, mid, lo), np.where(pos, vm, vlo)
        hi, vhi = np.where(pos, hi, mid), np.where(pos, vhi, vm)
        # Illinois: o lado que não andou tem o valor cortado pela metade
        vhi = np.where(pos & (lado > 0), vhi / 2, vhi)
        vlo = np.where(~pos & (lado < 0), vlo / 2, vlo)
        lado = np.where(pos, 1.0, -1.0)
    return np.where(ok, np.where(np.abs(vlo) < np.abs(vhi), lo, hi), np.nan)


def divida(c: dict, capex: np.ndarray, caixa: np.ndarray) -> dict:
    """Financiamento por ha: entradas (fração de cada desembolso de implantação), juros pagos na carência e as
    parcelas. sac/price: fração fixa do cenário. icsd: parcelas esculpidas no caixa do P50 (caixa do ano / ICSD
    mínimo) e dívida = menor entre o teto da fração e o que o ICSD permite (o banco dimensiona no caso base)."""
    H = len(capex) - 1
    j, car, amo = float(c["juros_ano"]), int(c["carencia_anos"]), int(c["amortizacao_anos"])
    sist = c["sistema_amortizacao"]
    total = float(capex.sum())
    fim = min(car + amo, H)
    t = np.arange(H + 1)
    info = {"fracao": float(c["fracao_financiada"]), "fracao_icsd": None, "limitada_icsd": False}
    serv = np.zeros(H + 1)
    if sist == "icsd":
        janela = (t > car) & (t <= fim)
        serv_max = np.where(janela, np.maximum(caixa, 0.0) / float(c["icsd_minimo"]), 0.0)
        capacidade = float((serv_max * (1 + j) ** -(t - car).astype(float)).sum())
        if c.get("juros_carencia") == "capitalizados":  # o saldo no fim da carência cresce com os juros
            capacidade /= float((capex / total * (1 + j) ** np.clip(car - t, 0, None)).sum()) if total > 0 else 1.0
        fr_icsd = capacidade / total if total > 0 else 0.0
        fr = min(float(c["fracao_financiada"]), fr_icsd)
        serv = serv_max * (fr / fr_icsd if fr_icsd > 0 else 0.0)
        info.update(fracao=fr, fracao_icsd=fr_icsd, limitada_icsd=fr_icsd < float(c["fracao_financiada"]))
    fr = info["fracao"]
    D = np.zeros(H + 1)
    saldo, L = 0.0, 0.0
    capitaliza = c.get("juros_carencia") == "capitalizados"
    for a in range(H + 1):
        juros = saldo * j
        if 1 <= a <= car:
            if capitaliza:
                saldo += juros
            else:
                D[a] -= juros
        elif car < a <= fim and saldo > 1e-9:
            if sist == "icsd":
                pag = min(serv[a], saldo + juros)
                D[a] -= pag
                saldo = saldo + juros - pag
            elif sist == "price":
                n = fim - a + 1
                pmt = saldo * j / (1 - (1 + j) ** -n) if j > 0 else saldo / n
                D[a] -= pmt
                saldo -= pmt - juros
            else:  # sac
                if a == car + 1:
                    L = saldo
                amort = min(L / amo, saldo)
                D[a] -= amort + juros
                saldo -= amort
        D[a] += fr * capex[a]
        saldo += fr * capex[a]
    if saldo > 1e-9:  # o que sobrar é quitado no último ano da dívida
        D[fim] -= saldo
    info["valor_rs_ha"] = fr * total
    info["abaixo_minimo"] = fr < float(c.get("fracao_financiada_minima") or 0.0) - 1e-9
    return {"D": D, **info}


def simular_fluxos(custo_ano, m_custo, bruto_ano, m_captura, teto: float, fator_liq: float, c: dict,
                   r: dict | None = None, tirs: tuple[str, ...] = ("projeto", "alavancada")) -> dict:  # fmt: skip
    """Fluxo por ha em cada sorteio (linhas) e ano (colunas, 0..horizonte). A linha 0 é o caminho do P50 (custo e
    captura no P50): o volume contratado e a dívida saem dela, como o comprador e o banco fariam."""
    r = r or regra()
    H, T = int(c["horizonte_anos"]), int(c["prazo_anos"])
    fx = float(c["cambio_brl_usd"])
    mc = np.concatenate([[1.0], np.asarray(m_custo, dtype=float).ravel()])
    mk = np.concatenate([[1.0], np.asarray(m_captura, dtype=float).ravel()])
    n = len(mc)
    anos = np.arange(H + 1)
    cv = np.zeros(H + 1)
    cv[: min(len(custo_ano), H + 1)] = np.asarray(custo_ano, dtype=float)[: H + 1]
    K = mc[:, None] * cv[None, :]
    bv = np.zeros(H + 1)
    bv[: min(len(bruto_ano), H + 1)] = np.asarray(bruto_ano, dtype=float)[: H + 1]
    G = _com_teto(mk[:, None] * bv[None, :], teto)
    N = np.cumsum(G * fator_liq, axis=1)  # crédito líquido acumulado no fim de cada ano

    # entregas do contrato, marcos e multas
    preco, preco_pos = float(c["preco_usd_t"]) * fx, float(c["preco_pos_contrato_usd_t"]) * fx
    vol = c.get("volume_contratado")
    V = float(vol) * float(N[0, T]) if vol is not None else math.inf
    receita, vendidos, multas = (np.zeros((n, H + 1)) for _ in range(3))
    entregue, multa_acum = np.zeros(n), np.zeros(n)
    resc = np.zeros(n, dtype=bool)
    marcos, pcts = c["entregas_anos"], c["marcos_pct"]
    atende = np.ones((n, len(marcos)), dtype=bool)
    atraso_dias = np.zeros((n, len(marcos)))
    finito = math.isfinite(V) and V > 0
    teto_multa = float(c["rescisao_multa_fracao"]) * V * preco if finito else math.inf
    peso = V / float(r["agrupamento"]["contrato_creditos"]) if finito else 0.0
    multa_ativa = finito and (float(c["multa_credito_dia_rs"]) > 0 or float(c["multa_marco_dia_rs"]) > 0)
    dias_mes = 365.0 / 12
    # multa e rescisão no fluxo da fazenda só quando ela fecha o contrato sozinha; no lote, a reserva cobre a falta de
    # uma fazenda e a multa se mede no lote inteiro (cronograma_lote); a chance de cada marco é calculada igual
    no_fluxo = bool(c.get("multas_no_fluxo", True))
    teto_entrega = V if no_fluxo else math.inf
    for i, (e, pct) in enumerate(zip(marcos, pcts, strict=True)):
        d = np.maximum(np.minimum(N[:, e], teto_entrega) - entregue, 0.0)
        receita[:, e] += d * np.where(resc & no_fluxo, preco_pos, preco)
        vendidos[:, e] += d
        entregue += d
        if not finito:
            continue
        ultimo = i == len(marcos) - 1
        tol = float(c.get("tolerancia_ultimo_marco") or 0.0) if ultimo else float(c["tolerancia_marco"])
        precisa = (1 - tol) * float(pct) / 100 * V
        falta = N[:, e] < precisa - 1e-9
        atende[:, i] = ~falta & ~resc
        meses = (H - e) * 12
        if not falta.any() or meses <= 0:
            continue
        tm = e + np.arange(1, meses + 1) / 12  # crédito mês a mês depois do marco, linear dentro do ano
        y0 = np.minimum(np.floor(tm).astype(int), H)
        y1 = np.minimum(y0 + 1, H)
        Nm = N[:, y0] + (tm - y0)[None, :] * (N[:, y1] - N[:, y0])
        S = np.where(falta[:, None], np.maximum(precisa - Nm, 0.0), 0.0)
        dias = (S > 1e-9).sum(axis=1) * dias_mes
        atraso_dias[:, i] = dias
        if not multa_ativa:
            continue
        depois = (tm - e) > float(c["multa_carencia_dias"]) / 365
        mt = float(c["multa_credito_dia_rs"]) * S[:, depois].sum(axis=1) * dias_mes
        mt += float(c["multa_marco_dia_rs"]) * peso * dias
        mt = np.where(resc, 0.0, mt)
        bate = multa_acum + mt >= teto_multa
        mt = np.where(bate & ~resc, np.maximum(teto_multa - multa_acum, 0.0), mt)
        limite_dias = c.get("rescisao_atraso_marco_dias")
        if limite_dias is not None:  # marco atrasado demais também rescinde
            bate |= dias > float(limite_dias)
        resc |= bate
        multa_acum += mt
        paga = np.minimum(np.ceil(e + dias / 365).astype(int), H)
        np.add.at(multas, (np.arange(n), paga), mt)
    multas_fluxo = multas if no_fluxo else np.zeros_like(multas)
    # depois do contrato: o que sobrou e o que a mata segue capturando, vendido ao preço de mercado
    for e in c["entregas_pos_contrato_anos"]:
        d = np.maximum(N[:, e] - vendidos.sum(axis=1), 0.0)
        receita[:, e] += d * preco_pos
        vendidos[:, e] += d

    # pagamento ao dono, custos de operação e o que sai da receita
    um = anos >= 1
    modo = c["pagamento_dono"]
    if modo == "arrendamento":
        dono = np.broadcast_to(np.where(um, float(c["arrendamento_rs_ha_ano"]), 0.0), (n, H + 1)).copy()
    else:
        piso = np.where(um, float(c["piso_dono_rs_ha_ano"]), 0.0)
        part = float(c["participacao_dono"]) * receita
        if modo == "duas_fases":
            f1 = int(c["fase1_anos"])
            piso = np.where(um & (anos <= f1), float(c["fase1_rs_ha_ano"]), piso)
            part[:, anos <= f1] = 0.0
        dono = part + piso[None, :]
    op = np.zeros(H + 1)
    op[1:] += float(c["monitoramento_rs_ha_ano"])
    op[anos >= int(c["manutencao_desde_ano"])] += float(c["manutencao_rs_ha_ano"]) + float(
        c["manutencao_usd_ha_ano"]) * fx  # fmt: skip
    op[0] = 0.0
    for e in (*marcos, *c["entregas_pos_contrato_anos"]):
        op[e] += float(c["verificacao_rs_ha_entrega"])
    prop = receita * (float(c["tributos_receita"]) + float(c["registro_venda_receita"]))
    prop += vendidos * float(c["taxa_registro_usd_t"]) * fx
    F = -K + receita - prop - dono - op[None, :] - multas_fluxo

    div = divida(c, K[0], F[0] + K[0])
    L = F + mc[:, None] * div["D"][None, :]
    desc = (1 + float(c["taxa_desconto"])) ** -anos.astype(float)
    return {
        "anos": anos, "F": F, "L": L, "N": N, "G": G, "K": K, "receita": receita, "vendidos": vendidos,
        "dono": dono, "multas": multas, "multas_fluxo": multas_fluxo, "op": op, "divida": div, "V": V,
        "atende": atende, "atraso_dias": atraso_dias,
        "rescindido": resc, "vpl": F @ desc,
        "tir_projeto": _tir(F) if "projeto" in tirs else np.full(n, np.nan),
        "tir_alavancada": _tir(L) if "alavancada" in tirs else np.full(n, np.nan),
        "pico": np.maximum(-np.cumsum(L, axis=1).min(axis=1), 0.0), "desconto": desc,
    }  # fmt: skip


def fluxo_caixa(custo_rs_ha: float, credito_tco2_ha_ano: float, c: dict | None = None) -> dict:
    """Fluxo por ha de um caso simples (custo total no calendário de desembolso do cenário e crédito líquido igual
    todo ano até o fim do horizonte), ano a ano, e os indicadores (TIR em fração ao ano; None se não existir)."""
    c = c or cenario()
    H = int(c["horizonte_anos"])
    bruto = np.zeros(H + 1)
    bruto[1:] = credito_tco2_ha_ano
    s = simular_fluxos(custo_rs_ha * np.array(c["desembolso_custo"], dtype=float), [], bruto, [], math.inf, 1.0, c)

    def f(x):
        x = float(x[0])
        return None if math.isnan(x) else x

    return {
        "anos": [int(a) for a in s["anos"]],
        "projeto_rs_ha": [round(float(x), 2) for x in s["F"][0]],
        "com_financiamento_rs_ha": [round(float(x), 2) for x in s["L"][0]],
        "vpl_rs_ha": f(s["vpl"]),
        "tir_projeto": f(s["tir_projeto"]),
        "tir_alavancada": f(s["tir_alavancada"]),
        "pico_capital_proprio_rs_ha": f(s["pico"]),
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


def arrendamento_censo(linha: dict, c: dict, r: dict | None = None) -> tuple[float | None, str | None]:
    """Aluguel de referência por ha por ano (Censo Agro 2017): o do município, senão o do estado, senão o do Brasil."""
    r = r or regra()
    t = r.get("dono_aluguel_censo") or {}
    cod = _num(linha, "cod_municipio_ibge")
    muns = {int(k): float(v) for k, v in (t.get("por_municipio_rs_ha_ano") or {}).items()}
    if cod is not None and int(cod) in muns:
        return muns[int(cod)], "municipio"
    uf = str(linha.get("uf") or "").upper()
    if uf in (t.get("por_uf_rs_ha_ano") or {}):
        return float(t["por_uf_rs_ha_ano"][uf]), "uf"
    if t.get("brasil_rs_ha_ano") is not None:
        return float(t["brasil_rs_ha_ano"]), "brasil"
    return None, None


@lru_cache
def _pecuaria(arquivo: str) -> dict[int, tuple[float, float, float]]:
    import pandas as pd

    f = PADROES / arquivo
    if not f.exists():
        return {}
    t = pd.read_csv(f)
    return {int(x.cod_ibge): (float(x.pasto_ha), float(x.bovinos_cab), float(x.venda_bovinos_mil_rs))
            for x in t.itertuples()}  # fmt: skip


def renda_pecuaria(linha: dict, r: dict | None = None) -> dict | None:
    """Âncora de renda do gado no município (Censo Agro 2017, corrigida pelo IPCA): receita bruta da venda de gado por
    ha de pasto e lotação. Sem o município na tabela, None."""
    r = r or regra()
    pc = r.get("pecuaria") or {}
    cod = _num(linha, "cod_municipio_ibge")
    if cod is None or not pc.get("arquivo"):
        return None
    x = _pecuaria(pc["arquivo"]).get(int(cod))
    if not x or x[0] <= 0:
        return None
    pasto, cab, venda = x
    bruta = 1000 * venda / pasto * float(pc.get("ipca_fator") or 1.0)
    margem = float(pc.get("margem_liquida_referencia") or 0.0)
    return {"receita_bruta_rs_ha_ano": round(bruta, 0), "lotacao_cab_ha": round(cab / pasto, 2),
            "margem_referencia": margem, "sobra_referencia_rs_ha_ano": round(bruta * margem, 0),
            "ipca_ate": pc.get("ipca_ate")}  # fmt: skip


# --- cronograma do lote (ProFloresta+): chance de cada marco, multa e rescisão no lote inteiro -----------------


def cronograma_lote(credito_contrato_p50: float, c: dict | None = None, r: dict | None = None,
                    volume: float | None = None) -> dict:  # fmt: skip
    """Chance de cumprir cada marco, multa esperada e chance de rescisão de um lote com `credito_contrato_p50` créditos
    líquidos até o fim do contrato (P50), contra o volume contratado (padrão: o próprio P50). O erro da captura é um
    fator comum ao lote inteiro (não se cancela entre fazendas); a multa de R$ 1.000 por dia de marco é do contrato.
    Trazido da branch claude/premissas-rodada11 (cronograma do Anexo IV), com a curva e o cenário deste arquivo."""
    r = r or regra()
    c = c or cenario(r=r)
    volume = float(volume if volume is not None else credito_contrato_p50)
    T = int(c["prazo_anos"])
    forma = forma_curva(r)
    acum_ano = np.cumsum(forma)
    acum_ano = acum_ano / acum_ano[min(T, len(acum_ano) - 1)] * credito_contrato_p50
    passo = 1 / 12
    tempo = np.arange(0, len(forma) - 1 + passo / 2, passo)
    acum50 = np.interp(tempo, np.arange(len(forma)), acum_ano)
    cc = r["captura_curva"]["incerteza_captura"]
    mc_ = r["cenarios"]["monte_carlo"]
    _, zk = _sorteios(int(mc_["sorteios"]), int(mc_["semente"]))
    fk = _dois_lados(zk, float(cc["p10"]), 1.0, float(cc["p90"]))
    acum = fk[:, None] * acum50[None, :]
    preco_brl = float(c["preco_usd_t"]) * float(c["cambio_brl_usd"])
    valor = volume * preco_brl
    marcos = []
    multas = np.zeros(len(fk))
    atraso_max = np.zeros(len(fk))
    cumpre_todos = np.ones(len(fk), dtype=bool)
    for i, (ano, pct) in enumerate(zip(c["entregas_anos"], c["marcos_pct"], strict=True)):
        ultimo = i == len(c["entregas_anos"]) - 1
        tol = float(c.get("tolerancia_ultimo_marco") or 0.0) if ultimo else float(c["tolerancia_marco"])
        alvo = volume * float(pct) / 100
        limiar = alvo * (1 - tol)
        im = int(round(ano / passo))
        cumpre = acum[:, im] >= limiar - 1e-9
        depois = acum[:, im:]
        chegou = depois >= limiar - 1e-9
        meses = np.where(chegou.any(axis=1), np.argmax(chegou, axis=1), depois.shape[1])
        dias = meses * passo * 365
        falta = np.maximum(alvo - depois, 0.0)
        dia_mes = np.arange(depois.shape[1]) * passo * 365
        conta = (dia_mes[None, :] > float(c["multa_carencia_dias"])) & (
            np.arange(depois.shape[1])[None, :] < meses[:, None]
        )
        m_cred = (falta * conta).sum(axis=1) * float(c["multa_credito_dia_rs"]) * passo * 365
        m_marco = dias * float(c["multa_marco_dia_rs"])
        mt = np.where(cumpre, 0.0, m_cred + m_marco)
        multas += mt
        atraso_max = np.maximum(atraso_max, np.where(cumpre, 0.0, dias))
        cumpre_todos &= cumpre
        marcos.append({"ano": int(ano), "fracao": float(pct) / 100, "acumulado_exigido": alvo, "limiar": limiar,
                       "acumulado_p50": float(acum50[im]), "chance": float(cumpre.mean()),
                       "multa_esperada_rs": float(mt.mean()),
                       "atraso_medio_dias_se_falhar": float(dias[~cumpre].mean()) if (~cumpre).any() else 0.0,
                       })  # fmt: skip
    limite = c.get("rescisao_atraso_marco_dias")
    resc = multas >= float(c["rescisao_multa_fracao"]) * valor
    if limite is not None:
        resc |= atraso_max > float(limite)
    return {"marcos": marcos, "chance_todos": float(cumpre_todos.mean()), "multa_esperada_rs": float(multas.mean()),
            "chance_rescisao": float(resc.mean()), "valor_contrato_rs": valor, "volume": volume,
            "credito_contrato_p50": credito_contrato_p50}  # fmt: skip


def faixa_lote(p10, p50, p90, r: dict | None = None, fracao_comum: float | None = None) -> dict:
    """P10/P50/P90 de uma soma de fazendas, lado a lado (Portaria MME 102/2016 e PRMS):
    - soma: os P10 e os P90 somados, como se todas errassem juntas (o erro da captura comum ao lote inteiro);
    - carteira: um fator de Vasicek: parte `fracao_comum` da variância do erro de cada fazenda é comum a todas e o
      resto é dela. O fator comum sai de uma sequência de Sobol embaralhada; a parte de cada fazenda, de sorteios
      próprios. Cada fazenda numa normal de dois lados que respeita os seus P10, P50 e P90.
    Devolve também a incerteza padrão da carteira e a razão P90/P50 (os campos que a Portaria MME 102 pede)."""
    from scipy.stats import norm, qmc

    r = r or regra()
    cp = r["carteira"]
    f = float(cp["fracao_comum"] if fracao_comum is None else fracao_comum)
    p10, p50, p90 = (np.asarray(x, dtype=float).ravel() for x in (p10, p50, p90))
    ok = np.isfinite(p50) & (p50 > 0)
    p10, p50, p90 = np.where(np.isfinite(p10[ok]), p10[ok], p50[ok]), p50[ok], np.where(np.isfinite(p90[ok]),
                                                                                       p90[ok], p50[ok])  # fmt: skip
    if not len(p50):
        vazio = {"p10": 0.0, "p50": 0.0, "p90": 0.0}
        return {"soma": vazio, "carteira": dict(vazio), "incerteza_padrao": 0.0, "fracao_comum": f, "fazendas": 0}
    lo, hi = np.maximum(p50 - p10, 0) / Z90, np.maximum(p90 - p50, 0) / Z90
    m = int(cp["sorteios_log2"])
    zc = norm.ppf(np.clip(qmc.Sobol(1, scramble=True, seed=int(cp["semente"])).random_base2(m)[:, 0], 1e-9, 1 - 1e-9))
    g = np.random.default_rng(int(cp["semente"]) + 1)
    tot = np.zeros(len(zc))
    for i in range(0, len(p50), 2000):  # em blocos, para caber na memória com o estado inteiro
        sl = slice(i, i + 2000)
        z = np.sqrt(f) * zc[:, None] + np.sqrt(1 - f) * g.standard_normal((len(zc), len(p50[sl])))
        tot += np.maximum(p50[sl] + np.where(z < 0, z * lo[sl], z * hi[sl]), 0.0).sum(axis=1)
    cart = {"p10": float(np.percentile(tot, 10)), "p50": float(p50.sum()), "p90": float(np.percentile(tot, 90))}
    soma = {"p10": float(p10.sum()), "p50": float(p50.sum()), "p90": float(p90.sum())}
    return {"soma": soma, "carteira": cart, "incerteza_padrao": float(tot.std()), "fracao_comum": f,
            "fazendas": int(len(p50)), "sorteios": int(len(zc)),
            "p90_sobre_p50": cart["p10"] / cart["p50"] if cart["p50"] > 0 else None}  # fmt: skip


def parcelas_campo(ha_por_metodo: dict[str, float], r: dict | None = None) -> dict:
    """Quantas parcelas medir no lote (AR-TOOL03 do MDL): n = (t x CV / E)^2, estratos por método com alocação
    proporcional a área x CV, no mínimo 30 no lote e 3 por estrato com área."""
    from scipy.stats import norm

    r = r or regra()
    pc = r["parcelas"]
    t = float(norm.ppf(0.5 + float(pc["confianca"]) / 2))
    e = float(pc["erro_admissivel"])
    cv = {k: float(v) for k, v in pc["cv_biomassa"].items()}
    area = {k: float(v) for k, v in ha_por_metodo.items() if v and v > 0 and k in cv}
    tot = sum(area.values())
    if tot <= 0:
        return {"total": 0, "por_metodo": {}, "t": t, "erro_admissivel": e, "confianca": float(pc["confianca"])}
    wcv = {k: area[k] / tot * cv[k] for k in area}
    n = (t / e) ** 2 * sum(wcv.values()) ** 2
    n = max(n, float(pc["minimo_lote"]))
    por = {k: max(int(math.ceil(n * wcv[k] / sum(wcv.values()))), int(pc["minimo_estrato"])) for k in area}
    return {"total": int(sum(por.values())), "por_metodo": por, "t": round(t, 3), "erro_admissivel": e,
            "confianca": float(pc["confianca"]), "area_parcela_ha": float(pc["area_parcela_ha"]),
            "ha_medidos": round(sum(por.values()) * float(pc["area_parcela_ha"]), 1)}  # fmt: skip


def contrato_para_marcos(volume: float, c: dict | None = None, r: dict | None = None, fator: float = 1.0) -> float:
    """Créditos líquidos até o fim do contrato (P50 do lote) para cumprir TODOS os marcos com a tolerância; o mais
    apertado costuma ser o do ano 7, porque a curva começa devagar."""
    r = r or regra()
    c = c or cenario(r=r)
    T = int(c["prazo_anos"])
    acum = np.cumsum(forma_curva(r))
    acum = acum / acum[min(T, len(acum) - 1)]
    precisa = 0.0
    for i, (ano, pct) in enumerate(zip(c["entregas_anos"], c["marcos_pct"], strict=True)):
        ultimo = i == len(c["entregas_anos"]) - 1
        tol = float(c.get("tolerancia_ultimo_marco") or 0.0) if ultimo else float(c["tolerancia_marco"])
        limiar = volume * float(pct) / 100 * (1 - tol)
        precisa = max(precisa, limiar / max(float(acum[min(ano, len(acum) - 1)]) * fator, 1e-12))
    return precisa


def fator_captura_alvo(chance: float, r: dict | None = None) -> float:
    """Fator comum da captura que o lote precisa aguentar para cumprir com a chance alvo (P10 para 90%)."""
    r = r or regra()
    cc = r["captura_curva"]["incerteza_captura"]
    mc_ = r["cenarios"]["monte_carlo"]
    _, zk = _sorteios(int(mc_["sorteios"]), int(mc_["semente"]))
    fk = _dois_lados(zk, float(cc["p10"]), 1.0, float(cc["p90"]))
    return float(np.percentile(fk, 100 * (1 - chance)))


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


def _p(v: np.ndarray, q: int) -> float:
    return float(np.percentile(v, q))


def _tir_pct(v: np.ndarray) -> np.ndarray:
    return np.where(np.isnan(v), -1.0, v) * 100  # sem TIR = perde tudo


def _equilibrio(s: dict, c: dict) -> float | None:
    """Preço do contrato (US$/t) que zera o VPL do caminho do P50 na taxa do cenário: o VPL anda em linha reta com o
    preço (receita menos o que sai em % dela), então basta uma rodada."""
    fx = float(c["cambio_brl_usd"])
    prop = float(c["tributos_receita"]) + float(c["registro_venda_receita"])
    if c["pagamento_dono"] != "arrendamento":
        prop += float(c["participacao_dono"])
    T = int(c["prazo_anos"])
    d = s["desconto"]
    vend = s["vendidos"][0]
    dv = float(vend[: T + 1] @ d[: T + 1]) * fx * (1 - prop)  # só a receita do contrato anda com o preço
    if dv <= 0:
        return None
    return float(c["preco_usd_t"]) - float(s["vpl"][0]) / dv


def opcoes_metodo(m: dict) -> dict[str, dict]:
    """Os métodos disputam a fazenda: a regra de pontos (regeneração e semeadura onde a distância e o histórico
    deixam, plantio no resto), o plantio total na área toda e a regeneração onde a regra deixa com plantio no resto
    (a semeadura vira plantio). Vence o de menor preço de equilíbrio (custo líquido por crédito)."""
    area = sum(m["por_modo_ha"].values())
    out = {"regra": m}
    if area <= 0:
        return out
    reg, sem = m["por_modo_ha"].get("regeneracao_assistida", 0.0), m["por_modo_ha"].get("semeadura_direta", 0.0)
    if reg + sem > 1e-9:
        out["plantio"] = {**m, "por_modo_ha": {"regeneracao_assistida": 0.0, "semeadura_direta": 0.0,
                                                "plantio_total": area}, "modo": "plantio_total"}  # fmt: skip
    if reg > 1e-9 and sem > 1e-9:
        rp = {"regeneracao_assistida": reg, "semeadura_direta": 0.0, "plantio_total": area - reg}
        out["regeneracao_e_plantio"] = {**m, "por_modo_ha": rp, "modo": max(rp, key=rp.get)}
    return out


def _colunas_pecuaria(linha: dict, r: dict) -> dict:
    pc = renda_pecuaria(linha, r) or {}
    return {"pecuaria_receita_bruta_rs_ha_ano": pc.get("receita_bruta_rs_ha_ano"),
            "pecuaria_lotacao_cab_ha": pc.get("lotacao_cab_ha")}  # fmt: skip


def escolher_metodo(linha: dict, c: dict, r: dict) -> tuple[str, dict, dict]:
    """O método que vence a disputa da fazenda (menor preço de equilíbrio), o modo dele e o preço de cada opção."""
    H = int(c["horizonte_anos"])
    lb = None
    disputa = {}
    escolhido = "regra"
    ops = opcoes_metodo(modos(linha, r))
    for nome, mo in ops.items():
        cu, ca = custo(linha, mo, r, c), captura(linha, mo, r, c)
        lb = lb or linha_base(linha, H, mo, r)
        ds = descontos(linha, ca, lb, c, r)
        if len(ops) > 1 and c.get("modelo") == "curva":
            x = simular_fluxos(cu["por_ano_p50"], [], ca["bruto_ano"], [], ca["teto"], ds["fator"], c, r, ())
            disputa[nome] = _equilibrio(x, c)
    if disputa:  # empate fica com a regra de pontos (a regeneração onde a mata volta)
        escolhido = min(disputa, key=lambda k: (disputa[k] if disputa[k] is not None else math.inf, k != "regra"))
    return escolhido, ops[escolhido], disputa


def _parte_do_preco(s: dict, c: dict) -> np.ndarray:
    """R$/ha que o fluxo do P50 ganha por US$ 1 a mais no preço do contrato, em cada ano (a receita do contrato menos o
    que sai em % dela: tributos, registro e venda, a parte do dono)."""
    prop = float(c["tributos_receita"]) + float(c["registro_venda_receita"])
    if c["pagamento_dono"] != "arrendamento":
        prop += float(c["participacao_dono"])
    T = int(c["prazo_anos"])
    B = np.zeros(len(s["anos"]))
    B[: T + 1] = s["vendidos"][0][: T + 1] * float(c["cambio_brl_usd"]) * (1 - prop)
    return B


def fluxo_p50(linha: dict, c: dict | None = None, r: dict | None = None, fator_captura: float = 1.0,
              fator_custo: float | str = 1.0) -> dict:  # fmt: skip
    """O caminho do P50 da fazenda por ha (o método que venceu a disputa), com a parte que anda com o preço do
    contrato: F(preço) = F + (preço − preço do cenário) × B. Somado no lote (fluxo_lote) dá a TIR e o preço mínimo do
    lote inteiro com o mesmo cálculo da ficha."""
    r = r or regra()
    c = c or cenario(r=r)
    if str(linha.get("vazamento_motivo")) in ("mitigacao_vizinha", "sem_gado"):
        linha = {**linha, "vazamento_mitigacao": True}  # o vazamento por vizinha já foi decidido no município
    escolhido, m, _ = escolher_metodo(linha, c, r)
    cus, cap = custo(linha, m, r, c), captura(linha, m, r, c)
    dsc = descontos(linha, cap, linha_base(linha, int(c["horizonte_anos"]), m, r), c, r)
    if isinstance(fator_custo, str):  # "p10" ou "p90": o custo da própria fazenda nesse ponto da faixa
        fator_custo = float(cus[fator_custo]) / float(cus["p50"]) if cus["p50"] > 0 else 1.0
    s = simular_fluxos(np.asarray(cus["por_ano_p50"], dtype=float) * fator_custo, [],
                       np.asarray(cap["bruto_ano"], dtype=float) * fator_captura, [], cap["teto"], dsc["fator"], c, r,
                       ())  # fmt: skip
    return {"area_ha": float(m["area_ha"]), "metodo": escolhido, "modo": m["modo"], "F": s["F"][0], "K": s["K"][0],
            "B": _parte_do_preco(s, c), "vendidos": s["vendidos"][0],
            "creditos_contrato_ha": float(s["N"][0, int(c["prazo_anos"])]),
            "preco_equilibrio_usd": _equilibrio(s, c)}  # fmt: skip


def fluxo_lote(partes: list[dict], c: dict, multa_por_ano: dict[int, float] | None = None,
               volume: float | None = None) -> dict:  # fmt: skip
    """Soma dos fluxos do P50 das fazendas (R$ no lote inteiro). Com `volume` (o contrato do lote), o crédito entregue
    além dele sai do preço do contrato e é vendido ao preço depois do contrato na primeira venda seguinte (a reserva
    do lote não ganha o preço do contrato). A multa esperada do lote entra no ano do pagamento."""
    H, T = int(c["horizonte_anos"]), int(c["prazo_anos"])
    F, K, B, vend = (np.zeros(H + 1) for _ in range(4))
    for x in partes:
        F += x["area_ha"] * x["F"]
        K += x["area_ha"] * x["K"]
        B += x["area_ha"] * x["B"]
        vend[: T + 1] += x["area_ha"] * x["vendidos"][: T + 1]
    excesso = 0.0
    if volume is not None:
        prop = float(c["tributos_receita"]) + float(c["registro_venda_receita"])
        if c["pagamento_dono"] != "arrendamento":
            prop += float(c["participacao_dono"])
        ganho = float(c["cambio_brl_usd"]) * (1 - prop)  # R$ que fica por crédito e por US$ de preço
        entregue = np.diff(np.minimum(np.cumsum(vend), float(volume)), prepend=0.0)
        sobra = vend - entregue
        excesso = float(sobra.sum())
        F -= sobra * float(c["preco_usd_t"]) * ganho
        B = entregue * ganho
        pos = [int(a) for a in c["entregas_pos_contrato_anos"] if int(a) <= H]
        if pos and excesso > 0:
            F[pos[0]] += excesso * float(c["preco_pos_contrato_usd_t"]) * ganho
    for ano, v in (multa_por_ano or {}).items():
        F[min(int(ano), H)] -= float(v)
    return {"F": F, "K": K, "B": B, "preco_usd": float(c["preco_usd_t"]), "creditos_contrato": float(vend.sum()),
            "excesso_creditos": excesso}  # fmt: skip


def tir_lote(fl: dict, c: dict, preco_usd: float | None = None) -> dict:
    """TIR do projeto e com financiamento do lote a um preço do contrato (a dívida dimensionada no caixa do lote pelo
    ICSD, como o banco faria com o projeto agrupado)."""
    preco = fl["preco_usd"] if preco_usd is None else float(preco_usd)
    F = fl["F"] + (preco - fl["preco_usd"]) * fl["B"]
    div = divida(c, fl["K"], F + fl["K"])
    L = F + div["D"]
    d = (1 + float(c["taxa_desconto"])) ** -np.arange(len(F), dtype=float)
    tp, ta = _tir(F)[0], _tir(L)[0]
    return {"preco_usd": preco, "tir_projeto": None if math.isnan(tp) else float(tp),
            "tir_alavancada": None if math.isnan(ta) else float(ta), "vpl_rs": float(F @ d),
            "divida_fracao": div["fracao"], "pico_capital_rs": float(max(-np.cumsum(L).min(), 0.0))}  # fmt: skip


def preco_para_tir(fl: dict, c: dict, alvo: float, alavancada: bool = True, teto_usd: float = 1000.0) -> float | None:
    """Menor preço do contrato (US$/t) em que a TIR do lote chega ao alvo (fração ao ano), por bisseção."""
    chave = "tir_alavancada" if alavancada else "tir_projeto"

    def ok(p: float) -> bool:
        t = tir_lote(fl, c, p)[chave]
        return t is not None and t >= alvo

    lo, hi = 0.0, teto_usd
    if not ok(hi):
        return None
    if ok(lo):
        return 0.0
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if ok(mid) else (mid, hi)
    return round(hi, 2)


def calcular(linha: dict, c: dict | None = None, r: dict | None = None) -> tuple[dict, dict]:
    """Colunas de desenvolvedor_<mun>.csv para um imóvel (sem as do lote) e o resultado da simulação (fluxos)."""
    r = r or regra()
    c = c or cenario(r=r)
    H, T = int(c["horizonte_anos"]), int(c["prazo_anos"])
    escolhido, m, disputa = escolher_metodo(linha, c, r)
    cus = custo(linha, m, r, c)
    cap = captura(linha, m, r, c)
    lb = linha_base(linha, H, m, r)
    dsc = descontos(linha, cap, lb, c, r)
    mc_ = r["cenarios"]["monte_carlo"]
    zc, zk = _sorteios(int(mc_["sorteios"]), int(mc_["semente"]))
    mcus = _dois_lados(zc, cus["p10"] / cus["p50"], 1.0, cus["p90"] / cus["p50"]) if cus["p50"] > 0 else zc * 0 + 1
    mcap = _dois_lados(zk, cap["rel10"], 1.0, cap["rel90"])
    args = (cus["por_ano_p50"], cap["bruto_ano"], cap["teto"], dsc["fator"])

    def rodar(cc, sorteios=True, tirs=("projeto", "alavancada")):
        return simular_fluxos(args[0], mcus if sorteios else [], args[1], mcap if sorteios else [], args[2], args[3],
                              cc, r, tirs)  # fmt: skip

    s = rodar(c)
    sd = slice(1, None)  # os sorteios (a linha 0 é o caminho do P50)
    area = m["area_ha"]
    cred_ano = s["N"][:, H] / H
    cred_contrato = s["N"][:, T]
    tp, ta = _tir_pct(s["tir_projeto"]), _tir_pct(s["tir_alavancada"])

    # pagamento ao dono: a forma do cenário contra o aluguel fixo do Censo Agro 2017 e o aceite em duas fases
    alug, alug_fonte = arrendamento_censo(linha, c, r)
    comp = {}
    if c.get("modelo") == "curva":
        for nome, muda in (("arrendamento", {"pagamento_dono": "arrendamento", "arrendamento_rs_ha_ano": alug}),
                           ("duas_fases", {"pagamento_dono": "duas_fases"})):  # fmt: skip
            if nome == "arrendamento" and alug is None:
                comp[nome] = None
                continue
            x = rodar({**c, **muda}, sorteios=False, tirs=("projeto",))
            comp[nome] = _tir_pct(x["tir_projeto"])[0]
    # preço que zera o VPL na taxa do cenário (o VPL é quase linear no preço) e custo nivelado por crédito
    preco_eq = _equilibrio(s, c)
    d = s["desconto"]
    pv_cred = float(s["vendidos"][0] @ d)
    fixos = s["K"][0] + s["op"] + s["multas_fluxo"][0] + (s["dono"][0] - float(c.get("participacao_dono") or 0) * s[
        "receita"][0] * (c["pagamento_dono"] != "arrendamento"))  # fmt: skip
    fixos = fixos + s["vendidos"][0] * float(c["taxa_registro_usd_t"]) * float(c["cambio_brl_usd"])
    custo_credito = float(fixos @ d) / pv_cred / float(c["cambio_brl_usd"]) if pv_cred > 0 else None

    marcos = {}
    for i, e in enumerate(c["entregas_anos"]):
        marcos[f"marco_{e}_chance_pct"] = round(100 * float(s["atende"][sd, i].mean()), 1)
    out = {
        "restauracao_area_ha": round(area, 4),
        "modo_restauracao": m["modo"],
        "modo_restauracao_pontos": m["pontos_imovel"],
        "modo_restauracao_regra": "; ".join(
            f"{x['faixa']} {x['fracao']:.0%} {x['pontos']} pts {x['modo']}" for x in m["faixas"] if x["fracao"] > 0
        ),
        **{f"restauracao_{md}_ha": round(v, 4) for md, v in m["por_modo_ha"].items()},
        "distancia_fonte": m["distancia_fonte"],
        "metodo_escolhido": escolhido,
        **{f"metodo_{k}_preco_equilibrio_usd": (round(v, 2) if v is not None else None) for k, v in disputa.items()},
        "custo_restauracao_ha_p10": round(cus["p10"], 0),
        "custo_restauracao_ha_p50": round(cus["p50"], 0),
        "custo_restauracao_ha_p90": round(cus["p90"], 0),
        "custo_implantacao_ha_p50": round(float(cus["por_ano_p50"][0]), 0),
        "custo_fator_ajuste": round(cus["fator"], 4),
        "captura_modelo": cap["modelo"],
        "captura_tco2_ha_ano_p10": round(cap["p10"], 2),
        "captura_tco2_ha_ano_p50": round(cap["p50"], 2),
        "captura_tco2_ha_ano_p90": round(cap["p90"], 2),
        "captura_total_tco2_ha_p50": round(cap["total_p50"], 1),
        "captura_fator_ajuste": round(cap["fator"], 4),
        "desconto_linha_base": round(lb["tco2_ha_ano"], 3),
        "desconto_linha_base_pct": round(100 * dsc["linha_base"], 1),
        "linha_base_medida_pct": round(100 * dsc["linha_base_medida"], 1),
        "linha_base_regenera_pct": round(100 * lb["regenera_ate_o_fim"], 1),
        "linha_base_fonte": lb["fonte"],
        "vazamento_pct": round(100 * dsc["vazamento"], 1),
        "reserva_risco_pct": round(100 * dsc["reserva_risco"], 1),
        "reserva_risco_fonte": dsc["nao_permanencia"]["fonte"],
        "fogo_risco_ano_pct": _r(dsc["nao_permanencia"]["fogo_ano"], 100, 3),
        "derrubada_risco_ano_pct": _r(dsc["nao_permanencia"]["derrubada_ano"], 100, 3),
        "perda_natural_40a_pct": _r(dsc["nao_permanencia"]["perda_40a"], 100, 1),
        "taxa_supressao_secundaria_municipio": _num(linha, "taxa_supressao_secundaria_municipio"),
        "incerteza_pct": round(100 * dsc["incerteza"], 1),
        "fator_liquido": round(dsc["fator"], 4),
        "vazamento_motivo": linha.get("vazamento_motivo")
        or ("mitigacao_marcada" if dsc["vazamento_mitigacao"] else None),
        "vazamento_mitigacao_imovel": linha.get("vazamento_mitigacao_imovel"),
        "cabecas_deslocadas": _num(linha, "cabecas_deslocadas"),
        "rebanho_fonte": linha.get("rebanho_fonte"),
        "credito_liquido_tco2_ha_ano": round(float(cred_ano[0]), 3),
        "credito_liquido_tco2_ha_ano_p10": round(_p(cred_ano[sd], 10), 3),
        "credito_liquido_tco2_ha_ano_p90": round(_p(cred_ano[sd], 90), 3),
        "credito_liquido_tco2_ano": round(float(cred_ano[0]) * area, 1),
        "credito_liquido_tco2_ha_contrato_p10": round(_p(cred_contrato[sd], 10), 1),
        "credito_liquido_tco2_ha_contrato_p50": round(float(cred_contrato[0]), 1),
        "credito_liquido_tco2_ha_contrato_p90": round(_p(cred_contrato[sd], 90), 1),
        "credito_liquido_tco2_contrato": round(float(cred_contrato[0]) * area, 0),
        "credito_liquido_tco2_ha_horizonte": round(float(s["N"][0, H]), 1),
        "volume_contratado_tco2_ha": round(s["V"], 1) if math.isfinite(s["V"]) else None,
        **marcos,
        "marcos_todos_chance_pct": round(100 * float(s["atende"][sd].all(axis=1).mean()), 1),
        "multa_esperada_rs_ha": round(float(s["multas"][sd].sum(axis=1).mean()), 0),
        "rescisao_chance_pct": round(100 * float(s["rescindido"][sd].mean()), 1),
        "vpl_rs_ha_p10": round(_p(s["vpl"][sd], 10), 0),
        "vpl_rs_ha_p50": round(float(s["vpl"][0]), 0),
        "vpl_rs_ha_p90": round(_p(s["vpl"][sd], 90), 0),
        "tir_projeto_pct_p10": round(_p(tp[sd], 10), 1),
        "tir_projeto_pct_p50": round(float(tp[0]), 1),
        "tir_projeto_pct_p90": round(_p(tp[sd], 90), 1),
        "tir_alavancada_pct_p10": round(_p(ta[sd], 10), 1),
        "tir_alavancada_pct_p50": round(float(ta[0]), 1),
        "tir_alavancada_pct_p90": round(_p(ta[sd], 90), 1),
        "pico_capital_proprio_rs_ha_p10": round(_p(s["pico"][sd], 10), 0),
        "pico_capital_proprio_rs_ha_p50": round(float(s["pico"][0]), 0),
        "pico_capital_proprio_rs_ha_p90": round(_p(s["pico"][sd], 90), 0),
        "divida_fracao": round(s["divida"]["fracao"], 3),
        "divida_rs_ha": round(s["divida"]["valor_rs_ha"], 0),
        "divida_limitada_icsd": bool(s["divida"]["limitada_icsd"]),
        "pagamento_dono": c["pagamento_dono"],
        "dono_rs_ha_ano": round(float(s["dono"][0].sum()) / H, 0),
        "arrendamento_referencia_rs_ha_ano": alug,
        **_colunas_pecuaria(linha, r),
        "arrendamento_referencia_fonte": alug_fonte,
        "tir_projeto_pct_arrendamento": None if comp.get("arrendamento") is None else round(comp["arrendamento"], 1),
        "tir_projeto_pct_duas_fases": None if comp.get("duas_fases") is None else round(comp["duas_fases"], 1),
        "custo_credito_usd": None if custo_credito is None else round(custo_credito, 2),
        "preco_equilibrio_usd_t": None if preco_eq is None else round(preco_eq, 2),
        "valor_desenvolvedor_rs": round(float(s["vpl"][0]) * area, 0),
        "restauracao_faltou": ",".join(faltou(linha)),
        "restauracao_cenario": c["cenario"],
        "restauracao_versao": r["versao_completa"],
    }
    return out, {"sim": s, "custo": cus, "captura": cap, "descontos": dsc, "linha_base": lb, "modos": m}


def por_imovel(linha: dict, c: dict | None = None, r: dict | None = None) -> dict:
    """Colunas de desenvolvedor_<mun>.csv para um imóvel (sem as do lote, que dependem dos vizinhos)."""
    return calcular(linha, c, r)[0]


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
    from raiz.salvaguardas import avaliar

    return (
        str(linha.get("filtro_territorial") or "").lower() != "bloqueio"
        and avaliar(linha, linha.get("verificacao"))["pode_originar"]
    )


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
    """Soma por lote: imóveis, ha, crédito por ano, créditos no prazo do contrato (com a curva de captura) e se fecha
    o contrato de referência."""
    r = r or regra()
    alvo = float(r["agrupamento"]["contrato_creditos"])
    prazo = int(c["prazo_anos"])
    df = df.copy()
    if "credito_liquido_tco2_contrato" not in df:  # arquivo antigo, sem a curva: crédito igual todo ano
        df["credito_liquido_tco2_contrato"] = df.credito_liquido_tco2_ano * prazo
    g = df[df.grupo_id.notna()].groupby("grupo_id")
    soma = g.agg(
        grupo_imoveis=("cod_imovel", "count"),
        grupo_ha=("restauracao_area_ha", "sum"),
        grupo_credito_tco2_ano=("credito_liquido_tco2_ano", "sum"),
        grupo_creditos_prazo=("credito_liquido_tco2_contrato", "sum"),
    )
    soma["grupo_fecha_contrato"] = soma.grupo_creditos_prazo >= alvo
    por_ha = (soma.grupo_creditos_prazo / soma.grupo_ha).where(soma.grupo_ha > 0)
    soma["grupo_ha_para_contrato"] = (alvo / por_ha).where(por_ha > 0)
    casas = {"grupo_ha": 2, "grupo_credito_tco2_ano": 1, "grupo_creditos_prazo": 0, "grupo_ha_para_contrato": 0}
    soma = soma.round(casas)
    return df.merge(soma, left_on="grupo_id", right_index=True, how="left")


# --- por município (saida/<UF>/desenvolvedor_<mun>.csv) ----------------------------------------------------------

ENTRADAS = ("filtros", "mapbiomas", "extras", "direto", "ficha", "terra", "rebanho")
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


ENTRADAS_GRAVADAS = ("pasto_d0_ha", "pasto_d1_ha", "pasto_d2_ha", "pasto_d3_ha", "declividade_media_pct",
                     "chuva_mm_ano", "solo_cec_cmolc_kg", "linha_base_taxa_d0", "linha_base_taxa_d1",
                     "linha_base_taxa_d2", "linha_base_taxa_d3", "linha_base_fonte", "estrada_acesso_km",
                     "cidade_proxima_km", "taxa_supressao_secundaria_municipio")  # fmt: skip


def taxa_supressao_secundaria(im) -> float | None:
    """Parte da vegetação secundária do município suprimida no último ano do MapBiomas desmatamento
    (mb_supressao_secundaria_<ano>_ha somado dividido por mb_veg_secundaria_<ano>_ha somado), lida pelo nome."""
    import re

    anos = sorted({int(m.group(1)) for c in im.columns if (m := re.fullmatch(r"mb_supressao_secundaria_(\d{4})_ha", c))
                   and f"mb_veg_secundaria_{m.group(1)}_ha" in im.columns})  # fmt: skip
    if not anos:
        return None
    a = anos[-1]
    sup = float(np.nansum(im[f"mb_supressao_secundaria_{a}_ha"].to_numpy(float)))
    veg = float(np.nansum(im[f"mb_veg_secundaria_{a}_ha"].to_numpy(float)))
    return sup / veg if veg > 0 else None


def _gravado(pasta: Path, cod: int) -> dict[str, dict]:
    """O desenvolvedor_<mun>.csv anterior, por imóvel (vazio se não existe)."""
    import pandas as pd

    f = Path(pasta) / f"desenvolvedor_{cod}.csv"
    if not f.exists():
        return {}
    d = pd.read_csv(f, low_memory=False, dtype={"cod_imovel": str, "grupo_id": str})
    cols = [k for k in (*ENTRADAS_GRAVADAS, "vazamento_motivo", "vazamento_mitigacao_imovel", "cabecas_deslocadas",
                        "rebanho_fonte", "grupo_id") if k in d.columns]  # fmt: skip
    return {str(x["cod_imovel"]): x for x in d[["cod_imovel", *cols]].to_dict("records")}


def linhas_para_refazer(pasta: str | Path, cod: int, so: set[str] | None = None) -> dict[str, dict]:
    """As entradas de cada imóvel como o calcular_municipio as viu (as saídas do motor e as entradas geográficas
    gravadas em desenvolvedor_<mun>.csv, com a vizinha de mitigação já decidida), para refazer o caminho do P50 de
    uma fazenda sem o raster (fluxo_p50, no lote)."""
    import pandas as pd

    pasta = Path(pasta)
    im = linhas_do_municipio(pasta, cod)
    if so is not None:
        im = im[im.cod_imovel.isin({str(x) for x in so})]
    gravadas = _gravado(pasta, cod)
    out = {}
    for li in im.to_dict("records"):
        g = gravadas.get(str(li["cod_imovel"]), {})
        li = {**li, **{k: v for k, v in g.items() if k in ENTRADAS_GRAVADAS and pd.notna(v)}}
        if str(g.get("vazamento_motivo")) in ("mitigacao_vizinha", "sem_gado"):
            li["vazamento_mitigacao"] = True
        out[str(li["cod_imovel"])] = li
    return out


def entradas_com_cache(geo, geo_f: Path, cod: int, cobertura: Path | None, cache: Path | None,
                       fontes: tuple[str, ...]) -> tuple[dict, dict]:  # fmt: skip
    """Entradas geográficas do município (faixas de distância, linha base do YbYrá, declividade, chuva, solo), guardadas
    em cache/entradas/: a chave muda quando o polígono, a cobertura do MapBiomas ou as fontes mudam. Trocar as
    premissas não refaz a parte pesada."""
    import json

    from raiz import restauracao_geo as G

    base = Path(cache or G.pasta_cache())
    st = Path(geo_f).stat()
    cob = Path(cobertura).name if cobertura else "-"
    chave = hashlib.sha256(f"{st.st_size}|{st.st_mtime_ns}|{cob}|{','.join(fontes)}|v1".encode()).hexdigest()[:12]
    f = base / "entradas" / f"{cod}_{chave}.json"
    if f.exists():
        d = json.loads(f.read_text())
        return d["por"], d["mun"]
    por, mun = G.entradas_municipio(geo, cod, cobertura, cache, fontes)
    mun.pop("pontos", None)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"por": por, "mun": mun}, default=float))
    tmp.replace(f)
    return por, mun


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
            por, mun = entradas_com_cache(geo, geo_f, cod, cob[-1] if cob else None, cache, fontes_geo)
    # sem o raster ou sem o contorno (a amostra, uma máquina sem o cache): as entradas já medidas e gravadas no
    # desenvolvedor_<mun>.csv anterior valem, para o recálculo das premissas dar o mesmo que com o raster
    gravado = _gravado(pasta, cod) if (not por or not pontos) else {}
    if not por and gravado:
        geo_k = ENTRADAS_GRAVADAS[:7]
        por = {c_: {k: g[k] for k in geo_k if k in g and pd.notna(g[k])} for c_, g in gravado.items()}
        g0 = next(iter(gravado.values()))
        mun = {k: g0[k] for k in ENTRADAS_GRAVADAS if k.startswith("linha_base_") and k in g0 and pd.notna(g0[k])}
    acesso = ("estrada_acesso_km", "cidade_proxima_km")
    sup_mun = taxa_supressao_secundaria(im)  # derrubada da vegetação secundária no município (não permanência)
    if sup_mun is None and gravado:
        sup_mun = _num(next(iter(gravado.values())), "taxa_supressao_secundaria_municipio")
    registros = []
    for li in im.to_dict("records"):
        g = gravado.get(str(li["cod_imovel"]), {})
        extra = {k: g[k] for k in acesso if pd.isna(li.get(k)) and k in g and pd.notna(g[k])}
        registros.append({**li, **por.get(li["cod_imovel"], {}), **extra,
                          "taxa_supressao_secundaria_municipio": sup_mun})  # fmt: skip
    # vazamento (VMD0054): vizinha a até 15 km que intensifica o pasto recebe o gado e zera o vazamento
    mit = {}
    if pontos and r.get("mitigacao"):
        from raiz import vazamento as V

        mit = V.mitigacoes(registros, pontos, r, area_restauravel, elegivel)
    elif gravado:  # sem contorno: a vizinha decidida antes; as cabeças que saem, com o rebanho de agora
        from raiz import vazamento as V

        por_cod = {str(x["cod_imovel"]): x for x in registros}
        vz = ("vazamento_motivo", "vazamento_mitigacao_imovel")
        for c_, g in gravado.items():
            x = {k: g[k] for k in vz if k in g and pd.notna(g[k])}
            if x:
                x["vazamento_mitigacao"] = str(x.get("vazamento_motivo")) in ("mitigacao_vizinha", "sem_gado")
                li = por_cod.get(c_)
                if li is not None:
                    x["cabecas_deslocadas"] = V.cabecas_deslocadas(li, area_restauravel(li), r)
                    x["rebanho_fonte"] = V.rebanho(li, r)[1]
                mit[c_] = x
    linhas = []
    for linha in registros:
        cod_im = linha["cod_imovel"]
        linha = {**linha, **mit.get(cod_im, {}), **{k: v for k, v in mun.items() if k.startswith("linha_base_")}}
        calc = por_imovel(linha, c, r)
        geo_cols = {k: por.get(cod_im, {}).get(k) for k in (
            "pasto_d0_ha", "pasto_d1_ha", "pasto_d2_ha", "pasto_d3_ha",
            "declividade_media_pct", "chuva_mm_ano", "solo_cec_cmolc_kg")}  # fmt: skip
        geo_cols.update({k: _num(linha, k) for k in ("estrada_acesso_km", "cidade_proxima_km")})  # acesso, da ficha
        linhas.append({"cod_imovel": cod_im, **geo_cols, **calc, "_elegivel": elegivel(linha)})
    df = pd.DataFrame(linhas)
    for f in FAIXAS:
        df[f"linha_base_taxa_{f}"] = mun.get(f"linha_base_taxa_{f}")
    # lote: só quem pode entrar e tem ponto no mapa
    eleg = [(cd, *pontos[cd]) for cd, ok in zip(df.cod_imovel, df._elegivel, strict=True) if ok and cd in pontos]
    rot = agrupar(eleg, r)
    df["grupo_id"] = [f"{cod}-{rot[cd]:04d}" if cd in rot else None for cd in df.cod_imovel]
    if not pontos and gravado:  # sem contorno: o lote de vizinhas calculado antes
        df["grupo_id"] = [gravado.get(cd, {}).get("grupo_id") if isinstance(gravado.get(cd, {}).get("grupo_id"), str)
                          else None for cd in df.cod_imovel]  # fmt: skip
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
    "preco_usd_t", "prazo_anos", "horizonte_anos", "entregas_anos", "marcos_pct", "tolerancia_marco",
    "multa_credito_dia_rs", "multa_marco_dia_rs", "rescisao_multa_fracao", "volume_contratado",
    "preco_pos_contrato_usd_t", "entregas_pos_contrato_anos", "fracao_financiada", "juros_ano", "carencia_anos",
    "juros_carencia", "amortizacao_anos", "sistema_amortizacao", "icsd_minimo", "taxa_desconto", "cambio_brl_usd",
    "manutencao_rs_ha_ano", "manutencao_usd_ha_ano", "monitoramento_rs_ha_ano", "verificacao_rs_ha_entrega",
    "taxa_registro_usd_t", "registro_venda_receita", "tributos_receita", "pagamento_dono", "participacao_dono",
    "piso_dono_rs_ha_ano", "arrendamento_rs_ha_ano", "fase1_rs_ha_ano", "fase1_anos", "linha_base_piso",
    "vazamento", "reserva_risco", "incerteza",
)  # fmt: skip
NOMES_PAGAMENTO = {
    "participacao": "Parte do crédito + piso",
    "arrendamento": "Aluguel fixo por ha",
    "duas_fases": "Aceite em duas fases",
}
NOMES_DESCONTO = {
    "linha_base": "Linha de base (o que a mata faria sozinha)",
    "vazamento": "Vazamento (gado deslocado, VMD0054)",
    "reserva_risco": "Reserva de não permanência",
    "incerteza": "Incerteza",
}


def _faixa(linha: dict, base: str, nd: int = 1) -> dict | None:
    v = {q: _num(linha, f"{base}_{q}") for q in ("p10", "p50", "p90")}
    if v["p50"] is None:
        return None
    return {q: (round(x, nd) if x is not None else None) for q, x in v.items()}


def _curva_p50(linha: dict, c: dict, r: dict) -> dict | None:
    """Captura bruta e crédito líquido acumulado ano a ano (P50), a partir do total gravado e da forma da curva."""
    H = int(c["horizonte_anos"])
    total = _num(linha, "captura_total_tco2_ha_p50")
    fator = _num(linha, "fator_liquido")
    if total is None:
        anual = _num(linha, "captura_tco2_ha_ano_p50")
        if anual is None:
            return None
        total = anual * H
    bruto = np.zeros(H + 1)
    if c.get("modelo") == "curva":
        forma = forma_curva(r)
        k = min(H, len(forma) - 1)
        bruto[: k + 1] = forma[: k + 1] / forma[: k + 1].sum() * total
    else:
        bruto[1:] = total / H
    liq = np.cumsum(bruto * (fator if fator is not None else 1.0))
    return {"anos": list(range(H + 1)), "bruto_tco2_ha": [round(float(x), 2) for x in bruto],
            "liquido_acumulado_tco2_ha": [round(float(x), 1) for x in liq]}  # fmt: skip


def _texto_dono(c: dict, tir: float | None, alug: float | None, tir_alug: float | None) -> str:
    if c["pagamento_dono"] == "participacao":
        piso, anos = float(c["piso_dono_rs_ha_ano"]), int(c["horizonte_anos"])
        base = (f"O dono recebe {100 * float(c['participacao_dono']):.0f}% da receita do crédito, mais um piso de "
                f"R$ {piso:.0f}/ha por ano, por {anos} anos.")  # fmt: skip
    elif c["pagamento_dono"] == "duas_fases":
        base = (f"Aceite em duas fases: R$ {float(c['fase1_rs_ha_ano']):.0f}/ha por ano até o resultado do leilão, "
                f"depois {100 * float(c['participacao_dono']):.0f}% da receita mais o piso.")  # fmt: skip
    else:
        base = f"O dono recebe um aluguel fixo de R$ {float(c['arrendamento_rs_ha_ano']):.0f}/ha por ano."
    if tir is None or alug is None or tir_alug is None or c["pagamento_dono"] == "arrendamento":
        return base
    if tir_alug < tir - 0.05:
        return base + (f" Com o aluguel fixo do Censo Agro 2017 (R$ {alug:.0f}/ha por ano) a TIR cai de {tir:.1f}% "
                       f"para {tir_alug:.1f}%: o aluguel sai todo ano, antes de haver crédito.")  # fmt: skip
    return base + (f" Aqui o aluguel fixo do Censo Agro 2017 (R$ {alug:.0f}/ha por ano) é baixo e a TIR ficaria em "
                   f"{tir_alug:.1f}%, mas o dono não divide o risco da captura.")  # fmt: skip


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
    nome_c = linha.get("restauracao_cenario") or None
    if nome_c not in r["cenarios"]["cenarios"]:
        nome_c = None
    c = cenario(nome_c, r)
    H = int(c["horizonte_anos"])
    area = _num(linha, "restauracao_area_ha") or 0.0
    fl = [x for x in str(linha.get("restauracao_faltou") or "").split(",") if x]
    base_pct = _num(linha, "desconto_linha_base_pct") or 0.0
    medida = _num(linha, "linha_base_medida_pct")
    regenera = _num(linha, "linha_base_regenera_pct") or 0.0
    cred = {
        "p10": _num(linha, "credito_liquido_tco2_ha_ano_p10"),
        "p50": _num(linha, "credito_liquido_tco2_ha_ano"),
        "p90": _num(linha, "credito_liquido_tco2_ha_ano_p90"),
    }
    grupo = linha.get("grupo_id")
    tem_grupo = isinstance(grupo, str) and bool(grupo)
    pct = {k: _num(linha, f"{k}_pct") for k in ("vazamento", "reserva_risco", "incerteza")}
    for k, v in pct.items():  # arquivo antigo, sem as colunas: o valor do cenário
        if v is None:
            pct[k] = 100 * float(c[k])
    piso = 100 * float(c.get("linha_base_piso") or 0.0)
    descontos_ = [
        {"id": "linha_base", "nome": NOMES_DESCONTO["linha_base"], "pct": base_pct,
         "texto": (f"Medida no YbYrá: {medida:.1f}%; piso do cenário: {piso:.0f}%." if medida is not None
                   else "Medida no YbYrá.")},
        {"id": "vazamento", "nome": NOMES_DESCONTO["vazamento"], "pct": pct["vazamento"],
         "texto": ("Zero: há fazenda vizinha de mitigação no lote." if _verdade(linha.get("mitigacao_vizinha"))
                   else "Zero só com fazenda vizinha de mitigação no lote.")},
        {"id": "reserva_risco", "nome": NOMES_DESCONTO["reserva_risco"], "pct": pct["reserva_risco"],
         "texto": _texto_reserva(linha, c)},
        {"id": "incerteza", "nome": NOMES_DESCONTO["incerteza"], "pct": pct["incerteza"], "texto": ""},
    ]  # fmt: skip
    marcos = []
    for e, m_pct in zip(c["entregas_anos"], c["marcos_pct"], strict=True):
        marcos.append({"ano": e, "meta_pct": m_pct, "minimo_pct": round(m_pct * (1 - float(c["tolerancia_marco"])), 1),
                       "chance_pct": _num(linha, f"marco_{e}_chance_pct")})  # fmt: skip
    tir_p = _num(linha, "tir_projeto_pct_p50")
    alug = _num(linha, "arrendamento_referencia_rs_ha_ano")
    tir_alug = _num(linha, "tir_projeto_pct_arrendamento")
    comparacao = [{"forma": c["pagamento_dono"], "nome": NOMES_PAGAMENTO.get(c["pagamento_dono"]), "tir_pct": tir_p,
                   "atual": True}]  # fmt: skip
    if c["pagamento_dono"] != "arrendamento" and alug is not None:
        fonte_alug = linha.get("arrendamento_referencia_fonte")
        comparacao.append({"forma": "arrendamento", "nome": NOMES_PAGAMENTO["arrendamento"], "tir_pct": tir_alug,
                           "rs_ha_ano": alug, "fonte": fonte_alug, "atual": False})  # fmt: skip
    if c["pagamento_dono"] != "duas_fases" and _num(linha, "tir_projeto_pct_duas_fases") is not None:
        comparacao.append({"forma": "duas_fases", "nome": NOMES_PAGAMENTO["duas_fases"],
                           "tir_pct": _num(linha, "tir_projeto_pct_duas_fases"), "atual": False})  # fmt: skip
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
            "implantacao_p50": _num(linha, "custo_implantacao_ha_p50"),
            "tabela": c.get("tabela_custo"),
            "fator_ajuste": _num(linha, "custo_fator_ajuste"),
        },  # fmt: skip
        "captura_tco2_ha_ano": {
            **(_faixa(linha, "captura_tco2_ha_ano", 2) or {}),
            "modelo": c.get("modelo"),
            "total_no_horizonte_p50": _num(linha, "captura_total_tco2_ha_p50"),
            "horizonte_anos": H,
            "fator_ajuste": _num(linha, "captura_fator_ajuste"),
        },  # fmt: skip
        "curva_p50": _curva_p50(linha, c, r),
        "linha_base": {
            "desconto_tco2_ha_ano": _num(linha, "desconto_linha_base"),
            "desconto_pct_da_captura": base_pct,
            "medida_pct": medida,
            "piso_pct": piso,
            "regenera_sozinha_ate_o_fim_pct": regenera,
            "fonte": linha.get("linha_base_fonte"),
            "metodo": r["linha_base"]["metodo"],
            "explicacao": (
                f"Sem projeto, cerca de {regenera:.0f}% deste pasto viraria mata sozinho em {H} anos. "
                f"Esse carbono não vira crédito: o desconto é de {base_pct:.0f}% da captura"
                + (f" (o cenário não deixa ficar abaixo de {piso:.0f}%)." if piso > 0 else ".")
            ),
        },
        "descontos": descontos_,
        "descontos_regra": r["liquido"]["regra"],
        "fator_liquido": _num(linha, "fator_liquido"),
        "credito_liquido_tco2_ha_ano": cred,
        "credito_liquido_tco2_ano": _num(linha, "credito_liquido_tco2_ano"),
        "credito_contrato": {
            **(_faixa(linha, "credito_liquido_tco2_ha_contrato", 1) or {}),
            "total_t": _num(linha, "credito_liquido_tco2_contrato"),
            "prazo_anos": int(c["prazo_anos"]),
        },  # fmt: skip
        "do_bruto_ao_liquido": {
            "reserva_risco": pct["reserva_risco"] / 100,
            "incerteza": pct["incerteza"] / 100,
            "vazamento": pct["vazamento"] / 100,
            "vazamento_situacao": "pendente: gado deslocado (VMD0054) ainda não medido"
            if pct["vazamento"] == 0
            else "",
        },
        "marcos": {
            "lista": marcos,
            "tolerancia_pct": 100 * float(c["tolerancia_marco"]),
            "volume_contratado_tco2_ha": _num(linha, "volume_contratado_tco2_ha"),
            "todos_chance_pct": _num(linha, "marcos_todos_chance_pct"),
            "multa_esperada_rs_ha": _num(linha, "multa_esperada_rs_ha"),
            "rescisao_chance_pct": _num(linha, "rescisao_chance_pct"),
            "regra": (
                f"Multa de R$ {float(c['multa_credito_dia_rs']):.2f} por crédito em falta por dia depois de "
                f"{int(c['multa_carencia_dias'])} dias e de R$ {float(c['multa_marco_dia_rs']):.0f} por dia de marco "
                f"atrasado; rescisão quando as multas chegam a {100 * float(c['rescisao_multa_fracao']):.0f}% do "
                "valor do contrato."
            ),
        },
        "divida": {
            "fracao": _num(linha, "divida_fracao"),
            "rs_ha": _num(linha, "divida_rs_ha"),
            "limitada_icsd": _verdade(linha.get("divida_limitada_icsd")),
            "sistema": c["sistema_amortizacao"],
            "juros_ano": c["juros_ano"],
            "carencia_anos": c["carencia_anos"],
            "icsd_minimo": c.get("icsd_minimo"),
        },
        "pagamento_dono": {
            "forma": c["pagamento_dono"],
            "rs_ha_ano_medio": _num(linha, "dono_rs_ha_ano"),
            "texto": _texto_dono(c, tir_p, alug, tir_alug),
            "comparacao": comparacao,
        },
        "preco_equilibrio_usd_t": _num(linha, "preco_equilibrio_usd_t"),
        "custo_credito_usd": _num(linha, "custo_credito_usd"),
        "vpl_rs_ha": _faixa(linha, "vpl_rs_ha", 0),
        "tir_projeto_pct": _faixa(linha, "tir_projeto_pct", 1),
        "tir_alavancada_pct": _faixa(linha, "tir_alavancada_pct", 1),
        "pico_capital_proprio_rs_ha": _faixa(linha, "pico_capital_proprio_rs_ha", 0),
        "valor_desenvolvedor_rs": _num(linha, "valor_desenvolvedor_rs"),
        "cenario": {k: c[k] for k in ("cenario", "nome", "modelo", "cambio_data", *CENARIO_EDITAVEL) if k in c},
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
            "custo": (
                {md: r["custo_sfb_rs_ha"][md]["fonte"] for md in r["modos"]}
                if c.get("tabela_custo") == "sfb_bom_futuro"
                else {md: r["custo_rs_ha"][md]["fonte"] for md in r["modos"]}
            ),
            "captura": (
                {md: r["captura_curva"]["fonte"] for md in r["modos"]}
                if c.get("modelo") == "curva"
                else {md: r["captura_tco2_ha_ano"][md]["fonte"] for md in r["modos"]}
            ),
            "modo": r["regra_modo"]["fonte"],
            "linha_base": r["linha_base"]["fonte"],
            "liquido": r["liquido"]["fonte"],
            "cenario": fontes_cenario(c["cenario"], r),
        },  # fmt: skip
    }


def simular(linha: dict, nome_cenario: str | None = None, r: dict | None = None, **muda) -> dict:
    """Simulador da ficha: refaz o imóvel com os parâmetros do cenário editados, com o fluxo ano a ano (P50)."""
    r = r or regra()
    nome = nome_cenario or linha.get("restauracao_cenario") or None
    if nome not in r["cenarios"]["cenarios"]:
        nome = None
    c = cenario(nome, r, **muda)
    calc, x = calcular(linha, c, r)
    s = x["sim"]
    bloco = bloco_ficha({**linha, **calc}, r)
    bloco["cenario"] = {k: c[k] for k in ("cenario", "nome", "modelo", "cambio_data", *CENARIO_EDITAVEL) if k in c}

    def lista(v, nd=2):
        return [round(float(a), nd) for a in v]

    bloco["fluxo_p50"] = {
        "anos": [int(a) for a in s["anos"]],
        "projeto_rs_ha": lista(s["F"][0]),
        "com_financiamento_rs_ha": lista(s["L"][0]),
        "receita_rs_ha": lista(s["receita"][0]),
        "dono_rs_ha": lista(s["dono"][0]),
        "multas_rs_ha": lista(s["multas_fluxo"][0]),
        "divida_rs_ha": lista(s["divida"]["D"]),
        "credito_acumulado_tco2_ha": lista(s["N"][0], 1),
    }
    return bloco


ORDENS = {
    "valor_desenvolvedor": "valor_desenvolvedor_rs",
    "vpl_ha": "vpl_rs_ha_p50",
    "tir_alavancada": "tir_alavancada_pct_p50",
    "credito": "credito_liquido_tco2_ano",
}
_INTEIROS = ("prazo_anos", "horizonte_anos", "carencia_anos", "amortizacao_anos", "manutencao_desde_ano", "fase1_anos")
_LISTAS = ("entregas_anos", "marcos_pct", "entregas_pos_contrato_anos")
_OPCOES = {
    "sistema_amortizacao": ("sac", "price", "icsd"),
    "pagamento_dono": tuple(NOMES_PAGAMENTO),
    "juros_carencia": ("pagos", "capitalizados"),
}
_LIMITES = {
    "preco_usd_t": (0.01, 1000), "prazo_anos": (1, 60), "horizonte_anos": (1, 80), "tolerancia_marco": (0, 1),
    "multa_credito_dia_rs": (0, 100), "multa_marco_dia_rs": (0, 1e7), "rescisao_multa_fracao": (0, 1),
    "volume_contratado": (0.05, 2), "preco_pos_contrato_usd_t": (0, 1000), "fracao_financiada": (0, 1),
    "juros_ano": (0, 1), "carencia_anos": (0, 60), "amortizacao_anos": (1, 60), "icsd_minimo": (1, 5),
    "taxa_desconto": (0, 1), "cambio_brl_usd": (0.01, 100), "manutencao_rs_ha_ano": (0, 1e5),
    "manutencao_usd_ha_ano": (0, 1e4), "monitoramento_rs_ha_ano": (0, 1e5), "verificacao_rs_ha_entrega": (0, 1e5),
    "taxa_registro_usd_t": (0, 100), "registro_venda_receita": (0, 0.9), "tributos_receita": (0, 0.9),
    "participacao_dono": (0, 0.9), "piso_dono_rs_ha_ano": (0, 1e5), "arrendamento_rs_ha_ano": (0, 1e5),
    "fase1_rs_ha_ano": (0, 1e5), "fase1_anos": (0, 20), "linha_base_piso": (0, 1), "vazamento": (0, 1),
    "reserva_risco": (0.20, 1), "incerteza": (0, 1),
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
        if k in _LISTAS:
            try:
                muda[k] = [float(x) if k == "marcos_pct" else int(x)
                           for x in str(v).replace(";", ",").split(",") if x.strip()]  # fmt: skip
            except ValueError as ex:
                raise ValueError(f"{k}: números separados por vírgula, como 7,12,17,22,25") from ex
            if not muda[k] and k == "entregas_anos":
                raise ValueError("entregas_anos: pelo menos um ano de entrega")
        elif k in _OPCOES:
            if v not in _OPCOES[k]:
                raise ValueError(f"{k}: use {', '.join(_OPCOES[k])}")
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
    if "entregas_anos" in muda and "marcos_pct" not in muda:
        c = cenario(nome)
        if len(c["marcos_pct"]) != len(muda["entregas_anos"]):  # marcos proporcionais ao ano, até 100% no último
            muda["marcos_pct"] = [round(100 * a / max(muda["entregas_anos"]), 1) for a in muda["entregas_anos"]]
    return nome, muda


def cenarios_publicos(r: dict | None = None) -> dict:
    r = r or regra()
    out = {}
    for nome in r["cenarios"]["cenarios"]:
        c = cenario(nome, r)
        out[nome] = {"nome": c["nome"], "modelo": c.get("modelo"),
                     "parametros": {k: c[k] for k in CENARIO_EDITAVEL if k in c},
                     "fontes": fontes_cenario(nome, r)}  # fmt: skip
    return {"padrao": r["cenarios"]["padrao"], "versao": versao(), "cenarios": out, "editaveis": list(CENARIO_EDITAVEL),
            "opcoes": {k: list(v) for k, v in _OPCOES.items()}, "cambio": r.get("cambio") or None}  # fmt: skip


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
