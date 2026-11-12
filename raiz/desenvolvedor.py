"""Valor para quem restaura (o desenvolvedor) com as premissas da rodada 11: motor/premissas/restauracao_v2026_11.yaml.

Por hectare, em reais reais (o preço do ProFloresta+ é reajustado pelo IPCA):
 1. dois métodos disputam cada fazenda: plantio total em toda a área, ou regeneração assistida onde a regra de pontos
    deixa (raiz/restauracao.py) e plantio no resto;
 2. captura: total de 40 anos do método (Bom Futuro), no máximo o teto do bioma, distribuída no tempo pela curva
    oficial da concessão Triunfo do Xingu;
 3. do bruto ao líquido, nesta ordem: linha de base, vazamento (zero com área de mitigação vizinha), reserva de risco e
    incerteza;
 4. receita: entregas do Anexo IV (anos 7, 12, 17, 22 e 25) ao preço do contrato e venda dos anos 26 a 40;
 5. custos: implantação, manutenção inicial, manutenção anual, taxa de registro e pagamento ao dono (três formas);
 6. dívida do Fundo Clima: fração do investimento, juros capitalizados na carência, SAC até o ano 25, limitada pela
    cobertura (ICSD) em cada janela de entrega;
 7. TIR real do projeto e do acionista, VPL ao custo de capital, pico de caixa, preço de equilíbrio (custo líquido por
    crédito) e hectares por milhão de créditos;
 8. lote pelo custo líquido por crédito, com reservas até a chance alvo de cumprir os marcos; chance de cumprir cada
    marco, multa esperada e chance de rescisão.
Tudo é estimativa a calibrar com dado real (raiz/restauracao_aprendizado.py). Sem nome, CPF ou CNPJ.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

from raiz import RAIZ_REPO

ARQ_PREMISSAS = RAIZ_REPO / "motor" / "premissas" / "restauracao_v2026_11.yaml"
METODOS = ("regeneracao_assistida", "plantio_total")
FORMAS_DONO = ("parte_credito", "aluguel_fixo", "duas_fases")
Z90 = 1.2815515655446004


# --- premissas e cenário ---------------------------------------------------------------------------------------------


@lru_cache
def _ler(arq: Path, _marca: tuple = ()) -> dict:
    texto = arq.read_bytes()
    p = yaml.safe_load(texto)
    p["hash"] = hashlib.sha256(texto).hexdigest()[:8]
    p["versao_completa"] = f"{p['versao']}+{p['hash']}"
    return p


def premissas(arq: Path | None = None) -> dict:
    """As premissas da rodada 11, com versao_completa = versão + hash do arquivo (relê quando o arquivo muda)."""
    a = Path(arq or ARQ_PREMISSAS)
    st = a.stat()
    return _ler(a, (str(a), st.st_mtime_ns, st.st_size))


def versao(arq: Path | None = None) -> str:
    return premissas(arq)["versao_completa"]


def _valor(x):
    return x["valor"] if isinstance(x, dict) and "valor" in x else x


def _nivel(x, nivel: str):
    if isinstance(x, dict) and nivel in x:
        return x[nivel]
    return _valor(x)


EDITAVEIS = (
    "preco_contrato_usd_t", "venda_apos_contrato_usd_t", "venda_apos_contrato", "cambio_brl_usd", "taxa_desconto",
    "fracao_financiada", "juros_ano", "carencia_anos", "icsd_minimo", "linha_base", "vazamento", "reserva_risco",
    "incerteza", "taxa_registro", "manutencao_usd_ha_ano", "forma_dono", "parte_dono", "piso_dono_rs_ha_ano",
    "aluguel_rs_ha_ano", "metodo",
)  # fmt: skip


FONTE_DO_EDITAVEL = {
    "preco_contrato_usd_t": "preco", "venda_apos_contrato_usd_t": "venda_apos_contrato",
    "venda_apos_contrato": "venda_apos_contrato", "cambio_brl_usd": "cambio", "taxa_desconto": "taxa_desconto",
    "fracao_financiada": "financiamento", "juros_ano": "juros", "carencia_anos": "carencia", "icsd_minimo": "icsd",
    "linha_base": "linha_base", "vazamento": "vazamento", "reserva_risco": "reserva_risco", "incerteza": "incerteza",
    "taxa_registro": "taxa_registro", "manutencao_usd_ha_ano": "manutencao", "forma_dono": "parte_dono",
    "parte_dono": "parte_dono", "piso_dono_rs_ha_ano": "piso_dono", "aluguel_rs_ha_ano": "aluguel_dono",
    "metodo": "custo_regeneracao",
}  # fmt: skip


def cenario(nome: str | None = None, p: dict | None = None, **muda) -> dict:
    """Parâmetros do cenário (central, estresse, otimista, so_contrato_25) com as mudanças do simulador."""
    p = p or premissas()
    nome = nome or p["padrao"]
    if nome not in p["cenarios"]:
        raise ValueError(f"cenário desconhecido: {nome} (use {', '.join(p['cenarios'])})")
    cen = p["cenarios"][nome]
    nv = cen.get("nivel", "central")
    rec, fin, d, dono = p["receita"], p["financiamento"], p["descontos"], p["dono"]
    c = {
        "cenario": nome,
        "nome": cen["nome"],
        "nivel": nv,
        "preco_contrato_usd_t": float(_nivel(rec["preco_contrato_usd_t"], nv)),
        "venda_apos_contrato_usd_t": float(_valor(rec["venda_apos_contrato_usd_t"])),
        "venda_apos_contrato": bool(cen.get("venda_apos_contrato", True)),
        "cambio_brl_usd": float(_valor(rec["cambio_brl_usd"])),
        "taxa_registro": float(_valor(rec["taxa_registro_receita"])),
        "manutencao_usd_ha_ano": float(_valor(rec["manutencao_usd_ha_ano"])),
        "manutencao_desde_ano": int(rec["manutencao_usd_ha_ano"].get("desde_ano", 3)),
        "taxa_desconto": float(_valor(rec["taxa_desconto_real"])),
        "fracao_financiada": float(_nivel(fin["fracao_investimento"], nv)),
        "juros_ano": float(_nivel(fin["juros_ano"], nv)),
        "carencia_anos": int(_valor(fin["carencia_anos"])),
        "ultimo_ano_divida": int(fin["ultimo_ano"]),
        "icsd_minimo": float(_valor(fin["icsd_minimo"])),
        "linha_base": float(_nivel(d["linha_base"], nv)),
        "vazamento": float(_nivel(d["vazamento"], nv)),
        "vazamento_com_mitigacao": float(d["vazamento"]["com_area_de_mitigacao"]),
        "reserva_risco": float(_valor(d["reserva_risco"])),
        "incerteza": float(_valor(d["incerteza"])),
        "forma_dono": dono["forma_padrao"],
        "parte_dono": float(_nivel(dono["formas"]["parte_credito"]["parte"], nv)),
        "piso_dono_rs_ha_ano": float(_valor(dono["formas"]["parte_credito"]["piso_rs_ha_ano"])),
        "aluguel_rs_ha_ano": None,  # None = o do Censo Agro pelo município da fazenda
        "opcao_rs_ha_mes": float(_valor(dono["formas"]["duas_fases"]["opcao_rs_ha_mes"])),
        "opcao_meses": float(_valor(dono["formas"]["duas_fases"]["meses_ate_resultado"])),
        "prazo_dono_anos": int(_valor(dono["prazo_contrato_anos"])),
        "metodo": "auto",
    }
    for k, v in muda.items():
        if v is None:
            continue
        if k not in EDITAVEIS:
            raise ValueError(f"parâmetro desconhecido no cenário: {k}")
        c[k] = v
    if c["forma_dono"] not in FORMAS_DONO:
        raise ValueError(f"forma de pagamento ao dono desconhecida: {c['forma_dono']}")
    if c["metodo"] not in ("auto", *METODOS):
        raise ValueError(f"método desconhecido: {c['metodo']}")
    return c


def fontes(p: dict | None = None) -> dict[str, str]:
    """De onde vem cada grupo de premissas (para a ficha e o relatório)."""
    p = p or premissas()
    m = p["metodos"]
    g = {
        "custo_plantio": m["plantio_total"]["custo_implantacao_rs_ha"]["fonte"],
        "custo_regeneracao": m["regeneracao_assistida"]["custo_implantacao_rs_ha"]["fonte"],
        "manutencao_inicial_regeneracao": m["regeneracao_assistida"]["manutencao_inicial_rs_ha"]["fonte"],
        "faixa_custo_plantio": m["plantio_total"]["custo_faixa_rs_ha"]["fonte"],
        "faixa_custo_regeneracao": m["regeneracao_assistida"]["custo_faixa_rs_ha"]["fonte"],
        "captura_plantio": m["plantio_total"]["captura_40_anos_tco2_ha"]["fonte"],
        "captura_regeneracao": m["regeneracao_assistida"]["captura_40_anos_tco2_ha"]["fonte"],
        "curva": p["curva"]["fonte"],
        "incerteza_captura": p["incerteza_captura"]["fonte"],
        "linha_base": p["descontos"]["linha_base"]["fonte"],
        "vazamento": p["descontos"]["vazamento"]["fonte"],
        "reserva_risco": p["descontos"]["reserva_risco"]["fonte"],
        "incerteza": p["descontos"]["incerteza"]["fonte"],
        "preco": p["receita"]["preco_contrato_usd_t"]["fonte"],
        "venda_apos_contrato": p["receita"]["venda_apos_contrato_usd_t"]["fonte"],
        "cambio": p["receita"]["cambio_brl_usd"]["fonte"],
        "taxa_registro": p["receita"]["taxa_registro_receita"]["fonte"],
        "manutencao": p["receita"]["manutencao_usd_ha_ano"]["fonte"],
        "taxa_desconto": p["receita"]["taxa_desconto_real"]["fonte"],
        "financiamento": p["financiamento"]["fracao_investimento"]["fonte"],
        "juros": p["financiamento"]["juros_ano"]["fonte"],
        "carencia": p["financiamento"]["carencia_anos"]["fonte"],
        "icsd": p["financiamento"]["icsd_minimo"]["fonte"],
        "contrato": p["contrato"]["fonte"],
        "prazo_dono": p["dono"]["prazo_contrato_anos"]["fonte"],
        "parte_dono": p["dono"]["formas"]["parte_credito"]["parte"]["fonte"],
        "piso_dono": p["dono"]["formas"]["parte_credito"]["piso_rs_ha_ano"]["fonte"],
        "aluguel_dono": p["dono"]["formas"]["aluguel_fixo"]["fonte"],
        "mitigacao": p["mitigacao"]["fonte"],
    }
    # cada parâmetro que o simulador muda aponta para a fonte do seu grupo
    g.update({k: g[v] for k, v in FONTE_DO_EDITAVEL.items()})
    return g


# --- captura no tempo ------------------------------------------------------------------------------------------------


def forma_curva(p: dict | None = None) -> np.ndarray:
    """Remoção bruta por ano (anos 1 a 40) da curva oficial, interpolada em linha reta, somando 1."""
    p = p or premissas()
    pts = {int(k): float(v) for k, v in p["curva"]["pontos_tco2_ha_ano"].items()}
    anos = np.arange(1, int(p["curva"]["horizonte_anos"]) + 1)
    xs = sorted(pts)
    y = np.interp(anos, xs, [pts[x] for x in xs])
    return y / y.sum()


def teto_bioma(bioma: str | None, p: dict | None = None) -> tuple[float, bool, str]:
    """Teto da captura em 40 anos no bioma: (tCO2/ha, publicado, nome do bioma usado)."""
    p = p or premissas()
    t = p["teto_bioma_tco2_ha_40_anos"]
    b = bioma if isinstance(bioma, str) and bioma in t else p["bioma_padrao"]
    return float(t[b]["valor"]), bool(t[b]["publicado"]), b


def total_metodo(metodo: str, bioma: str | None, fator: float = 1.0, p: dict | None = None) -> float:
    """Captura bruta de 40 anos por ha do método (vezes ajustes e calibração), no máximo o teto do bioma."""
    p = p or premissas()
    tot = float(p["metodos"][metodo]["captura_40_anos_tco2_ha"]["valor"]) * fator
    return min(tot, teto_bioma(bioma, p)[0])


def fator_liquido(c: dict, mitigacao: bool = False) -> float:
    """Do bruto ao líquido: (1 - linha de base) x (1 - vazamento) x (1 - reserva) x (1 - incerteza)."""
    vaz = c["vazamento_com_mitigacao"] if mitigacao else c["vazamento"]
    return (1 - c["linha_base"]) * (1 - vaz) * (1 - c["reserva_risco"]) * (1 - c["incerteza"])


def marcos(p: dict | None = None) -> list[dict]:
    p = p or premissas()
    return [dict(m) for m in p["contrato"]["marcos"]]


def fracao_ate(ano: int, p: dict | None = None) -> float:
    """Parte da captura de 40 anos que já entrou até o fim do ano."""
    f = forma_curva(p)
    return float(f[: max(min(ano, len(f)), 0)].sum())


# --- aluguel de referência --------------------------------------------------------------------------------------------


def aluguel_referencia(cod_municipio, uf: str | None, p: dict | None = None) -> tuple[float, str]:
    """Aluguel pago por ha e ano no Censo Agro 2017: o do município, senão o da UF, senão o do Brasil."""
    p = p or premissas()
    a = p["dono"]["formas"]["aluguel_fixo"]
    try:
        cm = int(float(cod_municipio))
    except (TypeError, ValueError):
        cm = None
    if cm is not None and cm in a["por_municipio_rs_ha_ano"]:
        return float(a["por_municipio_rs_ha_ano"][cm]), "municipio"
    if isinstance(uf, str) and uf.upper() in a["por_uf_rs_ha_ano"]:
        return float(a["por_uf_rs_ha_ano"][uf.upper()]), "uf"
    return float(a["brasil_rs_ha_ano"]), "brasil"


# --- fluxo de caixa por hectare (vetorizado nos sorteios) ----------------------------------------------------------


def _tir(cf: np.ndarray) -> np.ndarray:
    """TIR de cada linha (fluxo anual 0..T). Procura a primeira troca de sinal de positivo para negativo entre -90% e
    150% ao ano e refina por bisseção; NaN quando não existe (o projeto não se paga)."""
    cf = np.atleast_2d(cf)
    t = np.arange(cf.shape[1])
    grade = np.concatenate([np.linspace(-0.9, -0.1, 17), np.linspace(-0.09, 0.6, 70), np.linspace(0.62, 1.5, 23)])
    vpl = cf @ ((1 + grade[None, :]) ** -t[:, None])
    pos, neg = vpl[:, :-1] > 0, vpl[:, 1:] <= 0
    troca = pos & neg
    tem = troca.any(axis=1)
    i = np.argmax(troca, axis=1)
    lo, hi = grade[i].astype(float), grade[np.minimum(i + 1, len(grade) - 1)].astype(float)
    for _ in range(60):
        mid = (lo + hi) / 2
        v = np.einsum("nt,nt->n", cf, (1 + mid[:, None]) ** -t[None, :])
        lo = np.where(v > 0, mid, lo)
        hi = np.where(v > 0, hi, mid)
    return np.where(tem, (lo + hi) / 2, np.nan)


def _janelas(entregas: list[int], ultimo: int) -> list[tuple[int, int]]:
    """Cada entrega paga as parcelas até a entrega seguinte: [e_k, e_{k+1} - 1]; a última só o próprio ano."""
    out = []
    for k, e in enumerate(entregas):
        fim = entregas[k + 1] - 1 if k + 1 < len(entregas) else e
        out.append((e, min(fim, ultimo)))
    return out


def fluxo(
    custo_impl: np.ndarray | float,
    manut_inicial: np.ndarray | float,
    credito_ano: np.ndarray,
    c: dict,
    forma: str | None = None,
    aluguel_rs_ha_ano: float | None = None,
    p: dict | None = None,
) -> dict[str, np.ndarray]:
    """Fluxo anual por ha (anos 0..40) e indicadores, para N sorteios.

    custo_impl e manut_inicial: R$/ha (N,) ou escalar; credito_ano: crédito LÍQUIDO por ha por ano, (N, 40) ou (40,).
    """
    p = p or premissas()
    forma = forma or c["forma_dono"]
    cred = np.atleast_2d(np.asarray(credito_ano, dtype=float))
    n, horiz = cred.shape[0], cred.shape[1]
    T = horiz
    ci = np.broadcast_to(np.asarray(custo_impl, dtype=float), (n,)).astype(float)
    mi = np.broadcast_to(np.asarray(manut_inicial, dtype=float), (n,)).astype(float)
    anos_mi = list(p["metodos"]["plantio_total"]["manutencao_inicial_rs_ha"].get("anos", [1, 2]))
    fx = c["cambio_brl_usd"]
    preco = c["preco_contrato_usd_t"] * fx
    venda = c["venda_apos_contrato_usd_t"] * fx
    entregas = [int(m["ano"]) for m in p["contrato"]["marcos"]]
    prazo = int(p["contrato"]["prazo_anos"])

    invest = np.zeros((n, T + 1))
    invest[:, 0] = ci
    for a in anos_mi:
        invest[:, a] += mi / len(anos_mi)
    # receita: o crédito de cada ano sai na entrega seguinte; depois do contrato, venda no próprio ano
    rec = np.zeros((n, T + 1))
    vol = np.zeros((n, T + 1))  # créditos vendidos em cada ano
    ant = 0
    for e in entregas:
        v = cred[:, ant:e].sum(axis=1)
        vol[:, e] += v
        rec[:, e] += v * preco
        ant = e
    if c["venda_apos_contrato"]:
        for t in range(prazo + 1, T + 1):
            vol[:, t] += cred[:, t - 1]
            rec[:, t] += cred[:, t - 1] * venda
    manut = np.zeros(T + 1)
    manut[c["manutencao_desde_ano"] :] = c["manutencao_usd_ha_ano"] * fx
    # dono
    dono = np.zeros((n, T + 1))
    prazo_dono = min(int(c["prazo_dono_anos"]), T)
    if forma == "aluguel_fixo":
        alu = float(aluguel_rs_ha_ano if aluguel_rs_ha_ano is not None else c["aluguel_rs_ha_ano"] or 0.0)
        dono[:, 1 : prazo_dono + 1] += alu
        parte = 0.0
    else:
        parte = c["parte_dono"]
        dono[:, 1 : prazo_dono + 1] += c["piso_dono_rs_ha_ano"]
        dono += parte * rec
        if forma == "duas_fases":
            dono[:, 0] += c["opcao_rs_ha_mes"] * c["opcao_meses"]
    reg = c["taxa_registro"] * rec
    proj = -invest + rec - reg - manut[None, :] - dono

    # dívida: draws proporcionais ao investimento; juros capitalizados na carência; SAC até o último ano
    fin, j, car, ult = c["fracao_financiada"], c["juros_ano"], int(c["carencia_anos"]), int(c["ultimo_ano_divida"])
    draws = fin * invest
    serv = np.zeros((n, T + 1))
    saldo = np.zeros(n)
    amort = np.zeros(n)
    for t in range(T + 1):
        juros = saldo * j
        if t <= car:
            saldo = saldo + juros
        elif t <= ult:
            if t == car + 1:
                amort = saldo / max(ult - car, 1)
            a = np.minimum(amort, saldo)
            serv[:, t] = a + juros
            saldo = saldo - a
        saldo = saldo + draws[:, t]
    serv[:, min(ult, T)] += np.where(saldo > 1e-9, saldo, 0.0)  # sobra (não acontece com carência < último ano)
    # cobertura por janela de entrega: k = escala da dívida (0 a 1) que respeita o ICSD mínimo em toda janela
    k = np.ones(n)
    icsd_min = np.full(n, np.inf)
    for a, b in _janelas(entregas, ult):
        s = serv[:, a : b + 1].sum(axis=1)
        cfads = proj[:, a : b + 1].sum(axis=1)
        com = s > 1e-9
        lim = np.where(com, np.maximum(cfads, 0.0) / (c["icsd_minimo"] * np.where(com, s, 1.0)), np.inf)
        k = np.minimum(k, lim)
    k = np.clip(k, 0.0, 1.0)
    for a, b in _janelas(entregas, ult):
        s = serv[:, a : b + 1].sum(axis=1) * k
        cfads = proj[:, a : b + 1].sum(axis=1)
        icsd_min = np.minimum(icsd_min, np.where(s > 1e-9, cfads / np.where(s > 1e-9, s, 1.0), np.inf))
    acion = proj + k[:, None] * (draws - serv)
    tt = np.arange(T + 1)
    d = (1 + c["taxa_desconto"]) ** -tt
    vpl = proj @ d
    # preço de equilíbrio: um preço único por crédito que paga o custo de capital (VPL = 0 sem dívida)
    custos_fixos = invest + manut[None, :] + (dono - parte * rec)
    vol_pv = vol @ d
    equilibrio = np.where(vol_pv > 0, (custos_fixos @ d) / np.maximum((1 - c["taxa_registro"] - parte) * vol_pv,
                                                                      1e-9), np.inf)  # fmt: skip
    return {
        "projeto": proj,
        "acionista": acion,
        "receita": rec,
        "dono": dono,
        "volume": vol,
        "vpl_rs_ha": vpl,
        "tir_projeto": _tir(proj),
        "tir_acionista": _tir(acion),
        "pico_caixa_rs_ha": np.maximum(-np.cumsum(acion, axis=1).min(axis=1), 0.0),
        "fracao_divida": k * fin,
        "icsd_min": np.where(np.isfinite(icsd_min), icsd_min, np.nan),
        "preco_equilibrio_rs_t": equilibrio,
        "dono_rs_ha_ano_medio": dono[:, 1 : prazo_dono + 1].mean(axis=1),
    }


# --- uma opção (mistura de métodos) numa fazenda -------------------------------------------------------------


def opcao_por_ha(
    fracoes: dict[str, float],
    bioma: str | None,
    c: dict,
    fator_custo: float = 1.0,
    fator_captura: float = 1.0,
    calibracao: dict[str, tuple[float, float]] | None = None,
    mitigacao: bool = False,
    p: dict | None = None,
) -> dict:
    """Custo e crédito por ha de uma opção (fração de cada método), no P50 e nas faixas P10 e P90.

    calibracao: {metodo: (fator_custo, fator_captura)} vindo do real dos clientes.
    """
    p = p or premissas()
    cal = calibracao or {}
    forma = forma_curva(p)
    impl = manut = c10 = c90 = 0.0
    total = 0.0
    for md, fr in fracoes.items():
        if fr <= 0:
            continue
        m = p["metodos"][md]
        fc, fk = cal.get(md, (1.0, 1.0))
        i = float(m["custo_implantacao_rs_ha"]["valor"]) * fator_custo * fc
        mt = float(m["manutencao_inicial_rs_ha"]["valor"]) * fator_custo * fc
        p50 = float(m["custo_implantacao_rs_ha"]["valor"]) + float(m["manutencao_inicial_rs_ha"]["valor"])
        impl += fr * i
        manut += fr * mt
        c10 += fr * float(m["custo_faixa_rs_ha"]["p10"]) / p50 * (i + mt)
        c90 += fr * float(m["custo_faixa_rs_ha"]["p90"]) / p50 * (i + mt)
        total += fr * total_metodo(md, bioma, fator_captura * fk, p)
    liq = fator_liquido(c, mitigacao)
    return {
        "custo_impl": impl,
        "manut_inicial": manut,
        "custo_total": impl + manut,
        "custo_p10": c10,
        "custo_p90": c90,
        "bruto_40": total,
        "liquido_40": total * liq,
        "fator_liquido": liq,
        "credito_ano": forma * total * liq,  # (40,)
    }


@lru_cache
def _sorteios(n: int, semente: int) -> tuple[np.ndarray, np.ndarray]:
    g = np.random.default_rng(semente)
    return g.standard_normal(n), g.standard_normal(n)


def _dois_lados(z: np.ndarray, p10: float, p50: float, p90: float) -> np.ndarray:
    lo, hi = (p50 - p10) / Z90, (p90 - p50) / Z90
    return np.maximum(p50 + np.where(z < 0, z * lo, z * hi), 0.0)


def fatores_captura(p: dict | None = None) -> np.ndarray:
    p = p or premissas()
    mc = p["monte_carlo"]
    _, zk = _sorteios(int(mc["sorteios"]), int(mc["semente"]))
    ic = p["incerteza_captura"]
    return _dois_lados(zk, float(ic["p10"]), 1.0, float(ic["p90"]))


def avaliar(op: dict, c: dict, forma: str | None = None, aluguel: float | None = None, faixa: bool = True,
            p: dict | None = None) -> dict:  # fmt: skip
    """Indicadores de uma opção: central (premissas no P50) e, com faixa=True, P10 e P90 por Monte Carlo."""
    p = p or premissas()
    f = fluxo(op["custo_impl"], op["manut_inicial"], op["credito_ano"], c, forma, aluguel, p)
    out = {k: float(v[0]) for k, v in f.items() if isinstance(v, np.ndarray) and v.ndim == 1}
    out["fluxo_projeto"] = f["projeto"][0]
    out["fluxo_acionista"] = f["acionista"][0]
    if faixa:
        mc = p["monte_carlo"]
        zc, _ = _sorteios(int(mc["sorteios"]), int(mc["semente"]))
        custos = _dois_lados(zc, op["custo_p10"], op["custo_total"], op["custo_p90"])
        esc = custos / op["custo_total"] if op["custo_total"] > 0 else np.ones_like(custos)
        fk = fatores_captura(p)
        g = fluxo(op["custo_impl"] * esc, op["manut_inicial"] * esc, fk[:, None] * op["credito_ano"][None, :], c,
                  forma, aluguel, p)  # fmt: skip
        for nome in ("vpl_rs_ha", "tir_projeto", "tir_acionista", "pico_caixa_rs_ha", "preco_equilibrio_rs_t"):
            v = g[nome]
            if nome.startswith("tir"):
                v = np.where(np.isnan(v), -1.0, v)
            out[f"{nome}_p10"] = float(np.percentile(v, 10))
            out[f"{nome}_p90"] = float(np.percentile(v, 90))
        out["custo_p10"], out["custo_p90"] = op["custo_p10"], op["custo_p90"]
    return out


def ha_por_milhao(liquido_40_ha: float, p: dict | None = None, marcos_todos: bool = False) -> float | None:
    """Hectares para 1 milhão de créditos líquidos: pelo volume do contrato (ano 25) ou por todos os marcos com a
    tolerância (o mais apertado costuma ser o ano 7, porque a curva começa devagar)."""
    p = p or premissas()
    if liquido_40_ha <= 0:
        return None
    vol = float(p["contrato"]["creditos"])
    if not marcos_todos:
        return vol / (liquido_40_ha * fracao_ate(int(p["contrato"]["prazo_anos"]), p))
    return creditos_40_necessarios(vol, p) / liquido_40_ha


def creditos_40_necessarios(volume: float, p: dict | None = None, fator: float = 1.0) -> float:
    """Créditos líquidos de 40 anos (soma das fazendas) para cumprir todos os marcos do Anexo IV com a tolerância."""
    p = p or premissas()
    tol = float(p["contrato"]["tolerancia_intermediaria"])
    ms = p["contrato"]["marcos"]
    precisa = 0.0
    for i, m in enumerate(ms):
        alvo = volume * float(m["acumulado"]) / float(p["contrato"]["creditos"])
        limiar = alvo if i == len(ms) - 1 else alvo * (1 - tol)
        precisa = max(precisa, limiar / max(fracao_ate(int(m["ano"]), p) * fator, 1e-12))
    return precisa


# --- cronograma do ProFloresta+: chance de cumprir, multa esperada, rescisão ---------------------------------------


def cronograma(credito_40_total: float, preco_brl_t: float, p: dict | None = None, volume: float | None = None,
               fatores: np.ndarray | None = None) -> dict:  # fmt: skip
    """Chance de cumprir cada marco, multa esperada e chance de rescisão de um lote com credito_40_total créditos
    líquidos em 40 anos (P50). O erro da captura é sorteado como um fator comum ao lote inteiro."""
    p = p or premissas()
    ct = p["contrato"]
    volume = float(volume or ct["creditos"])
    fk = fatores_captura(p) if fatores is None else np.asarray(fatores, dtype=float)
    forma = forma_curva(p)
    passo = 1 / 12
    tempo = np.arange(0, len(forma) + passo / 2, passo)  # meses, do ano 0 ao 40
    acum50 = np.interp(tempo, np.arange(len(forma) + 1), np.concatenate([[0.0], np.cumsum(forma)])) * credito_40_total
    acum = fk[:, None] * acum50[None, :]  # (sorteios, meses)
    tol = float(ct["tolerancia_intermediaria"])
    multa_cred, desde = float(ct["multa_credito_dia_rs"]), int(ct["multa_credito_desde_dia"])
    multa_marco = float(ct["multa_marco_dia_rs"])
    out_marcos = []
    multas = np.zeros(len(fk))
    atraso_max = np.zeros(len(fk))
    ms = ct["marcos"]
    for i, m in enumerate(ms):
        ano = int(m["ano"])
        alvo = volume * float(m["acumulado"]) / float(ct["creditos"])
        limiar = alvo if i == len(ms) - 1 else alvo * (1 - tol)
        im = int(round(ano / passo))
        no_marco = acum[:, im]
        cumpre = no_marco >= limiar
        # atraso: meses depois do marco até o acumulado chegar ao limiar (ou até o ano 40)
        depois = acum[:, im:]
        chegou = depois >= limiar
        meses = np.where(chegou.any(axis=1), np.argmax(chegou, axis=1), depois.shape[1])
        dias = meses * passo * 365
        # multa por crédito: sobre o que falta para o acumulado do marco, a partir do 181º dia
        falta = np.maximum(alvo - depois, 0.0)
        dia_mes = np.arange(depois.shape[1]) * passo * 365
        conta = (dia_mes[None, :] >= desde) & (np.arange(depois.shape[1])[None, :] < meses[:, None])
        m_cred = (falta * conta).sum(axis=1) * multa_cred * passo * 365
        m_marco = dias * multa_marco
        multas += np.where(cumpre, 0.0, m_cred + m_marco)
        atraso_max = np.maximum(atraso_max, np.where(cumpre, 0.0, dias))
        out_marcos.append({
            "ano": ano,
            "acumulado_exigido": alvo,
            "limiar_com_tolerancia": limiar,
            "acumulado_p50": float(acum50[im]),
            "chance_cumprir": float(cumpre.mean()),
            "multa_esperada_rs": float(np.where(cumpre, 0.0, m_cred + m_marco).mean()),
            "atraso_medio_dias_se_falhar": float(dias[~cumpre].mean()) if (~cumpre).any() else 0.0,
        })  # fmt: skip
    valor = volume * preco_brl_t
    resc = (multas >= float(ct["rescisao_multas_pct_valor"]) * valor) | (
        atraso_max > float(ct["rescisao_atraso_marco_dias"])
    )
    return {
        "marcos": out_marcos,
        "chance_cumprir_todos": float(np.mean([all(acum[s, int(round(int(m["ano"]) / passo))] >= (
            volume * float(m["acumulado"]) / float(ct["creditos"]) * (1 if i == len(ms) - 1 else 1 - tol))
            for i, m in enumerate(ms)) for s in range(len(fk))])),
        "multa_esperada_rs": float(multas.mean()),
        "chance_rescisao": float(resc.mean()),
        "chance_multas_acima_20pct": float((multas >= float(ct["rescisao_multas_pct_valor"]) * valor).mean()),
        "valor_contrato_rs": valor,
    }  # fmt: skip
