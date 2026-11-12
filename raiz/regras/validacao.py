"""Validação cruzada das regras (E2 passo 4): o laudo da Raíz contra o de outra fonte, imóvel a imóvel.

Fontes previstas: o quadro de áreas do SICAR (pedido de LAI ao SFB, docs/pedidos/lai-sfb.md), o GeoCAR (MIT, as regras
que o motor copiou) e o landschaft (GPL, só no servidor). Cada uma chega como uma tabela por imóvel; o mapa de colunas
de cada fonte fica em FONTES e é conferido quando o primeiro arquivo chegar (nomes marcados como provisórios).

Como no Tax-Calculator, cada diferença vira uma linha para investigar: o valor dos dois lados, a diferença e a
explicação passo a passo da Raíz para o imóvel.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from raiz.regras import Parametros, federal, parametros

# nome na fonte -> nome na Raíz. "provisorio": conferir com o primeiro arquivo real.
FONTES: dict[str, dict] = {
    "sicar": {
        "descricao": "quadro de áreas do SICAR (demonstrativo do imóvel)",
        "provisorio": True,
        "colunas": {
            "cod_imovel": "cod_imovel",
            "num_area_imovel": "ha",
            "num_modulo_fiscal": "m_fiscal",
            "num_area_reserva_legal_minima_lei": "rl_minima_ha",
            "num_area_remanescente_vegetacao_nativa": "floresta_rem_ha",
        },
    },
    "geocar": {
        "descricao": "GeoCAR (regras em Python, MIT)",
        "provisorio": True,
        "colunas": {"cod_imovel": "cod_imovel", "rl_exigida_ha": "rl_minima_ha", "deficit_rl_ha": "deficit_RL_ha"},
    },
    "landschaft": {
        "descricao": "landschaft (GPL, rodado no servidor)",
        "provisorio": True,
        "colunas": {
            "cod_imovel": "cod_imovel",
            "reserva_legal_minima_ha": "rl_minima_ha",
            "deficit_ha": "deficit_RL_ha",
        },
    },
}

TOL_IGUAL_HA, TOL_IGUAL_REL = 0.01, 0.001
TOL_PERTO_HA, TOL_PERTO_REL = 1.0, 0.02


def laudo_raiz(im: pd.DataFrame, p: Parametros | None = None) -> pd.DataFrame:
    """Colunas comparáveis da Raíz por imóvel, a partir das colunas do motor."""
    p = p or parametros()
    r = federal.calcular(im, p)
    out = pd.DataFrame({"cod_imovel": im.cod_imovel.values}, index=im.index)
    out["ha"] = im.ha
    out["m_fiscal"] = im.m_fiscal
    out["floresta_rem_ha"] = im.floresta_rem_ha
    base = im.ha - im.get("nao_floresta_ha", 0.0)
    out["rl_minima_ha"] = r.pct_RL / 100 * base
    out["deficit_RL_ha"] = r.deficit_RL_ha
    if "app_recompor_ha" in r:
        out["app_recompor_ha"] = r.app_recompor_ha
    return out.reset_index(drop=True)


def classificar(raiz: pd.Series, externo: pd.Series) -> pd.Series:
    d = (raiz - externo).abs()
    escala = np.maximum(raiz.abs(), externo.abs())
    classe = np.where(
        raiz.isna() & externo.notna(),
        "só na fonte",
        np.where(
            raiz.notna() & externo.isna(),
            "só na Raíz",
            np.where(
                (d <= TOL_IGUAL_HA) | (d <= TOL_IGUAL_REL * escala),
                "igual",
                np.where((d <= TOL_PERTO_HA) | (d <= TOL_PERTO_REL * escala), "perto", "diferente"),
            ),
        ),
    )
    classe = np.where(raiz.isna() & externo.isna(), "sem valor", classe)
    return pd.Series(classe, index=raiz.index)


@dataclass
class Relatorio:
    fonte: str
    linhas: pd.DataFrame  # cod_imovel, coluna, raiz, fonte, diferenca, classe
    resumo: pd.DataFrame  # coluna x classe
    sem_par: dict = field(default_factory=dict)  # imóveis que só um lado tem

    def piores(self, n: int = 20) -> pd.DataFrame:
        d = self.linhas[self.linhas.classe == "diferente"]
        return d.reindex(d.diferenca.abs().sort_values(ascending=False).index).head(n)


def comparar(im: pd.DataFrame, externo: pd.DataFrame, fonte: str, p: Parametros | None = None) -> Relatorio:
    """im: imóveis do motor (colunas de docs/colunas.md); externo: a tabela da fonte com os nomes dela."""
    cfg = FONTES[fonte]
    ext = externo.rename(columns=cfg["colunas"])
    faltam = [c for c in cfg["colunas"].values() if c not in ext.columns]
    if "cod_imovel" in faltam:
        raise ValueError(f"{fonte}: tabela sem a coluna do código do imóvel ({cfg['colunas']})")
    nossa = laudo_raiz(im, p)
    comuns = [c for c in cfg["colunas"].values() if c != "cod_imovel" and c in ext.columns and c in nossa.columns]
    j = nossa[["cod_imovel", *comuns]].merge(
        ext[["cod_imovel", *comuns]], on="cod_imovel", how="outer", suffixes=("_raiz", "_fonte"), indicator=True
    )
    sem_par = {
        "só na Raíz": j.loc[j._merge == "left_only", "cod_imovel"].tolist(),
        "só na fonte": j.loc[j._merge == "right_only", "cod_imovel"].tolist(),
    }
    j = j[j._merge == "both"]
    partes = []
    for c in comuns:
        a, b = pd.to_numeric(j[f"{c}_raiz"], errors="coerce"), pd.to_numeric(j[f"{c}_fonte"], errors="coerce")
        partes.append(
            pd.DataFrame(
                {
                    "cod_imovel": j.cod_imovel.values,
                    "coluna": c,
                    "raiz": a.values,
                    "fonte": b.values,
                    "diferenca": (a - b).values,
                    "classe": classificar(a, b).values,
                }
            )
        )
    linhas = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()
    resumo = linhas.groupby(["coluna", "classe"]).size().unstack(fill_value=0) if len(linhas) else pd.DataFrame()
    return Relatorio(fonte, linhas, resumo, sem_par)


def explicar_diferencas(rel: Relatorio, im: pd.DataFrame, n: int = 10, p: Parametros | None = None) -> list[str]:
    """Texto para investigar as maiores diferenças: valores dos dois lados e o passo a passo da Raíz."""
    p = p or parametros()
    por_cod = im.set_index("cod_imovel")
    out = []
    for _, d in rel.piores(n).iterrows():
        out.append(
            f"{d.cod_imovel} {d.coluna}: Raíz {d.raiz:.2f}, {rel.fonte} {d.fonte:.2f} (diferença {d.diferenca:+.2f})"
        )
        if d.cod_imovel in por_cod.index:
            out += [f"    {passo}" for passo in federal.explicar(por_cod.loc[d.cod_imovel], p)]
    return out
