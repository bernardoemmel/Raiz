"""Números, dinheiro e datas no jeito brasileiro (1.234,5; R$ 1.234; 12/11/2026)."""

from __future__ import annotations

import datetime as dt


def fmt_num(x, casas: int = 0, vazio: str = "—") -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return vazio
    if v != v:
        return vazio
    s = f"{v:,.{casas}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def fmt_moeda(x, moeda: str = "BRL") -> str:
    if x is None:
        return "—"
    simbolo = {"BRL": "R$", "USD": "US$"}.get(moeda, moeda)
    return f"{simbolo} {fmt_num(x)}"


def fmt_data(d: dt.date | str | None = None) -> str:
    d = d or dt.date.today()
    if isinstance(d, str):
        d = dt.date.fromisoformat(d[:10])
    return d.strftime("%d/%m/%Y")
