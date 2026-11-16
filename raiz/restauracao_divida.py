"""Dívida por ICSD, amortização sem aumento oculto do saldo e conta reserva."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path

import cvxpy as cp
import numpy as np


def versao() -> str:
    return (
        "divida-icsd-2026a+"
        + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
        + ";cvxpy="
        + version("cvxpy")
    )


@lru_cache(maxsize=32)
def _problema(n, carencia, fim, juros, fracao_maxima):
    capex = cp.Parameter(n, nonneg=True)
    limite_servico = cp.Parameter(n, nonneg=True)
    fracao = cp.Variable(nonneg=True)
    servico = cp.Variable(n, nonneg=True)
    saldo = cp.Variable(n + 1, nonneg=True)
    restricoes = [
        fracao <= fracao_maxima,
        saldo[0] == 0,
        saldo[-1] == 0,
        saldo[1:] == saldo[:-1] * (1 + juros) + capex * fracao - servico,
        servico <= limite_servico,
        servico[: carencia + 1] == 0,
    ]
    if fim + 1 < n:
        restricoes += [servico[fim + 1 :] == 0, saldo[fim + 1 :] == 0]
    # Juros após a carência precisam ser pagos: saldo não cresce para esconder
    # anos sem caixa. Capitalização fora da carência exigiria novo contrato.
    restricoes += [servico[carencia + 1 : fim + 1] >= juros * saldo[carencia + 1 : fim + 1]]
    problema = cp.Problem(cp.Maximize(fracao), restricoes)
    return problema, capex, limite_servico, fracao, servico, saldo


def dimensionar(
    capex,
    caixa_disponivel,
    *,
    juros_ano: float,
    carencia_meses: int,
    amortizacao_meses: int,
    icsd_minimo: float = 1.3,
    fracao_maxima: float = 0.5,
    reserva_meses: int = 6,
    periodos_ano: int = 12,
) -> dict:
    """Desembolso proporcional ao capex; serviço cabe no CFADS/ICSD.

    Mensal é o modo padrão. O motor histórico pode fornecer fluxo anual, caso
    explicitamente identificado; carência e amortização devem ser anos inteiros
    nesse caso. Reserva é capital próprio imobilizado, não receita para elevar
    artificialmente o ICSD. Capitaliza juros somente durante a carência.
    """
    k, caixa = np.asarray(capex, dtype=float), np.asarray(caixa_disponivel, dtype=float)
    if k.ndim != 1 or len(k) < 2 or caixa.shape != k.shape or not np.isfinite(k).all() or not np.isfinite(caixa).all():
        raise ValueError("capex e caixa devem ser vetores finitos do mesmo tamanho")
    if (k < 0).any() or periodos_ano not in (1, 12):
        raise ValueError("capex não negativo e periodicidade anual ou mensal obrigatórios")
    if not all(np.isfinite(x) for x in (juros_ano, icsd_minimo, fracao_maxima)) or not (
        0 <= juros_ano <= 1 and icsd_minimo >= 1 and 0 <= fracao_maxima <= 1
    ):
        raise ValueError("juros, ICSD ou fração inválidos")
    if any(isinstance(x, bool) or int(x) != x or x < 0 for x in (carencia_meses, amortizacao_meses, reserva_meses)):
        raise ValueError("prazos devem ser meses inteiros não negativos")
    passo = 12 // periodos_ano
    if carencia_meses % passo or amortizacao_meses % passo or amortizacao_meses == 0:
        raise ValueError("prazo incompatível com a periodicidade do fluxo")
    carencia, fim = carencia_meses // passo, (carencia_meses + amortizacao_meses) // passo
    if fim >= len(k) or carencia >= fim or k[carencia + 1 :].sum() > 1e-9:
        raise ValueError("horizonte insuficiente ou desembolso depois da carência")
    j = (1 + juros_ano) ** (1 / periodos_ano) - 1
    escala = max(float(k.sum()), float(np.max(np.abs(caixa))), 1)
    solver = "CVXPY/CLARABEL"
    # Prova exata de inviabilidade de dívida positiva: antes da primeira
    # amortização há saldo positivo, juros positivos e nenhum caixa para juros.
    # Evita milhares de LPs iguais nas bisseções de preço, sem mudar o modelo.
    zero = k.sum() == 0 or fracao_maxima == 0 or (j > 0 and caixa[carencia + 1] <= 0)
    if zero:
        fracao, servico, saldos = 0.0, np.zeros(len(k)), np.zeros(len(k) + 1)
        solver = "redução analítica exata das restrições de caixa/juros"
    else:
        p, entrada, limite, f, pagamento, saldo = _problema(len(k), carencia, fim, j, fracao_maxima)
        entrada.value = k / escala
        limite.value = np.maximum(caixa, 0) / (icsd_minimo * escala)
        p.solve(solver="CLARABEL", warm_start=True, tol_gap_abs=1e-9, tol_feas=1e-9)
        if p.status != cp.OPTIMAL:
            raise RuntimeError(f"dívida sem solução ótima: {p.status}")
        fracao = float(np.clip(f.value, 0, fracao_maxima))
        servico = np.maximum(np.asarray(pagamento.value) * escala, 0)
        saldos = np.maximum(np.asarray(saldo.value) * escala, 0)
        servico[np.abs(servico) < escala * 1e-8] = 0
    if fracao < 1e-7 or k.sum() == 0:
        fracao, servico, saldos = 0.0, np.zeros(len(k)), np.zeros(len(k) + 1)
    reserva = np.zeros(len(k))
    # Alvo: próximos N meses de serviço; anual usa a fração explícita do
    # próximo serviço anual. Conta abre com equity no período zero.
    for t in range(len(k)):
        restantes = reserva_meses / passo
        for futuro in range(t + 1, len(k)):
            if restantes <= 0:
                break
            reserva[t] += min(1, restantes) * servico[futuro]
            restantes -= 1
    movimento = np.diff(reserva, prepend=0.0)
    fluxo = fracao * k - servico - movimento
    cobertura = [float(caixa[i] / v) if v > escala * 1e-8 else None for i, v in enumerate(servico)]
    if any(v is not None and v < icsd_minimo - 1e-5 for v in cobertura):
        raise RuntimeError("solução viola ICSD após arredondamento")
    return {
        "modelo_versao": versao(),
        "solver": solver,
        "fracao": fracao,
        "valor_financiado": float(fracao * k.sum()),
        "fluxo_financiamento": fluxo.tolist(),
        "servico": servico.tolist(),
        "saldo_devedor": saldos.tolist(),
        "icsd": cobertura,
        "conta_reserva": reserva.tolist(),
        "movimento_reserva": movimento.tolist(),
        "reserva_fonte": "capital próprio; não compõe CFADS nem eleva ICSD",
        "periodos_ano": periodos_ano,
        "carencia_meses": carencia_meses,
        "amortizacao_meses": amortizacao_meses,
        "reserva_meses": reserva_meses,
        "limite": "Fluxo anual agregado; calendário mensal não inferido." if periodos_ano == 1 else None,
        "motivo_sem_divida": "caixa e ICSD não suportam juros/amortização no prazo" if fracao == 0 else None,
    }


def classificar_volume(
    volume_tco2e: float, classe: str, estagio_contrato: str, *, modelo_versao: str, evidencia: str | None = None
) -> dict:
    """Matriz própria inspirada no PRMS; não declara conformidade petrolífera."""
    if not np.isfinite(volume_tco2e) or volume_tco2e < 0:
        raise ValueError("volume inválido")
    if classe not in ("modelado", "medido", "emitido"):
        raise ValueError("classe deve ser modelado, medido ou emitido")
    if estagio_contrato not in ("sem_contrato", "em_negociacao", "contratado", "entregue"):
        raise ValueError("estágio do contrato desconhecido")
    if not modelo_versao or (classe != "modelado" and not evidencia):
        raise ValueError("versão obrigatória; medição/emissão requer evidência")
    if estagio_contrato == "entregue" and classe != "emitido":
        raise ValueError("volume entregue exige emissão comprovada")
    return {
        "volume_tco2e": float(volume_tco2e),
        "classe_volume": classe,
        "estagio_contrato": estagio_contrato,
        "evidencia": evidencia,
        "modelo_versao": modelo_versao,
        "classificador_versao": versao(),
        "habilita_comercializacao": False,
    }
