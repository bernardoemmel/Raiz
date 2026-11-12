"""Chave de bloco (E2 passo 3): grade fixa de 0,5 grau, a mesma dos blocos que o motor guarda em cache/tb/.

O bloco de um imóvel é o do ponto dentro dele (point_on_surface, em graus SIRGAS 2000), então cada imóvel tem um
bloco só, e o mesmo no Python e no banco (função funil.chave_bloco, migração 0010). Um imóvel grande pode tocar
outros blocos: `blocos_tocados` lista todos, para saber o que recalcular quando uma camada muda num bloco.

Formato: "<x do canto sudoeste>_<y do canto sudoeste>", como "-47.0_-3.5" (igual ao nome dos arquivos do motor).
"""

from __future__ import annotations

import math

import numpy as np
import shapely

PASSO = 0.5


def canto(v: float, passo: float = PASSO) -> float:
    return round(math.floor(v / passo) * passo, 4) + 0.0  # + 0.0 tira o -0.0


def chave(lon: float, lat: float, passo: float = PASSO) -> str:
    return f"{canto(lon, passo)}_{canto(lat, passo)}"


def caixa(ch: str, passo: float = PASSO) -> tuple[float, float, float, float]:
    x, y = (float(t) for t in ch.split("_"))
    return x, y, x + passo, y + passo


def chaves(geoms, passo: float = PASSO) -> np.ndarray:
    """Bloco de cada geometria (em graus). Geometria nula ou vazia: None."""
    geoms = np.asarray(geoms, dtype=object)
    out = np.full(len(geoms), None, dtype=object)
    ok = np.array([g is not None and not g.is_empty for g in geoms], dtype=bool)
    if ok.any():
        p = shapely.point_on_surface(geoms[ok])
        xs, ys = shapely.get_x(p), shapely.get_y(p)
        out[ok] = [chave(x, y, passo) for x, y in zip(xs, ys, strict=True)]
    return out


def blocos_tocados(geom, passo: float = PASSO) -> list[str]:
    """Todos os blocos que a geometria toca (pela caixa e confirmando a interseção)."""
    if geom is None or geom.is_empty:
        return []
    x0, y0, x1, y1 = geom.bounds
    out = []
    for i in range(math.floor(x0 / passo), math.floor(x1 / passo) + 1):
        for j in range(math.floor(y0 / passo), math.floor(y1 / passo) + 1):
            ch = chave(i * passo, j * passo, passo)
            if shapely.intersects(geom, shapely.box(*caixa(ch, passo))):
                out.append(ch)
    return out
