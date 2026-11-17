"""Regra de matrícula por época (TJPA hoje): compara a data de abertura e a área da matrícula com o limite
constitucional para alienar terra pública daquela época (raiz/estaduais/matriculas.yaml, campo `periodos`).

Usa a certidão de inteiro teor, que só entra com autorização do dono (fluxo de documentos). Sem certidão, a triagem
só marca a ressalva por área e o item do checklist (raiz/estaduais/cruzamento.py).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from raiz.estaduais.cruzamento import matriculas


@dataclass(frozen=True)
class Avaliacao:
    situacao: str  # suspeita | dentro_do_limite | sem_regra | sem_dados
    limite_ha: float | None
    regra: str | None
    texto: str


def _data(v) -> dt.date | None:
    if v in (None, ""):
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v)[:10])


def _ha(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def regra_por_epoca(uf: str) -> dict | None:
    return next((m for m in matriculas() if m.get("uf") == uf.upper() and m.get("periodos")), None)


def avaliar(uf: str, aberta_em, area_ha: float | None) -> Avaliacao:
    """Matrícula aberta em `aberta_em` com `area_ha`: suspeita quando passa do limite da época."""
    m = regra_por_epoca(uf)
    if not m:
        return Avaliacao("sem_regra", None, None, "UF sem regra de matrícula por época.")
    data = _data(aberta_em)
    if data is None or area_ha is None:
        return Avaliacao("sem_dados", None, m["id"], "Falta a data de abertura ou a área da matrícula na certidão.")
    for p in m["periodos"]:
        de, ate = _data(p["de"]), _data(p.get("ate"))
        if data >= de and (ate is None or data <= ate):
            lim = float(p["limite_ha"])
            if area_ha > lim:
                txt = (f"Matrícula de {_ha(area_ha)} ha aberta em {data:%d/%m/%Y}, acima do limite de {_ha(lim)} ha da "
                       f"época: conferir bloqueio ou cancelamento ({m['tribunal']}).")  # fmt: skip
                return Avaliacao("suspeita", lim, m["id"], txt)
            return Avaliacao("dentro_do_limite", lim, m["id"], "Área dentro do limite constitucional da época.")
    return Avaliacao("dentro_do_limite", None, m["id"], "Matrícula anterior a 16/07/1934: fora da regra.")
