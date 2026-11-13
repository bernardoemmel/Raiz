"""CRPS na unidade do alvo; nunca reconstrói distribuição só de P10/P50/P90."""

import math

import numpy as np
from properscoring import _crps, crps_ensemble


def crps(real: float, sorteios) -> float:
    if _crps._crps_ensemble_core is _crps._crps_ensemble_vectorized:
        raise RuntimeError("CRPS exige o backend Numba; fallback quadrático recusado")
    amostra = np.asarray(sorteios, dtype=float)
    if amostra.ndim != 1 or amostra.size < 2 or not np.isfinite(amostra).all() or not math.isfinite(real):
        raise ValueError("CRPS exige resultado e sorteios finitos")
    nota = float(crps_ensemble(float(real), amostra))
    if not math.isfinite(nota):
        raise ValueError("CRPS fora da faixa numérica suportada")
    return nota


def crps_distribuicao(real: float, distribuicao: dict) -> float:
    if not isinstance(distribuicao, dict) or set(distribuicao) != {"tipo", "sorteios"}:
        raise ValueError("distribuição não suportada para CRPS")
    if distribuicao["tipo"] != "empirica":
        raise ValueError("distribuição não suportada para CRPS")
    return crps(real, distribuicao["sorteios"])
