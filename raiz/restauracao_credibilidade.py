"""Credibilidade parcial de parcelas locais com experiência regional comparável.

Implementação própria de Bühlmann com componentes de variância, inspirada na
ASOP 25. A norma não prescreve estes parâmetros nem certifica este modelo.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

FONTE = "https://www.actuarialstandardsboard.org/asops/credibility-procedures/"
CHAVES = ("bioma", "metodo", "unidade", "protocolo")


def versao() -> str:
    return "credibilidade-2026a+" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]


def combinar(
    locais: list[dict],
    coorte: list[dict],
    *,
    perfil: dict,
    idade_anos: float,
    janela_anos: float = 2,
    correlacao_local: float = 1.0,
) -> dict:
    """Nunca mistura protocolos/unidades e exclui parcelas locais da coorte.

    Correlação local = 1 é o padrão conservador: parcelas no mesmo bloco contam
    como uma unidade independente. Uma correlação menor precisa ser informada e
    fica registrada. Quantis são descritivos na unidade da parcela padronizada.
    """
    if not all(perfil.get(k) for k in CHAVES):
        raise ValueError("perfil requer bioma, método, unidade e protocolo")
    if (
        not np.isfinite([idade_anos, janela_anos, correlacao_local]).all()
        or idade_anos < 0
        or janela_anos < 0
        or not 0 <= correlacao_local <= 1
    ):
        raise ValueError("idade, janela ou correlação inválida")

    def filtrar(registros):
        t = pd.DataFrame(registros)
        if t.empty:
            return pd.DataFrame(columns=["parcela_id", "bloco_id", "valor"])
        if t[["parcela_id", "bloco_id", "valor", "idade_anos", *CHAVES]].isna().any().any():
            raise ValueError("parcelas, blocos e características devem estar completos")
        if t.parcela_id.duplicated().any():
            raise ValueError("parcela duplicada")
        if not np.isfinite(t[["valor", "idade_anos"]].to_numpy()).all() or (t.valor < 0).any():
            raise ValueError("valor ou idade não finitos/negativos")
        for k in CHAVES:
            t = t[t[k] == perfil[k]]
        return t[t.idade_anos.between(max(0, idade_anos - janela_anos), idade_anos + janela_anos)].copy()

    local, regional = filtrar(locais), filtrar(coorte)
    regional = regional[~regional.parcela_id.isin(local.parcela_id) & ~regional.bloco_id.isin(local.bloco_id)]
    registro = {
        "modelo_versao": versao(),
        "perfil": perfil,
        "idade_anos": idade_anos,
        "janela_anos": janela_anos,
        "n_local": len(local),
        "n_coorte": len(regional),
        "correlacao_local": correlacao_local,
        "fonte_metodo": FONTE,
        "rotulo": "estimativa regional combinada com parcelas locais"
        if len(local)
        else "estimativa regional, não medida na fazenda",
    }
    grupos = regional.groupby("bloco_id").valor.agg(["count", "mean", "var"])
    if len(grupos) < 3 or (grupos["count"] < 2).any():
        return {
            **registro,
            "status": "pendente_coorte_comparavel",
            "peso_local": None,
            "criterio": "Exige pelo menos três blocos comparáveis, com duas parcelas por bloco; não inventar peso.",
        }
    n = grupos["count"].to_numpy(dtype=float)
    medias = grupos["mean"].to_numpy()
    media_coorte = float(np.average(medias, weights=n))
    dentro = float(np.sum((n - 1) * grupos["var"]) / (n.sum() - len(n)))
    entre_bruto = float(np.sum(n * (medias - media_coorte) ** 2) / (len(n) - 1))
    coef = (n.sum() - np.sum(n * n) / n.sum()) / (len(n) - 1)
    entre = max(0.0, (entre_bruto - dentro) / coef)
    tamanhos = local.groupby("bloco_id").size().to_numpy(dtype=float)
    n_efetivo = float(np.sum(tamanhos / (1 + (tamanhos - 1) * correlacao_local)))
    k = dentro / entre if entre > 0 else None
    peso = n_efetivo / (n_efetivo + k) if k is not None and n_efetivo > 0 else 0.0
    media_local = float(local.valor.mean()) if len(local) else None
    valores = regional.valor.to_numpy(dtype=float)
    pesos = np.full(len(valores), (1 - peso) / len(valores))
    if peso:
        valores = np.r_[valores, local.valor.to_numpy(dtype=float)]
        pesos = np.r_[pesos, np.full(len(local), peso / len(local))]
    ordem = np.argsort(valores)
    v, acumulado = valores[ordem], np.cumsum(pesos[ordem])
    quantis = {
        q: float(v[min(int(np.searchsorted(acumulado, p)), len(v) - 1)])
        for q, p in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9))
    }
    return {
        **registro,
        "status": "estimado",
        "peso_local": peso,
        "peso_coorte": 1 - peso,
        "n_local_efetivo": n_efetivo,
        "k": k,
        "variancia_dentro": dentro,
        "variancia_entre": entre,
        "media_local": media_local,
        "media_coorte": media_coorte,
        "media_combinada": peso * (media_local or 0) + (1 - peso) * media_coorte,
        **quantis,
        "natureza_quantis": "distribuição descritiva de parcelas comparáveis; não total da fazenda",
        "criterio": "Peso local n efetivo/(n efetivo + K); K pela variância dentro/entre blocos da coorte. "
        "Mesmos bioma, método, protocolo e unidade; sem duplicar parcelas locais na coorte.",
        "entradas_sha256": hashlib.sha256(
            pd.concat([t for t in (local, regional) if not t.empty], ignore_index=True)
            .sort_values("parcela_id")
            .to_json(orient="records")
            .encode()
        ).hexdigest(),
    }
