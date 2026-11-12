"""Vazamento (Verra VMD0054): o gado que sai da área restaurada vai para onde? (trazido da branch
claude/premissas-rodada11, da outra sessão da rodada 11)

Para cada fazenda que entra em projeto, procura uma fazenda vizinha que possa intensificar o pasto e receber esse gado
(área de mitigação, VMD0054 seção 5.2). Achou, o vazamento da fazenda vai a zero e a vizinha entra no lote como área
de mitigação. Regra nas premissas (raiz/regras/padroes/restauracao.yaml, bloco `mitigacao`):
vizinha a até `raio_km`, pasto com vigor médio ou alto, lotação atual abaixo da lotação alvo e folga para as cabeças
deslocadas. Lê as colunas pelo nome; sem nome, CPF ou CNPJ.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np


def _num(linha: dict, c: str) -> float | None:
    v = linha.get(c)
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _verdade(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "sim", "t")
    try:
        return bool(v) and not (isinstance(v, float) and math.isnan(v))
    except (TypeError, ValueError):
        return False


def _vigor(linha: dict) -> int | None:
    v = _num(linha, "mb_pasto_vigor_principal")
    if v is None:
        m = _num(linha, "pasto_vigor_media")
        v = None if m is None else round(m)
    return None if v is None or v < 1 else int(min(v, 3))


def _pasto(linha: dict) -> float:
    x = _num(linha, "pasto_ha")
    if x is None:
        x = _num(linha, "mb_pasto_2025_ha")
    return max(x or 0.0, 0.0)


def rebanho(linha: dict, p: dict | None = None) -> tuple[float | None, str]:
    """Rebanho do imóvel: o do motor (rebanho_cabecas) ou, sem ele, a lotação média do Censo vezes o pasto."""
    reb = _num(linha, "rebanho_cabecas")
    if reb is not None:
        return reb, "motor"
    if p is None:
        return None, "sem_rebanho"
    lot = p["mitigacao"].get("lotacao_quando_falta_rebanho") or {}
    try:
        cm = int(float(linha.get("cod_municipio_ibge")))
    except (TypeError, ValueError):
        cm = None
    uf = str(linha.get("uf") or "").upper()
    if cm is not None and cm in (lot.get("por_municipio") or {}):
        return float(lot["por_municipio"][cm]) * _pasto(linha), "censo_municipio"
    if uf in (lot.get("por_uf") or {}):
        return float(lot["por_uf"][uf]) * _pasto(linha), "censo_uf"
    return None, "sem_rebanho"


def cabecas_deslocadas(linha: dict, area: float, p: dict | None = None) -> float | None:
    """Cabeças que saem da área restaurada: o rebanho da fazenda na proporção da área sobre o pasto."""
    reb, _ = rebanho(linha, p)
    if reb is None:
        return None
    pasto = _pasto(linha)
    if pasto <= 0:
        return 0.0 if area <= 0 else reb
    return reb * min(area / pasto, 1.0)


def pode_receber(linha: dict) -> bool:
    """Pode ser área de mitigação: sem bloqueio, sem outro projeto de carbono e sem problema no imóvel."""
    if _verdade(linha.get("problema")):
        return False
    if str(linha.get("filtro_territorial") or "").lower() == "bloqueio":
        return False
    if (_num(linha, "projeto_carbono_ha") or 0.0) > 0:
        return False
    return linha.get("caminho_terra") not in ("publica_sem_destinacao", "terra_indigena_ou_tradicional")


def mitigacoes(
    registros: list[dict],
    pontos: dict[str, tuple[float, float]],
    p: dict,
    area_de: Callable[[dict], float],
    elegivel: Callable[[dict], bool],
) -> dict[str, dict]:
    """Por fazenda: vazamento_mitigacao (vazamento zerado), vazamento_mitigacao_imovel (a vizinha), vazamento_motivo
    (mitigacao_vizinha, sem_gado, sem_vizinha, sem_rebanho, sem_ponto), cabecas_deslocadas e rebanho_fonte
    (motor, censo_municipio ou censo_uf)."""
    from scipy.spatial import cKDTree

    regra = p["mitigacao"]
    raio = float(regra["raio_km"])
    alvo = float(regra["lotacao_alvo_cab_ha"])
    vig_min = int(regra["vigor_minimo"])
    por = {str(x["cod_imovel"]): x for x in registros}
    area = {c: area_de(x) for c, x in por.items()}
    projetos = {c: x for c, x in por.items() if area[c] > 0 and elegivel(x)}
    out: dict[str, dict] = {}
    desloc = {}
    for c, x in projetos.items():
        cab = cabecas_deslocadas(x, area[c], p)
        desloc[c] = cab
        if cab is None:
            out[c] = {"vazamento_mitigacao": False, "vazamento_motivo": "sem_rebanho", "cabecas_deslocadas": None}
        elif cab <= 0:
            out[c] = {"vazamento_mitigacao": True, "vazamento_motivo": "sem_gado", "cabecas_deslocadas": 0.0}
    # folga de cada candidata: (lotação alvo x pasto que fica) - gado que fica
    folga = {}
    for c, x in por.items():
        if c not in pontos or not pode_receber(x):
            continue
        vg = _vigor(x)
        reb, _ = rebanho(x, p)
        if vg is None or vg < vig_min or reb is None:
            continue
        fica_pasto = _pasto(x) - (area[c] if c in projetos else 0.0)
        fica_reb = reb - ((desloc.get(c) or 0.0) if c in projetos else 0.0)
        f = alvo * max(fica_pasto, 0.0) - max(fica_reb, 0.0)
        if f > 0:
            folga[c] = f
    cands = sorted(folga)
    arvore = None
    if cands:
        xy = np.array([pontos[c] for c in cands], dtype=float)
        lat0 = float(np.radians(np.nanmean(xy[:, 1])))
        km = np.column_stack([xy[:, 0] * 111.32 * math.cos(lat0), xy[:, 1] * 110.57])
        arvore = cKDTree(km)
    for c in sorted(projetos, key=lambda k: -(desloc.get(k) or 0.0)):
        if c in out:
            continue
        cab = desloc[c]
        if c not in pontos:
            out[c] = {"vazamento_mitigacao": False, "vazamento_motivo": "sem_ponto", "cabecas_deslocadas": cab}
            continue
        achou = None
        if arvore is not None:
            lon, lat = pontos[c]
            q = np.array([lon * 111.32 * math.cos(lat0), lat * 110.57])
            for i in sorted(arvore.query_ball_point(q, r=raio), key=lambda i: float(np.hypot(*(km[i] - q)))):
                v = cands[i]
                if v != c and folga.get(v, 0.0) >= cab:
                    achou = v
                    folga[v] -= cab
                    break
        if achou:
            out[c] = {"vazamento_mitigacao": True, "vazamento_mitigacao_imovel": achou,
                      "vazamento_motivo": "mitigacao_vizinha", "cabecas_deslocadas": round(cab, 1)}  # fmt: skip
        else:
            out[c] = {
                "vazamento_mitigacao": False,
                "vazamento_motivo": "sem_vizinha",
                "cabecas_deslocadas": round(cab, 1),
            }
    for c, x in projetos.items():
        if c in out:
            out[c]["rebanho_fonte"] = rebanho(x, p)[1]
    return out
