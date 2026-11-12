"""Nota de cada previsão contra o gabarito e o placar por modelo, versão e alvo (E7 passo 5, painel de acerto).

Notas (quanto menor, melhor, menos cobertura e acerto):
    faixa P10/P50/P90     WIS (weighted interval score) com o intervalo de 80% e a mediana, erro absoluto da mediana
                          e cobertura do intervalo de 80% (devia ficar perto de 80%)
    número                erro absoluto e erro quadrático
    chance (0 a 1)        nota de Brier e log score; a chance é de o resultado ser verdadeiro
    categoria             acerto e nota de Brier da categoria (0 quando acerta, 2 quando erra)

O WIS segue Bracher et al. (2021, PLOS Comput Biol), com K = 1 intervalo (alfa = 0,2):
    WIS = (0,5 |y - m| + (alfa/2) IS_alfa) / (K + 0,5),   IS_alfa = (u - l) + (2/alfa)(l - y)+ + (2/alfa)(y - u)+
Fórmulas reescritas, sem copiar código.
"""

from __future__ import annotations

import math
from collections import defaultdict

ALFA = 0.2  # P10 a P90
VERDADE = {"1", "1.0", "true", "verdadeiro", "sim", "aceito", "aceitou", "t"}
# alvos cujo valor_num é a chance (0 a 1) de o resultado ser verdadeiro
PROBABILIDADE = {"aceite_dono"}


def e_probabilidade(alvo: str) -> bool:
    return alvo in PROBABILIDADE or str(alvo).startswith("vigilancia_")


def _verdade(real_num, real_texto) -> int | None:
    if real_num is not None and real_num == real_num:
        return 1 if float(real_num) >= 0.5 else 0
    if real_texto is not None:
        return 1 if str(real_texto).strip().lower() in VERDADE else 0
    return None


def wis(y: float, p10: float, p50: float, p90: float, alfa: float = ALFA) -> float:
    lo, hi = min(p10, p90), max(p10, p90)
    intervalo = (hi - lo) + (2 / alfa) * max(lo - y, 0.0) + (2 / alfa) * max(y - hi, 0.0)
    return (0.5 * abs(y - p50) + (alfa / 2) * intervalo) / 1.5


def nota(r: dict) -> dict | None:
    """Nota de uma linha previsão contra gabarito (chaves da visão aprendizado.previsao_contra_gabarito)."""
    alvo = r["alvo"]
    y_num, y_txt = r.get("real_num"), r.get("real_texto")
    if y_num is None and y_txt is None:
        return None
    p10, p50, p90 = r.get("p10"), r.get("p50"), r.get("p90")
    vn, vt = r.get("valor_num"), r.get("valor_texto")
    if e_probabilidade(alvo) and vn is not None:
        y = _verdade(y_num, y_txt)
        p = min(max(float(vn), 0.0), 1.0)
        return {
            "tipo": "chance",
            "brier": (p - y) ** 2,
            "log_score": -math.log(max(p if y else 1 - p, 1e-6)),
            "acerto": int((p >= 0.5) == bool(y)),
        }
    if p10 is not None and p50 is not None and p90 is not None and y_num is not None:
        y = float(y_num)
        return {
            "tipo": "faixa",
            "wis": wis(y, float(p10), float(p50), float(p90)),
            "ae_mediana": abs(y - float(p50)),
            "cobertura_80": int(min(p10, p90) <= y <= max(p10, p90)),
        }
    if vn is not None and y_num is not None:
        e = float(y_num) - float(vn)
        return {"tipo": "numero", "ae": abs(e), "eq": e * e}
    if vt is not None and y_txt is not None:
        ok = str(vt).strip().lower() == str(y_txt).strip().lower()
        return {"tipo": "categoria", "acerto": int(ok), "brier": 0.0 if ok else 2.0}
    return None


METRICAS = {
    "faixa": ("wis", "ae_mediana", "cobertura_80"),
    "numero": ("ae", "eq"),
    "chance": ("brier", "log_score", "acerto"),
    "categoria": ("acerto", "brier"),
}
# métrica principal para escolher a melhor versão (menor é melhor, menos para acerto e cobertura)
PRINCIPAL = {"faixa": "wis", "numero": "ae", "chance": "brier", "categoria": "brier"}


def placar(linhas: list[dict]) -> list[dict]:
    """Agrupa por modelo, versão e alvo: previsões, com gabarito, maturadas e a média de cada nota."""
    grupos: dict[tuple, dict] = defaultdict(lambda: {"previsoes": 0, "com_gabarito": 0, "maturadas": 0, "notas": []})
    for r in linhas:
        g = grupos[(r["modelo"], r["modelo_versao"], r["alvo"])]
        g["previsoes"] += 1
        g["maturadas"] += int(bool(r.get("maturou")))
        n = nota(r)
        if n is not None:
            g["com_gabarito"] += 1
            g["notas"].append(n)
    out = []
    for (modelo, versao, alvo), g in sorted(grupos.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        tipos = {n["tipo"] for n in g["notas"]}
        tipo = tipos.pop() if len(tipos) == 1 else (None if not tipos else "misto")
        medias = {}
        if tipo in METRICAS:
            for m in METRICAS[tipo]:
                vals = [n[m] for n in g["notas"] if m in n]
                medias[m] = round(sum(vals) / len(vals), 6) if vals else None
        out.append(
            {
                "modelo": modelo,
                "modelo_versao": versao,
                "alvo": alvo,
                "tipo": tipo,
                "previsoes": g["previsoes"],
                "com_gabarito": g["com_gabarito"],
                "maturadas": g["maturadas"],
                **medias,
            }
        )
    return out


def campeoes(pl: list[dict], minimo: int = 10) -> list[dict]:
    """Por modelo e alvo, a versão com a melhor nota principal entre as que têm ao menos `minimo` gabaritos (o
    portão do campeão e desafiante da E8 decide a troca; aqui só se mostra quem está na frente)."""
    por: dict[tuple, list[dict]] = defaultdict(list)
    for r in pl:
        if r["tipo"] in PRINCIPAL and r["com_gabarito"] >= minimo and r.get(PRINCIPAL[r["tipo"]]) is not None:
            por[(r["modelo"], r["alvo"])].append(r)
    out = []
    for (modelo, alvo), rs in sorted(por.items()):
        m = PRINCIPAL[rs[0]["tipo"]]
        melhor = min(rs, key=lambda r: r[m])
        out.append(
            {"modelo": modelo, "alvo": alvo, "metrica": m, "versao": melhor["modelo_versao"], "nota": melhor[m],
             "versoes_comparadas": len(rs)}
        )  # fmt: skip
    return out
