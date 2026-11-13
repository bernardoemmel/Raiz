"""Diagnósticos fora da API: reamostragem somente no fit, variância da floresta e caudas."""

import numpy as np


def classificador_balanceado(estimador, *, semente: int = 12):
    """A Pipeline do imbalanced-learn só reamostra em fit; predict preserva a coorte original."""
    from imblearn.over_sampling import RandomOverSampler
    from imblearn.pipeline import Pipeline
    from sklearn.base import clone
    from sklearn.preprocessing import StandardScaler

    return Pipeline(
        [
            ("escala", StandardScaler()),
            ("balanceamento", RandomOverSampler(random_state=semente)),
            ("modelo", clone(estimador)),
        ]
    )


def variancia_floresta(floresta, x_treino, x_teste) -> np.ndarray:
    """IJ do forestci mede variância da média estimada, não intervalo preditivo nem sorteios para CRPS."""
    import forestci

    if not floresta.bootstrap or len(floresta.estimators_) < 100:
        raise ValueError("forestci exige bootstrap e ao menos 100 árvores neste protocolo")
    # Sem calibração empírica Bayes aleatória: resultado determinístico; negativos são diagnosticados.
    v = np.asarray(
        forestci.random_forest_error(floresta, np.asarray(x_treino).shape, np.asarray(x_teste), calibrate=False),
        dtype=float,
    )
    if not np.isfinite(v).all() or (v < 0).any():
        raise ValueError("variância IJ instável; aumentar árvores e conferir o treino")
    return v


def caudas(erros, destino) -> dict:
    """Gráfico privado sem IDs; preserva os dois sinais e não elimina os extremos."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import probscale

    e = np.asarray(erros, dtype=float)
    if e.ndim != 1 or len(e) < 20 or not np.isfinite(e).all():
        raise ValueError("caudas exigem ao menos 20 erros finitos")
    fig = probscale.probplot(e, problabel="Probabilidade acumulada (%)", datalabel="Erro (tCO₂e/ha/ano)")
    try:
        fig.savefig(destino, metadata={"Creator": "Raíz — avaliação privada"})
    finally:
        plt.close(fig)
    return {
        "n": len(e),
        "p01": float(np.quantile(e, 0.01)),
        "p50": float(np.quantile(e, 0.5)),
        "p99": float(np.quantile(e, 0.99)),
        "erro_absoluto_p95": float(np.quantile(np.abs(e), 0.95)),
    }
