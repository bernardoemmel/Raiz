"""Índice público da IOEPA: edições ordinárias e extras por data, sem busca frágil."""

from __future__ import annotations

import datetime as dt
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

_EDICAO = re.compile(r"(?P<ano>\d{4})\.(?P<mes>\d{2})\.(?P<dia>\d{2})\.(?:DOE|EXTRA)\.pdf$", re.I)


def sementes(fonte: dict, hoje: dt.date) -> list[str] | None:
    if fonte.get("modo") != "diario_pa":
        return None
    desde = hoje - dt.timedelta(days=int(fonte.get("dias", 7)))
    base = fonte["urls"][0].rstrip("/")
    return [f"{base}/{ano}/" for ano in sorted({hoje.year, desde.year}, reverse=True)]


def links(texto: str, url: str, fonte: dict, hoje: dt.date) -> list[str] | None:
    if fonte.get("modo") != "diario_pa":
        return None
    desde = hoje - dt.timedelta(days=int(fonte.get("dias", 7)))
    encontrados = {}
    for a in BeautifulSoup(texto, "html.parser").find_all("a", href=True):
        link = urljoin(url, a["href"])
        m = _EDICAO.fullmatch(urlsplit(link).path.rsplit("/", 1)[-1])
        if not m:
            continue
        try:
            dia = dt.date(int(m["ano"]), int(m["mes"]), int(m["dia"]))
        except ValueError:
            continue
        if desde <= dia <= hoje:
            encontrados[link] = dia
    # A allowlist e os limites de resposta/páginas continuam no coletor central.
    return sorted(encontrados, key=lambda u: (encontrados[u], u), reverse=True)
