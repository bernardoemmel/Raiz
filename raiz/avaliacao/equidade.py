"""Diferença de seleção condicional, sem esconder estrato ausente em uma média nacional."""

from collections import Counter, defaultdict
from itertools import combinations

import numpy as np
import pandas as pd

from raiz.avaliacao.contratos import Inclusao

PORTES = ("pequena", "media", "grande")


def medir(inclusoes: list[Inclusao], *, limite: float = 0.05, minimo: int = 30) -> dict:
    from aif360.sklearn.metrics import statistical_parity_difference

    if not np.isfinite(limite) or not 0 <= limite <= 1 or minimo < 2:
        raise ValueError("política de equidade inválida")
    if not inclusoes or len({(x.decisao_id, x.caso_id) for x in inclusoes}) != len(inclusoes):
        raise ValueError("coorte vazia ou duplicada")
    grupos = defaultdict(list)
    for x in inclusoes:
        grupos[(x.municipio, x.aptidao)].append(x)
    resultados = []
    for (municipio, aptidao), xs in sorted(grupos.items()):
        por = {p: [x for x in xs if x.porte == p] for p in PORTES}
        # Repetir decisões sobre a mesma fazenda não aumenta a evidência de cobertura.
        contagens = {p: len({x.caso_id for x in v}) for p, v in por.items()}
        suficiente = all(n >= minimo for n in contagens.values())
        diferencas = []
        if suficiente:
            for a, b in combinations(PORTES, 2):
                par = por[a] + por[b]
                y = pd.Series([int(x.entrou) for x in par], index=pd.Index([x.porte for x in par], name="porte"))
                repeticoes = Counter(x.caso_id for x in par)
                pesos = [1 / repeticoes[x.caso_id] for x in par]
                gap = float(statistical_parity_difference(y, prot_attr="porte", priv_group=b, sample_weight=pesos))
                diferencas.append({"classes": [a, b], "diferenca": gap})
        aprovado = suficiente and all(abs(d["diferenca"]) <= limite + 1e-12 for d in diferencas)
        resultados.append(
            {
                "municipio": municipio,
                "aptidao": aptidao,
                "n": contagens,
                "taxas": {p: _taxa(v) if v else None for p, v in por.items()},
                "diferencas": diferencas,
                "suficiente": suficiente,
                "aprovado": aprovado,
            }
        )
    return {
        "aprovado": all(r["aprovado"] for r in resultados),
        "limite": limite,
        "minimo": minimo,
        "estratos": resultados,
    }


def exigir(relatorio: dict) -> None:
    if not relatorio["aprovado"]:
        raise ValueError("equidade reprovada: diferença excessiva ou cobertura insuficiente")


def _taxa(xs) -> float:
    por = defaultdict(list)
    for x in xs:
        por[x.caso_id].append(x.entrou)
    return sum(sum(v) / len(v) for v in por.values()) / len(por)


def politica() -> dict:
    import json

    from raiz import RAIZ_REPO

    return json.loads((RAIZ_REPO / "infra/politica-avaliacao.json").read_text())
