"""Linha de base dinâmica por blocos espaciais e controle sintético (pysyncon).

O contrato usa períodos inteiros (por exemplo, mês ordinal). O ajuste enxerga
apenas os períodos anteriores ao plantio; valores posteriores só avaliam o
contrafactual. Não há importação de scpi no pacote distribuído.
"""

from __future__ import annotations

import hashlib
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import CRS
from pysyncon import Synth


def versao() -> str:
    h = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
    return f"linha-base-sintetica-2026a+{h};pysyncon={version('pysyncon')}"


def agregar_pixels(pixels: pd.DataFrame, *, crs: str, bloco_m: float = 1000) -> pd.DataFrame:
    """Média ponderada pela área em blocos fixos; pixels não viram réplicas."""
    sistema = CRS.from_user_input(crs)
    if not sistema.is_projected or any(a.unit_name != "metre" for a in sistema.axis_info[:2]):
        raise ValueError("agregação requer CRS projetado em metros")
    if not np.isfinite(bloco_m) or bloco_m <= 0:
        raise ValueError("bloco_m deve ser positivo")
    campos = ["pixel_id", "x_m", "y_m", "periodo", "tratado", "elegivel_controle", "valor", "area_m2"]
    t = pixels[campos].copy()
    if t.isna().any().any() or t.duplicated(["pixel_id", "periodo"]).any():
        raise ValueError("pixels devem ser completos e únicos por período")
    if not np.isfinite(t[["x_m", "y_m", "periodo", "valor", "area_m2"]].to_numpy()).all() or (t.area_m2 <= 0).any():
        raise ValueError("valores finitos e área positiva são obrigatórios")
    if not t.tratado.isin([True, False]).all() or not t.elegivel_controle.isin([True, False]).all():
        raise ValueError("tratado e elegivel_controle devem ser booleanos")
    if not (t.periodo == np.floor(t.periodo)).all():
        raise ValueError("período deve ser inteiro")
    fixos = t.groupby("pixel_id")[["x_m", "y_m", "area_m2", "tratado", "elegivel_controle"]].nunique()
    if (fixos > 1).any().any():
        raise ValueError("geometria, área e elegibilidade do pixel devem ser fixas")
    t = t[t.tratado | t.elegivel_controle].copy()
    t["bloco"] = (
        np.floor(t.x_m / bloco_m).astype(int).astype(str) + ":" + np.floor(t.y_m / bloco_m).astype(int).astype(str)
    )
    if (t.groupby("bloco").tratado.nunique() > 1).any():
        raise ValueError("bloco mistura tratamento e controle; ampliar faixa de exclusão dos doadores")
    t["ponderado"] = t.valor * t.area_m2
    g = t.groupby(["bloco", "periodo", "tratado"], as_index=False).agg(
        area_m2=("area_m2", "sum"), ponderado=("ponderado", "sum"), n_pixels=("pixel_id", "nunique")
    )
    if (g.groupby("bloco")["area_m2"].nunique() > 1).any():
        raise ValueError("área observada varia entre períodos; harmonizar máscara antes do ajuste")
    g["valor"] = g.ponderado / g.area_m2
    return g.drop(columns="ponderado").sort_values(["bloco", "periodo"]).reset_index(drop=True)


def ajustar(blocos: pd.DataFrame, *, bloco_tratado: str, periodo_plantio: int, unidade: str) -> dict:
    """Controles devem estar previamente livres de intervenção e de vazamento."""
    if not unidade.strip():
        raise ValueError("unidade física obrigatória")
    t = blocos.copy()
    if t.duplicated(["bloco", "periodo"]).any() or t[["bloco", "periodo", "valor", "tratado"]].isna().any().any():
        raise ValueError("painel deve ser completo e único por bloco/período")
    if (t.groupby("bloco").tratado.nunique() != 1).any():
        raise ValueError("tratamento não pode variar na definição do bloco")
    tratados = set(t.loc[t.tratado, "bloco"])
    if bloco_tratado not in tratados:
        raise ValueError("bloco_tratado não identificado como tratado")
    controles = sorted(set(t.bloco) - tratados)
    if len(controles) < 2:
        raise ValueError("exige ao menos dois blocos de controle")
    painel = t.pivot(index="periodo", columns="bloco", values="valor")[[bloco_tratado, *controles]].sort_index()
    if not np.isfinite(painel.to_numpy()).all():
        raise ValueError("painel desbalanceado ou valores não finitos")
    pre = painel[painel.index < periodo_plantio]
    pos = painel[painel.index >= periodo_plantio]
    if len(pre) < 4 or pos.empty:
        raise ValueError("exige quatro períodos pré-plantio e ao menos um pós-plantio")
    # Cada período pré é um preditor. Não se escolhem variáveis pelo resultado pós.
    x0, x1 = pre[controles], pre[bloco_tratado]
    variaveis = pd.concat([x0, x1], axis=1).std(axis=1) > 1e-12
    if not variaveis.any():
        pesos = np.full(len(controles), 1 / len(controles))
    else:
        modelo = Synth()
        modelo.fit(
            X0=x0[variaveis],
            X1=x1[variaveis],
            Z0=x0,
            Z1=x1,
            custom_V=np.ones(int(variaveis.sum())) / int(variaveis.sum()),
        )
        pesos = np.asarray(modelo.W)
    if not np.isfinite(pesos).all() or pesos.min() < -1e-7 or not np.isclose(pesos.sum(), 1):
        raise RuntimeError("pesos inválidos no controle sintético")
    pesos = np.maximum(pesos, 0)
    pesos /= pesos.sum()
    sintetico = painel[controles].to_numpy() @ pesos
    tratado = painel[bloco_tratado].to_numpy()
    gap = tratado - sintetico
    origem = len(pre) - 1
    linhas = [
        {
            "periodo": int(p),
            "fase": "pre" if p < periodo_plantio else "pos",
            "observado": float(a),
            "linha_base": float(b),
            "diferenca_estoque": float(d),
            "adicional_desde_ultimo_pre": float(d - gap[origem]),
        }
        for p, a, b, d in zip(painel.index, tratado, sintetico, gap, strict=True)
    ]
    return {
        "modelo_versao": versao(),
        "unidade": unidade,
        "bloco_tratado": bloco_tratado,
        "periodo_plantio": periodo_plantio,
        "periodos_treino": [int(p) for p in pre.index],
        "treino_sha256": hashlib.sha256(pre.to_csv(float_format="%.12g").encode()).hexdigest(),
        "pesos_controles": dict(zip(controles, pesos.tolist(), strict=True)),
        "rmse_pre": float(np.sqrt(np.mean(gap[: len(pre)] ** 2))),
        "serie": linhas,
        "p10_p90": None,
        "pendencia_incerteza": "inferência scpi no servidor, sem GPL no pacote",
        "habilita_comercializacao": False,
        "limites": "Requer controles comparáveis, sem tratamento nem efeito do deslocamento do gado.",
    }
