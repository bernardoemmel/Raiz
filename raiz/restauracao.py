"""Valor de cada fazenda para quem restaura com crédito de carbono (o desenvolvedor), por imóvel.

Calculado pelo produto, fora do motor: lê as colunas do motor pelo nome (docs/colunas.md) e as entradas geográficas de
raiz/restauracao_geo.py. A regra de pontos, os ajustes e a linha de base medida no município estão em
raiz/regras/padroes/restauracao.yaml; os números de custo, captura, descontos, receita, financiamento, contrato e
pagamento ao dono estão nas premissas da rodada 11 (motor/premissas/restauracao_v2026_11.yaml, raiz/desenvolvedor.py).
Grava desenvolvedor_<mun>.csv.

Passo a passo por imóvel:
 1. regra de pontos por faixa de distância do pasto à mata: onde a regeneração assistida vale;
 2. dois métodos disputam a fazenda: plantio total em toda a área, ou regeneração onde a regra deixa e plantio no
    resto; vence o de menor custo líquido por crédito (preço de equilíbrio);
 3. custo e captura do método com os ajustes de acesso, relevo, degradação, chuva e solo; teto do bioma;
 4. do bruto ao líquido: linha de base do cenário, vazamento (zero com área de mitigação vizinha), reserva e incerteza;
    a linha de base medida no YbYrá do município fica ao lado, para comparar;
 5. fluxo de 40 anos (entregas do ProFloresta+, venda depois do contrato, dívida limitada pelo ICSD), TIR real do
    acionista, pico de caixa, hectares por milhão de créditos e as três formas de pagar o dono;
 6. lote de fazendas vizinhas (agrupar) e, por estado, lote pelo custo líquido por crédito (raiz/desenvolvedor_lote.py).
Tudo é estimativa a calibrar com dado real de cliente (raiz/restauracao_aprendizado.py).
"""

from __future__ import annotations

import hashlib
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

from raiz import desenvolvedor as D

PADROES = Path(__file__).parent / "regras" / "padroes"
ARQ_REGRA = PADROES / "restauracao.yaml"
ARQ_CALIBRACAO = PADROES / "restauracao_calibracao.yaml"
ARQ_PREMISSAS = D.ARQ_PREMISSAS
C2CO2 = 44 / 12
RAIZ = 0.24  # raízes / parte aérea, igual ao motor
FAIXAS = ("d0", "d1", "d2", "d3")  # até 100 m, 100 a 300 m, 300 m a 1 km, acima de 1 km (limites no YAML)


# --- regra, premissas e versão --------------------------------------------------------------------------------------


@lru_cache
def _ler(regra: Path, calibracao: Path, premissas: Path, _marcas: tuple = ()) -> dict:
    textos = [regra.read_bytes(), premissas.read_bytes()]
    r = yaml.safe_load(textos[0])
    r["premissas"] = D.premissas(premissas)
    r["calibracao"] = {}
    if calibracao.exists():
        textos.append(calibracao.read_bytes())
        r["calibracao"] = yaml.safe_load(textos[2]) or {}
    h = hashlib.sha256(b"\n--\n".join(textos)).hexdigest()[:8]
    r["versao_completa"] = f"{r['versao']}+{r['premissas']['versao']}+{h}"
    return r


def _marca(p: Path) -> tuple:
    try:
        st = p.stat()
    except FileNotFoundError:
        return (str(p), None)
    return (str(p), st.st_mtime_ns, st.st_size)


def regra(regra: Path | None = None, calibracao: Path | None = None, premissas: Path | None = None) -> dict:
    """A regra (restauracao.yaml), as premissas da rodada 11 e a calibração, com versao_completa = versões + hash dos
    três. Relê quando um dos arquivos muda (a recalibração grava enquanto a API está de pé)."""
    arqs = (Path(regra or ARQ_REGRA), Path(calibracao or ARQ_CALIBRACAO), Path(premissas or ARQ_PREMISSAS))
    return _ler(*arqs, tuple(_marca(a) for a in arqs))


def versao() -> str:
    return regra()["versao_completa"]


def cenario(nome: str | None = None, r: dict | None = None, **muda) -> dict:
    """Cenário das premissas (central, estresse, otimista, so_contrato_25) com as mudanças do simulador."""
    r = r or regra()
    return D.cenario(nome, r["premissas"], **muda)


def fontes_cenario(nome: str | None = None, r: dict | None = None) -> dict[str, str]:
    r = r or regra()
    return D.fontes(r["premissas"])


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


# --- os dois métodos na fazenda -----------------------------------------------------------------------------------


def opcoes(linha: dict, m: dict | None = None, r: dict | None = None) -> dict[str, dict[str, float]]:
    """Opções da fazenda: plantio total em toda a área e, onde a regra de pontos deixa, regeneração assistida com
    plantio no resto. A área que a regra põe em semeadura direta entra como plantio (a rodada 11 não tem custo e
    captura publicados da semeadura)."""
    r = r or regra()
    m = m or modos(linha, r)
    area = m["area_ha"]
    if area > 0:
        fr = m["por_modo_ha"]["regeneracao_assistida"] / area
    else:  # sem área, o que a distância e o histórico indicariam
        fr = 1.0 if m["modo"] == "regeneracao_assistida" else 0.0
    out = {"plantio_total": {"plantio_total": 1.0}}
    if fr > 1e-9:
        out["regeneracao_assistida"] = {"regeneracao_assistida": min(fr, 1.0), "plantio_total": max(1.0 - fr, 0.0)}
    return out


def _calibracao(r: dict) -> dict[str, tuple[float, float]]:
    return {md: (_cal(r, "custo", md), _cal(r, "captura", md)) for md in D.METODOS}


def _mitigada(linha: dict) -> bool:
    return _verdade(linha.get("vazamento_mitigacao"))


def valor(linha: dict, c: dict | None = None, r: dict | None = None, m: dict | None = None,
          faixa: bool = True) -> dict:  # fmt: skip
    """Os dois métodos avaliados e o escolhido (menor custo líquido por crédito, ou o método pedido no cenário)."""
    r = r or regra()
    p = r["premissas"]
    c = c or cenario(r=r)
    m = m or modos(linha, r)
    fc, _ = fator_custo(linha, r)
    fk, _ = fator_captura(linha, r)
    cal = _calibracao(r)
    bioma = linha.get("bioma")
    alu, alu_fonte = D.aluguel_referencia(linha.get("cod_municipio_ibge"), linha.get("uf"), p)
    alu_usado = c["aluguel_rs_ha_ano"] if c["aluguel_rs_ha_ano"] is not None else alu
    mit = _mitigada(linha)
    ops = {}
    for nome, fr in opcoes(linha, m, r).items():
        op = D.opcao_por_ha(fr, bioma, c, fc, fk, cal, mit, p)
        ops[nome] = {"fracoes": fr, "op": op, "ind": D.avaliar(op, c, aluguel=alu_usado, faixa=False, p=p)}
    if c["metodo"] in ops:
        escolha = c["metodo"]
    else:
        escolha = min(ops, key=lambda k: (ops[k]["ind"]["preco_equilibrio_rs_t"], k != "regeneracao_assistida"))
    e = ops[escolha]
    if faixa:
        e["ind"] = D.avaliar(e["op"], c, aluguel=alu_usado, faixa=True, p=p)
    donos = {f: D.avaliar(e["op"], c, forma=f, aluguel=alu, faixa=False, p=p) for f in D.FORMAS_DONO}
    return {
        "opcoes": ops,
        "escolha": escolha,
        "donos": donos,
        "aluguel_ref": alu,
        "aluguel_fonte": alu_fonte,
        "aluguel_usado": alu_usado,
        "mitigacao": mit,
        "fator_custo": fc,
        "fator_captura": fk,
        "cenario": c,
    }


def custo(linha: dict, m: dict | None = None, r: dict | None = None) -> dict:
    """R$/ha P10/P50/P90 do método escolhido (implantação e manutenção dos 2 primeiros anos), com os ajustes."""
    r = r or regra()
    v = valor(linha, r=r, m=m, faixa=False)
    op = v["opcoes"][v["escolha"]]["op"]
    f, det = fator_custo(linha, r)
    return {"p10": op["custo_p10"], "p50": op["custo_total"], "p90": op["custo_p90"], "fator": f, "ajustes": det}


def captura(linha: dict, m: dict | None = None, r: dict | None = None) -> dict:
    """tCO2/ha/ano bruto (média de 40 anos) do método escolhido, P10/P50/P90 pela incerteza da captura."""
    r = r or regra()
    v = valor(linha, r=r, m=m, faixa=False)
    op = v["opcoes"][v["escolha"]]["op"]
    ic = r["premissas"]["incerteza_captura"]
    anos = int(r["premissas"]["curva"]["horizonte_anos"])
    b = op["bruto_40"] / anos
    f, det = fator_captura(linha, r)
    return {"p10": b * float(ic["p10"]), "p50": b, "p90": b * float(ic["p90"]), "fator": f, "ajustes": det}


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


def _pct(x: float | None, nd: int = 1) -> float | None:
    """Fração em %, com -100 quando a TIR não existe (o projeto não se paga)."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return -100.0
    return round(100 * x, nd)


def _arred(x: float | None, nd: int = 0) -> float | None:
    if x is None or not math.isfinite(x):
        return None
    return round(x, nd)


def por_imovel(linha: dict, c: dict | None = None, r: dict | None = None) -> dict:
    """Colunas de desenvolvedor_<mun>.csv para um imóvel (sem as do lote, que dependem dos vizinhos)."""
    r = r or regra()
    p = r["premissas"]
    c = c or cenario(r=r)
    m = modos(linha, r)
    area = m["area_ha"]
    v = valor(linha, c, r, m)
    e = v["opcoes"][v["escolha"]]
    op, ind = e["op"], e["ind"]
    anos = int(p["curva"]["horizonte_anos"])
    prazo = int(p["contrato"]["prazo_anos"])
    ic = p["incerteza_captura"]
    k10, k90 = float(ic["p10"]), float(ic["p90"])
    lb = linha_base(linha, prazo, m, r)  # medida no YbYrá do município: só para comparar
    base_t = lb["tco2_ha_ano"]
    bruto = op["bruto_40"] / anos
    liq = op["liquido_40"] / anos
    contrato_ha = op["liquido_40"] * D.fracao_ate(prazo, p)
    teto, publicado, bioma_usado = D.teto_bioma(linha.get("bioma"), p)
    plano = {md: area * e["fracoes"].get(md, 0.0) for md in r["modos"]}
    lb_medida_pct = round(100 * base_t / bruto, 1) if bruto > 0 else 0.0
    out = {
        "restauracao_area_ha": round(area, 4),
        "modo_restauracao": v["escolha"],
        "modo_pela_regra": m["modo"],
        "modo_restauracao_pontos": m["pontos_imovel"],
        "modo_restauracao_regra": "; ".join(
            f"{x['faixa']} {x['fracao']:.0%} {x['pontos']} pts {x['modo']}" for x in m["faixas"] if x["fracao"] > 0
        ),
        **{f"restauracao_{md}_ha": round(plano[md], 4) for md in r["modos"]},
        "distancia_fonte": m["distancia_fonte"],
        "custo_restauracao_ha_p10": round(op["custo_p10"], 0),
        "custo_restauracao_ha_p50": round(op["custo_total"], 0),
        "custo_restauracao_ha_p90": round(op["custo_p90"], 0),
        "custo_fator_ajuste": round(v["fator_custo"], 4),
        "captura_tco2_ha_ano_p10": round(bruto * k10, 2),
        "captura_tco2_ha_ano_p50": round(bruto, 2),
        "captura_tco2_ha_ano_p90": round(bruto * k90, 2),
        "captura_fator_ajuste": round(v["fator_captura"], 4),
        "teto_bioma_tco2_ha": teto,
        "teto_bioma_publicado": publicado,
        "bioma_usado": bioma_usado,
        "desconto_linha_base": round(base_t, 3),
        "desconto_linha_base_pct": lb_medida_pct,
        "linha_base_regenera_pct": round(100 * lb["regenera_ate_o_fim"], 1),
        "linha_base_fonte": lb["fonte"],
        "linha_base_cenario_pct": round(100 * c["linha_base"], 1),
        "linha_base_medida_acima": lb_medida_pct > 100 * c["linha_base"],
        "vazamento_pct": round(100 * (c["vazamento_com_mitigacao"] if v["mitigacao"] else c["vazamento"]), 1),
        "vazamento_mitigacao": v["mitigacao"],
        "vazamento_mitigacao_imovel": linha.get("vazamento_mitigacao_imovel"),
        "vazamento_motivo": linha.get("vazamento_motivo") or ("mitigacao_vizinha" if v["mitigacao"] else "cenario"),
        "cabecas_deslocadas": linha.get("cabecas_deslocadas"),
        "rebanho_fonte": linha.get("rebanho_fonte"),
        "fator_liquido": round(op["fator_liquido"], 4),
        "credito_liquido_tco2_ha_ano": round(liq, 3),
        "credito_liquido_tco2_ha_ano_p10": round(liq * k10, 3),
        "credito_liquido_tco2_ha_ano_p90": round(liq * k90, 3),
        "credito_liquido_tco2_ano": round(liq * area, 1),
        "credito_liquido_t": round(op["liquido_40"] * area, 0),
        "credito_liquido_contrato_t": round(contrato_ha * area, 0),
        "custo_liquido_por_credito": _arred(ind["preco_equilibrio_rs_t"], 2),
        "custo_liquido_por_credito_usd": _arred(ind["preco_equilibrio_rs_t"] / c["cambio_brl_usd"], 2),
        "custo_liquido_por_credito_p10": _arred(ind.get("preco_equilibrio_rs_t_p10"), 2),
        "custo_liquido_por_credito_p90": _arred(ind.get("preco_equilibrio_rs_t_p90"), 2),
        "vpl_rs_ha_p10": round(min(ind["vpl_rs_ha_p10"], ind["vpl_rs_ha"]), 0),
        "vpl_rs_ha_p50": round(ind["vpl_rs_ha"], 0),
        "vpl_rs_ha_p90": round(max(ind["vpl_rs_ha_p90"], ind["vpl_rs_ha"]), 0),
        "tir_projeto_pct_p10": min(_pct(ind["tir_projeto_p10"]), _pct(ind["tir_projeto"])),
        "tir_projeto_pct_p50": _pct(ind["tir_projeto"]),
        "tir_projeto_pct_p90": max(_pct(ind["tir_projeto_p90"]), _pct(ind["tir_projeto"])),
        "tir_alavancada_pct_p10": min(_pct(ind["tir_acionista_p10"]), _pct(ind["tir_acionista"])),
        "tir_alavancada_pct_p50": _pct(ind["tir_acionista"]),
        "tir_alavancada_pct_p90": max(_pct(ind["tir_acionista_p90"]), _pct(ind["tir_acionista"])),
        "tir_desenvolvedor": _pct(ind["tir_acionista"]),
        "pico_capital_proprio_rs_ha_p10": round(min(ind["pico_caixa_rs_ha_p10"], ind["pico_caixa_rs_ha"]), 0),
        "pico_capital_proprio_rs_ha_p50": round(ind["pico_caixa_rs_ha"], 0),
        "pico_capital_proprio_rs_ha_p90": round(max(ind["pico_caixa_rs_ha_p90"], ind["pico_caixa_rs_ha"]), 0),
        "pico_caixa_ha": round(ind["pico_caixa_rs_ha"], 0),
        "fracao_divida": round(ind["fracao_divida"], 3),
        "icsd_minimo": _arred(ind["icsd_min"], 2),
        "valor_desenvolvedor_rs": round(ind["vpl_rs_ha"] * area, 0),
        "ha_por_milhao_volume": _arred(D.ha_por_milhao(op["liquido_40"], p), 0),
        "ha_por_milhao_marcos": _arred(D.ha_por_milhao(op["liquido_40"], p, marcos_todos=True), 0),
    }
    for md, curto in (("plantio_total", "plantio"), ("regeneracao_assistida", "regeneracao")):
        o = v["opcoes"].get(md)
        out[f"metodo_{curto}_tir_pct"] = _pct(o["ind"]["tir_acionista"]) if o else None
        out[f"metodo_{curto}_custo_credito"] = _arred(o["ind"]["preco_equilibrio_rs_t"], 2) if o else None
    d = v["donos"]
    forma = c["forma_dono"]
    if forma == "aluguel_fixo":
        texto = f"aluguel fixo de R$ {v['aluguel_usado']:.0f}/ha/ano por {c['prazo_dono_anos']} anos"
    else:
        texto = (f"{100 * c['parte_dono']:.0f}% do crédito mais piso de R$ {c['piso_dono_rs_ha_ano']:.0f}/ha/ano por "
                 f"{c['prazo_dono_anos']} anos")  # fmt: skip
        if forma == "duas_fases":
            texto = f"opção de R$ {c['opcao_rs_ha_mes']:.0f}/ha/mês até o leilão, depois " + texto
    out.update({
        "caminho_terra": linha.get("caminho_terra"),
        "caminho_terra_situacao": linha.get("caminho_terra_situacao"),
        "risco_terra": linha.get("risco_terra"),
        "projeto_carbono_ha": _num(linha, "projeto_carbono_ha"),
        "pagamento_dono": f"{forma}: {texto}",
        "pagamento_dono_rs_ha_ano": round(d[forma]["dono_rs_ha_ano_medio"], 0),
        "aluguel_referencia_rs_ha_ano": v["aluguel_ref"],
        "aluguel_referencia_fonte": v["aluguel_fonte"],
        "tir_desenvolvedor_dono_parte": _pct(d["parte_credito"]["tir_acionista"]),
        "tir_desenvolvedor_dono_aluguel": _pct(d["aluguel_fixo"]["tir_acionista"]),
        "tir_desenvolvedor_dono_duas_fases": _pct(d["duas_fases"]["tir_acionista"]),
        "restauracao_faltou": ",".join(faltou(linha)),
        "restauracao_cenario": c["cenario"],
        "restauracao_versao": r["versao_completa"],
    })  # fmt: skip
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
    # já está em projeto de carbono registrado: a mesma área não entra em dois projetos (VM0047)
    if (_num(linha, "projeto_carbono_ha") or 0.0) >= 1.0:
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


def colunas_do_lote(df, cod_municipio: int, c: dict | None = None, r: dict | None = None):
    """Soma por lote de vizinhas: imóveis, ha, crédito por ano, créditos no contrato e se fecha o contrato."""
    r = r or regra()
    p = r["premissas"]
    alvo = float(p["contrato"]["creditos"])
    prazo = int(p["contrato"]["prazo_anos"])
    g = df[df.grupo_id.notna()].groupby("grupo_id")
    soma = g.agg(
        grupo_imoveis=("cod_imovel", "count"),
        grupo_ha=("restauracao_area_ha", "sum"),
        grupo_credito_tco2_ano=("credito_liquido_tco2_ano", "sum"),
    )
    if "credito_liquido_contrato_t" in df:
        soma["grupo_creditos_prazo"] = g["credito_liquido_contrato_t"].sum()
    else:
        soma["grupo_creditos_prazo"] = soma.grupo_credito_tco2_ano * prazo
    soma["grupo_fecha_contrato"] = soma.grupo_creditos_prazo >= alvo
    taxa = (soma.grupo_creditos_prazo / soma.grupo_ha).where(soma.grupo_ha > 0)
    soma["grupo_ha_para_contrato"] = (alvo / taxa).where(taxa > 0)
    casas = {"grupo_ha": 2, "grupo_credito_tco2_ano": 1, "grupo_creditos_prazo": 0, "grupo_ha_para_contrato": 0}
    soma = soma.round(casas)
    return df.merge(soma, left_on="grupo_id", right_index=True, how="left")


# --- por município (saida/<UF>/desenvolvedor_<mun>.csv) ----------------------------------------------------------

ENTRADAS = ("filtros", "mapbiomas", "extras", "direto", "ficha", "terra")
COLS_FICHA = ("estrada_acesso_km", "cidade_proxima_km")
COLS_TERRA = ("caminho_terra", "caminho_terra_situacao", "risco_terra", "profloresta_fase1")


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
                extra = extra[[c for c in extra.columns if c == "cod_imovel" or c in COLS_TERRA]]
            novas = [c for c in extra.columns if c == "cod_imovel" or c not in im.columns]
            im = im.merge(extra[novas].drop_duplicates("cod_imovel"), on="cod_imovel", how="left")
    im["cod_imovel"] = im.cod_imovel.astype(str)
    if "cod_municipio_ibge" not in im:
        im["cod_municipio_ibge"] = cod
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
    from raiz import vazamento as V

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
        pontos = {str(c_): (float(p.x), float(p.y)) for c_, p in zip(g4326.cod_imovel, pts, strict=True)}
        if fontes_geo:
            uf = pasta.name.upper()
            cob = sorted((Path(cache_motor) / "mapbiomas" / uf).glob(f"{uf}_cobertura_2*.tif")) if cache_motor else []
            cob = [f for f in cob if f.stem.count("_") == 2]  # PA_cobertura_2025.tif (não as séries por ano)
            por, mun = G.entradas_municipio(geo, cod, cob[-1] if cob else None, cache, fontes_geo)
            mun.pop("pontos", None)
    registros = []
    for linha in im.to_dict("records"):
        cod_im = linha["cod_imovel"]
        registros.append({**linha, **por.get(cod_im, {}),
                          **{k: v for k, v in mun.items() if k.startswith("linha_base_")}})  # fmt: skip
    # vazamento (VMD0054): área de mitigação vizinha que recebe o gado; achou, o vazamento vai a zero
    mit = V.mitigacoes(registros, pontos, r["premissas"], area_de=area_restauravel, elegivel=elegivel)
    linhas = []
    for linha in registros:
        cod_im = linha["cod_imovel"]
        linha = {**linha, **mit.get(cod_im, {})}
        calc = por_imovel(linha, c, r)
        geo_cols = {k: por.get(cod_im, {}).get(k) for k in (
            "pasto_d0_ha", "pasto_d1_ha", "pasto_d2_ha", "pasto_d3_ha",
            "declividade_media_pct", "chuva_mm_ano", "solo_cec_cmolc_kg")}  # fmt: skip
        linhas.append({"cod_imovel": cod_im, **geo_cols, **calc, "_elegivel": elegivel(linha)})
    df = pd.DataFrame(linhas)
    for f in FAIXAS:
        df[f"linha_base_taxa_{f}"] = mun.get(f"linha_base_taxa_{f}")
    # lote de vizinhas: só quem pode entrar e tem ponto no mapa
    eleg = [(cd, *pontos[cd]) for cd, ok in zip(df.cod_imovel, df._elegivel, strict=True) if ok and cd in pontos]
    rot = agrupar(eleg, r)
    df["grupo_id"] = [f"{cod}-{rot[cd]:04d}" if cd in rot else None for cd in df.cod_imovel]
    df["elegivel_lote"] = df["_elegivel"]
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
    "linha_base_municipio": "linha de base medida no município (YbYrá): usada a taxa padrão para comparar",
}
CENARIO_EDITAVEL = D.EDITAVEIS
# nomes do simulador anterior (cenarios-2026a) que ainda valem, com o nome novo
ANTIGOS = {"preco_usd_t": "preco_contrato_usd_t", "taxa_desconto": "taxa_desconto",
           "fracao_financiada": "fracao_financiada", "juros_ano": "juros_ano", "carencia_anos": "carencia_anos",
           "cambio_brl_usd": "cambio_brl_usd"}  # fmt: skip
ANTIGOS_SEM_USO = ("prazo_anos", "entregas_anos", "amortizacao_anos", "sistema_amortizacao", "manutencao_rs_ha_ano",
                   "monitoramento_rs_ha_ano", "verificacao_rs_ha_entrega", "taxa_registro_usd_t", "tributos_receita",
                   "manutencao_desde_ano")  # fmt: skip


def _faixa(linha: dict, base: str, nd: int = 1) -> dict | None:
    v = {q: _num(linha, f"{base}_{q}") for q in ("p10", "p50", "p90")}
    if v["p50"] is None:
        return None
    return {q: (round(x, nd) if x is not None else None) for q, x in v.items()}


def _cenario_da_linha(linha: dict, r: dict) -> dict:
    nome = linha.get("restauracao_cenario")
    return cenario(nome if nome in r["premissas"]["cenarios"] else None, r)


def bloco_ficha(linha: dict, r: dict | None = None) -> dict:
    """Bloco "Para quem restaura" da ficha, a partir das colunas de desenvolvedor_<mun>.csv já carregadas."""
    r = r or regra()
    p = r["premissas"]
    modo = linha.get("modo_restauracao")
    if not isinstance(modo, str) or modo not in r["modos"]:
        return {
            "disponivel": False,
            "mensagem": "O valor para quem restaura ainda não foi calculado para este município.",
            "aviso": p["aviso"],
        }
    c = _cenario_da_linha(linha, r)
    area = _num(linha, "restauracao_area_ha") or 0.0
    fl = [x for x in str(linha.get("restauracao_faltou") or "").split(",") if x]
    medida = _num(linha, "desconto_linha_base_pct") or 0.0
    regenera = _num(linha, "linha_base_regenera_pct") or 0.0
    lb_cen = _num(linha, "linha_base_cenario_pct")
    lb_cen = 100 * c["linha_base"] if lb_cen is None else lb_cen
    vaz = _num(linha, "vazamento_pct")
    vaz = 100 * c["vazamento"] if vaz is None else vaz
    mit = _verdade(linha.get("vazamento_mitigacao"))
    cred = {
        "p10": _num(linha, "credito_liquido_tco2_ha_ano_p10"),
        "p50": _num(linha, "credito_liquido_tco2_ha_ano"),
        "p90": _num(linha, "credito_liquido_tco2_ha_ano_p90"),
    }
    grupo = linha.get("grupo_id")
    tem_grupo = isinstance(grupo, str) and bool(grupo)
    explic = (f"A conta desconta {lb_cen:.0f}% de linha de base (premissa do cenário). No YbYrá do município, cerca de "
              f"{regenera:.0f}% deste pasto viraria mata sozinho em {p['contrato']['prazo_anos']} anos, o que daria "
              f"{medida:.0f}% da captura.")  # fmt: skip
    if medida > lb_cen:
        explic += " A medida passa da premissa: o crédito desta fazenda pode ser menor que o mostrado."
    return {
        "disponivel": True,
        "aviso": p["aviso"],
        "versao": linha.get("restauracao_versao"),
        "area_ha": round(area, 2),
        "area_regra": r["area"]["regra"],
        "modo": {
            "id": modo,
            "nome": r["nomes_modos"][modo],
            "pela_regra": linha.get("modo_pela_regra"),
            "pontos_imovel": _num(linha, "modo_restauracao_pontos"),
            "por_faixa": linha.get("modo_restauracao_regra"),
            "por_modo_ha": {md: _num(linha, f"restauracao_{md}_ha") for md in r["modos"]},
            "regra": r["regra_modo"]["texto"],
            "escolha": "vence o método de menor custo líquido por crédito; a regeneração só onde a regra deixa",
        },
        "metodos": {
            "plantio_total": {
                "tir_pct": _num(linha, "metodo_plantio_tir_pct"),
                "custo_liquido_por_credito": _num(linha, "metodo_plantio_custo_credito"),
            },
            "regeneracao_assistida": {
                "tir_pct": _num(linha, "metodo_regeneracao_tir_pct"),
                "custo_liquido_por_credito": _num(linha, "metodo_regeneracao_custo_credito"),
            },
        },  # fmt: skip
        "custo_rs_ha": {
            **(_faixa(linha, "custo_restauracao_ha", 0) or {}),
            "fator_ajuste": _num(linha, "custo_fator_ajuste"),
        },  # fmt: skip
        "captura_tco2_ha_ano": {
            **(_faixa(linha, "captura_tco2_ha_ano", 2) or {}),
            "fator_ajuste": _num(linha, "captura_fator_ajuste"),
            "teto_bioma_tco2_ha": _num(linha, "teto_bioma_tco2_ha"),
            "teto_bioma_publicado": _verdade(linha.get("teto_bioma_publicado")),
        },  # fmt: skip
        "linha_base": {
            "cenario_pct": lb_cen,
            "desconto_tco2_ha_ano": _num(linha, "desconto_linha_base"),
            "desconto_pct_da_captura": medida,
            "regenera_sozinha_ate_o_fim_pct": regenera,
            "medida_acima_da_premissa": medida > lb_cen,
            "fonte": linha.get("linha_base_fonte"),
            "metodo": r["linha_base"]["metodo"],
            "explicacao": explic,
        },
        "credito_liquido_tco2_ha_ano": cred,
        "credito_liquido_tco2_ano": _num(linha, "credito_liquido_tco2_ano"),
        "credito_liquido_t": _num(linha, "credito_liquido_t"),
        "credito_liquido_contrato_t": _num(linha, "credito_liquido_contrato_t"),
        "custo_liquido_por_credito": {
            "p10": _num(linha, "custo_liquido_por_credito_p10"),
            "p50": _num(linha, "custo_liquido_por_credito"),
            "p90": _num(linha, "custo_liquido_por_credito_p90"),
            "usd_p50": _num(linha, "custo_liquido_por_credito_usd"),
        },
        "do_bruto_ao_liquido": {
            "ordem": p["descontos"]["ordem"],
            "linha_base": lb_cen / 100,
            "vazamento": vaz / 100,
            "reserva_risco": c["reserva_risco"],
            "incerteza": c["incerteza"],
            "fator_liquido": _num(linha, "fator_liquido"),
            "vazamento_situacao": (
                f"zero: área de mitigação vizinha ({linha.get('vazamento_mitigacao_imovel')}) recebe o gado"
                if mit
                else f"{vaz:.0f}% do cenário: nenhuma vizinha com pasto para receber o gado foi achada"
            ),
        },
        "vpl_rs_ha": _faixa(linha, "vpl_rs_ha", 0),
        "tir_projeto_pct": _faixa(linha, "tir_projeto_pct", 1),
        "tir_alavancada_pct": _faixa(linha, "tir_alavancada_pct", 1),
        "pico_capital_proprio_rs_ha": _faixa(linha, "pico_capital_proprio_rs_ha", 0),
        "valor_desenvolvedor_rs": _num(linha, "valor_desenvolvedor_rs"),
        "financiamento": {
            "fracao_divida": _num(linha, "fracao_divida"),
            "icsd_minimo": _num(linha, "icsd_minimo"),
            "icsd_exigido": c["icsd_minimo"],
        },  # fmt: skip
        "contrato": {
            "ha_por_milhao_volume": _num(linha, "ha_por_milhao_volume"),
            "ha_por_milhao_marcos": _num(linha, "ha_por_milhao_marcos"),
            "marcos": [dict(m) for m in p["contrato"]["marcos"]],
            "tolerancia": p["contrato"]["tolerancia_intermediaria"],
        },
        "dono": {
            "padrao": linha.get("pagamento_dono"),
            "rs_ha_ano": _num(linha, "pagamento_dono_rs_ha_ano"),
            "prazo_anos": c["prazo_dono_anos"],
            "aluguel_referencia_rs_ha_ano": _num(linha, "aluguel_referencia_rs_ha_ano"),
            "aluguel_referencia_fonte": linha.get("aluguel_referencia_fonte"),
            "tir_por_forma_pct": {
                "parte_credito": _num(linha, "tir_desenvolvedor_dono_parte"),
                "aluguel_fixo": _num(linha, "tir_desenvolvedor_dono_aluguel"),
                "duas_fases": _num(linha, "tir_desenvolvedor_dono_duas_fases"),
            },
        },  # fmt: skip
        "terra": {"caminho": linha.get("caminho_terra")},
        "cenario": {k: c[k] for k in ("cenario", "nome", *CENARIO_EDITAVEL) if k in c},
        "lote": {
            "grupo_id": grupo,
            "imoveis": _num(linha, "grupo_imoveis"),
            "ha": _num(linha, "grupo_ha"),
            "credito_tco2_ano": _num(linha, "grupo_credito_tco2_ano"),
            "creditos_no_prazo": _num(linha, "grupo_creditos_prazo"),
            "fecha_contrato": _verdade(linha.get("grupo_fecha_contrato")),
            "contrato_creditos": p["contrato"]["creditos"],
            "ha_para_contrato": _num(linha, "grupo_ha_para_contrato"),
        }
        if tem_grupo
        else None,
        "faltou": [{"id": x, "texto": TEXTO_FALTOU.get(x, x)} for x in fl],
        "premissas": {
            "versao": p["versao_completa"],
            **D.fontes(p),
            "modo": r["regra_modo"]["fonte"],
            "linha_base_medida": r["linha_base"]["fonte"],
        },  # fmt: skip
    }


def simular(linha: dict, nome_cenario: str | None = None, r: dict | None = None, **muda) -> dict:
    """Simulador da ficha: refaz o imóvel com o cenário e os parâmetros editados, com o fluxo ano a ano (P50)."""
    r = r or regra()
    if nome_cenario is None:
        nome_cenario = _cenario_da_linha(linha, r)["cenario"]
    c = cenario(nome_cenario, r, **muda)
    calc = por_imovel(linha, c, r)
    v = valor(linha, c, r, faixa=False)
    e = v["opcoes"][v["escolha"]]
    bloco = bloco_ficha({**linha, **calc}, r)
    bloco["cenario"] = {k: c[k] for k in ("cenario", "nome", *CENARIO_EDITAVEL) if k in c}
    bloco["fluxo_p50"] = {
        "anos": list(range(len(e["ind"]["fluxo_projeto"]))),
        "projeto_rs_ha": [round(float(x), 2) for x in e["ind"]["fluxo_projeto"]],
        "com_financiamento_rs_ha": [round(float(x), 2) for x in e["ind"]["fluxo_acionista"]],
    }
    return bloco


ORDENS = {
    "valor_desenvolvedor": "valor_desenvolvedor_rs",
    "vpl_ha": "vpl_rs_ha_p50",
    "tir_alavancada": "tir_alavancada_pct_p50",
    "credito": "credito_liquido_tco2_ano",
    "custo_credito": "custo_liquido_por_credito",
}
ORDENS_CRESCENTE = ("custo_credito",)  # menor primeiro
_INTEIROS = ("carencia_anos",)
_LIMITES = {
    "preco_contrato_usd_t": (0.01, 1000), "venda_apos_contrato_usd_t": (0, 1000), "cambio_brl_usd": (0.01, 100),
    "taxa_desconto": (0, 1), "fracao_financiada": (0, 1), "juros_ano": (0, 1), "carencia_anos": (0, 24),
    "icsd_minimo": (0, 10), "linha_base": (0, 0.95), "vazamento": (0, 0.95), "reserva_risco": (0, 0.95),
    "incerteza": (0, 0.95), "taxa_registro": (0, 0.9), "manutencao_usd_ha_ano": (0, 1e4), "parte_dono": (0, 0.9),
    "piso_dono_rs_ha_ano": (0, 1e5), "aluguel_rs_ha_ano": (0, 1e5),
}  # fmt: skip


def parametros_da_consulta(q: dict[str, str]) -> tuple[str | None, dict]:
    """Lê os parâmetros do simulador da URL (cenário e campos editáveis), com limites. Aceita os nomes do simulador
    anterior que continuam valendo (preco_usd_t, juros_ano...); arrendamento_rs_ha_ano vira aluguel fixo ao dono."""
    q = dict(q)
    nome = q.pop("cenario", None) or None
    if nome is not None and nome not in regra()["premissas"]["cenarios"]:
        raise ValueError(f"cenário desconhecido: {nome}")
    muda: dict = {}
    for k, v in q.items():
        if k in ANTIGOS_SEM_USO:
            raise ValueError(f"{k}: parâmetro do simulador anterior que não vale mais (o contrato e a dívida seguem as "
                             "premissas da rodada 11)")  # fmt: skip
        if k == "arrendamento_rs_ha_ano":
            muda["forma_dono"] = "aluguel_fixo"
            k = "aluguel_rs_ha_ano"
        k = ANTIGOS.get(k, k)
        if k not in CENARIO_EDITAVEL:
            raise ValueError(f"parâmetro desconhecido: {k}")
        if k == "forma_dono":
            if v not in D.FORMAS_DONO:
                raise ValueError(f"forma_dono: {', '.join(D.FORMAS_DONO)}")
            muda[k] = v
        elif k == "metodo":
            if v not in ("auto", *D.METODOS):
                raise ValueError(f"metodo: auto, {', '.join(D.METODOS)}")
            muda[k] = v
        elif k == "venda_apos_contrato":
            muda[k] = str(v).strip().lower() in ("1", "true", "sim", "t")
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
    p = r["premissas"]
    out = {}
    for nome in p["cenarios"]:
        c = cenario(nome, r)
        out[nome] = {"nome": c["nome"], "parametros": {k: c[k] for k in CENARIO_EDITAVEL if k in c}}
    return {"padrao": p["padrao"], "versao": versao(), "cenarios": out, "editaveis": list(CENARIO_EDITAVEL),
            "fontes": D.fontes(p), "aviso": p["aviso"]}  # fmt: skip


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
        sinal = 1.0 if ordem in ORDENS_CRESCENTE else -1.0
        out = sorted(out, key=lambda x: (_num(x, col) is None, sinal * (_num(x, col) or 0.0)))
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
