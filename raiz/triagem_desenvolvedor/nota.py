"""Nota 0 a 100 de uma fazenda para o desenvolvedor de restauração, com o motivo (regra em
raiz/regras/padroes/triagem_desenvolvedor.yaml). Colunas lidas pelo nome (docs/colunas.md), tolerando as que faltam.

A nota junta custo por crédito, TIR, crédito líquido P50 por ha e a terra. Embargo, terra indígena, UC de proteção
integral, desmatamento ou alerta recente, projeto já existente (ja_comprometida) e caminho que não origina não tiram a
fazenda da lista: travam a nota em nota_max e põem a fazenda em "nao_segue", com o motivo. Fazenda pequena entra como
qualquer outra (nunca é descartada por tamanho). Nada pessoal: só código do CAR e números.
"""

from __future__ import annotations

import hashlib
import math
from functools import lru_cache
from pathlib import Path

import yaml

from raiz.agentes.textos import num

ARQ = Path(__file__).resolve().parents[1] / "regras" / "padroes" / "triagem_desenvolvedor.yaml"
FAIXAS = ("recomendada", "com_ressalvas", "nao_segue", "sem_dados", "nao_encontrada")
CAMINHOS = {
    "privada_matricula": "privada com matrícula",
    "publica_concessao": "concessão pública",
    "assentamento": "assentamento",
    "posse_em_titulacao": "posse em titulação",
    "publica_sem_destinacao": "terra pública sem destinação",
    "terra_indigena_ou_tradicional": "terra indígena ou tradicional",
}


@lru_cache
def _ler(arq: Path, _marca: tuple) -> dict:
    texto = arq.read_bytes()
    r = yaml.safe_load(texto)
    r["versao_completa"] = f"{r['versao']}+{hashlib.sha256(texto).hexdigest()[:8]}"
    return r


def regra(arq: Path | None = None) -> dict:
    a = Path(arq or ARQ)
    return _ler(a, (str(a), a.stat().st_mtime_ns, a.stat().st_size))


def versao() -> str:
    return regra()["versao_completa"]


def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _s(v) -> str | None:
    return v if isinstance(v, str) and v.strip() else None


def _escala(x: float, melhor: float, pior: float) -> float:
    """1 na ponta melhor, 0 na pior, linha reta no meio (serve para os dois sentidos)."""
    return max(0.0, min(1.0, (x - pior) / (melhor - pior)))


def valores(linha: dict) -> dict:
    """Os números da fazenda, com a mesma conta da oferta (raiz/pedidos/oferta.py)."""
    c50 = _num(linha.get("credito_liquido_tco2_ha_contrato_p50"))
    if c50 is None:
        anual = _num(linha.get("credito_liquido_tco2_ha_ano"))
        c50 = anual * 25 if anual is not None else None
    tir = _num(linha.get("tir_alavancada_pct_p50"))
    if tir is None:
        tir = _num(linha.get("tir_projeto_pct_p50"))
    mf = _num(linha.get("m_fiscal"))
    porte = linha.get("porte")
    return {
        "ha": _num(linha.get("ha")) or _num(linha.get("area")),
        "pequena": porte == "pequeno" if isinstance(porte, str) else (None if mf is None else mf <= 4),
        "restauracao_area_ha": _num(linha.get("restauracao_area_ha")),
        "credito_p50_tco2_ha": c50,
        "custo_credito_usd": _num(linha.get("custo_credito_usd")),
        "tir_pct": tir,
        "caminho_terra": _s(linha.get("caminho_terra")),
        "risco_terra": _s(linha.get("risco_terra")),
        "status_sobreposicao": _s(linha.get("status_sobreposicao")) or "nao_verificado",
        "projeto_id": _s(linha.get("projeto_id")),
    }


def avaliar(linha: dict, r: dict | None = None) -> dict:
    """Uma linha do ranking (sem a posição): nota, faixa, os números e o motivo."""
    r = r or regra()
    v = valores(linha)
    P, F = r["pesos"], r["faixas"]
    partes: dict[str, tuple[float, str]] = {}
    if v["custo_credito_usd"] is not None:
        f = F["custo_credito_usd"]
        partes["custo"] = (_escala(v["custo_credito_usd"], f["melhor"], f["pior"]),
                           f"custo US$ {num(v['custo_credito_usd'], 2)} por crédito")  # fmt: skip
    if v["tir_pct"] is not None:
        f = F["tir_pct"]
        partes["tir"] = (_escala(v["tir_pct"], f["melhor"], f["pior"]), f"TIR {num(v['tir_pct'], 1)}%")
    if v["credito_p50_tco2_ha"] is not None:
        f = F["credito_tco2_ha"]
        partes["credito"] = (_escala(v["credito_p50_tco2_ha"], f["melhor"], f["pior"]),
                             f"crédito P50 de {num(v['credito_p50_tco2_ha'], 0)} t/ha")  # fmt: skip
    cam = CAMINHOS.get(v["caminho_terra"] or "", (v["caminho_terra"] or "sem caminho").replace("_", " "))
    if v["caminho_terra"] is not None or v["risco_terra"] is not None:
        t = r["terra"].get(v["risco_terra"] or "", r["terra"]["sem_risco"])
        partes["terra"] = (t, f"terra {cam}, risco {v['risco_terra'] or 'não calculado'}")
    trava, ressalvas = [], []
    for col, nome in r["travas"]["areas_ha"].items():
        x = _num(linha.get(col))
        if x is not None and x > 0:
            trava.append(f"{nome} em {num(x, 1)} ha")
    if v["caminho_terra"] in r["travas"]["caminhos_que_nao_originam"]:
        trava.append(f"caminho da terra não origina ({cam})")
    if v["status_sobreposicao"] == "ja_comprometida":
        ref = f" ({v['projeto_id']})" if v["projeto_id"] else ""
        trava.append(f"já está em projeto ou concessão{ref}")
    texto_res = r["ressalvas"]["status_sobreposicao"].get(v["status_sobreposicao"])
    if texto_res:
        ressalvas.append(texto_res)
    peso = sum(P[k] for k in partes)
    sem_numeros = "custo" not in partes and "credito" not in partes
    nota = None if not peso or sem_numeros else 100 * sum(P[k] * partes[k][0] for k in partes) / peso
    if nota is not None and trava:
        nota = min(nota, r["travas"]["nota_max"])
    if trava:
        faixa = "nao_segue"
    elif nota is None:
        faixa = "sem_dados"
    elif nota >= r["faixas_nota"]["recomendada"] and not ressalvas:
        faixa = "recomendada"
    else:
        faixa = "com_ressalvas"
    pedacos = [f"{t} (parte {num(s, 2)})" for s, t in partes.values()]
    faltam = [n for n in ("custo", "tir", "credito") if n not in partes]
    if faltam:
        pedacos.append("sem " + ", ".join({"custo": "custo", "tir": "TIR", "credito": "crédito"}[n] for n in faltam))
    if v["status_sobreposicao"] == "nao_verificado":
        pedacos.append("sobreposição com projetos não verificada")
    motivo = "; ".join(pedacos)
    if trava:
        motivo += ". Trava: " + "; ".join(trava)
    if ressalvas:
        motivo += ". Ressalva: " + "; ".join(ressalvas)
    ti = (_num(linha.get("ti_ha")) or 0) > 0 or (_num(linha.get("ti_funai_ha")) or 0) > 0
    uc = (_num(linha.get("uc_protecao_integral_ha")) or 0) > 0
    ti_uc = ", ".join(x for x, ativo in (("terra indígena", ti), ("UC de proteção integral", uc)) if ativo) or None
    return {
        **v,
        "nota": None if nota is None else round(nota, 1),
        "faixa": faixa,
        "embargo_ha": _num(linha.get("embargo_ha")),
        "ti_uc": ti_uc,
        "desmatamento_recente_ha": _num(linha.get("desm_pos2020_ha")),
        "alerta_recente_ha": _num(linha.get("alerta_ultimo_ano")),
        "motivo": motivo,
    }
