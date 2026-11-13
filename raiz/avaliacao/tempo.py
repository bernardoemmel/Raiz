"""Origens móveis do sktime; o callback não recebe resultados futuros nem entradas tardias."""

from collections.abc import Callable, Sequence
from datetime import datetime

import pandas as pd

from raiz.avaliacao.contratos import ObservacaoTemporal, instante
from raiz.avaliacao.metricas import crps


def avaliar(
    observacoes: Sequence[ObservacaoTemporal],
    origens: Sequence[datetime],
    treinar_prever: Callable,
    *,
    janela_inicial: int = 3,
    horizonte: int = 1,
) -> list[dict]:
    """Callback novo por origem: (treino imutável, corte, datas futuras) -> sorteios por data.

    O horizonte é contado em posições do calendário explícito, não em registros de fazendas.
    Gabarito posterior pode avaliar; jamais volta ao treino antes de conhecido_em.
    """
    from sktime.split import ExpandingWindowSplitter

    datas = tuple(instante(x) for x in origens)
    if len(datas) <= janela_inicial or janela_inicial < 1 or horizonte < 1 or tuple(sorted(set(datas))) != datas:
        raise ValueError("calendário da avaliação inválido")
    if len({x.caso_id for x in observacoes}) != len(observacoes):
        raise ValueError("observação duplicada")
    splitter = ExpandingWindowSplitter(initial_window=janela_inicial, fh=[horizonte], step_length=1)
    saida = []
    for passados, futuros in splitter.split(pd.Series(range(len(datas)))):
        corte = datas[passados[-1]]
        treino = tuple(
            x
            for x in observacoes
            if x.evento_em <= corte and x.conhecido_em <= corte and x.entradas_disponiveis_em <= corte
        )
        if not treino:
            raise ValueError("origem sem observações disponíveis")
        alvos = tuple(datas[i] for i in futuros)
        previsoes = treinar_prever(treino, corte, alvos)
        if set(previsoes) != set(alvos):
            raise ValueError("horizontes previstos divergem do protocolo")
        for data in alvos:
            gabaritos = [x for x in observacoes if x.evento_em == data]
            if not gabaritos:
                raise ValueError("horizonte sem gabarito; avaliação insuficiente")
            saida.append(
                {
                    "corte": corte,
                    "horizonte": data,
                    "n_treino": len(treino),
                    "n_real": len(gabaritos),
                    "crps": sum(crps(x.valor, previsoes[data]) for x in gabaritos) / len(gabaritos),
                }
            )
    if not saida:
        raise ValueError("nenhuma origem avaliável")
    return saida
