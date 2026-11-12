"""Baixar página: requisição direta e, quando falha ou a página só abre no navegador, o Firecrawl (API hospedada).

O Firecrawl entra só pela API (https://api.firecrawl.dev), com FIRECRAWL_API_KEY. Não instalar o Firecrawl no
servidor: o código dele é AGPL, licença proibida na Raíz. O pedido ao Firecrawl sai com localização Brasil, porque o
Diário Oficial da União recusa conexão de fora.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

from raiz.documentos.config import chave_firecrawl

log = logging.getLogger(__name__)

AGENTE = "Mozilla/5.0 (compatible; busca-editais/1.0)"
FIRECRAWL_URL = "https://api.firecrawl.dev/v2/scrape"


class FalhaDownload(Exception):
    pass


@dataclass
class Pagina:
    texto: str
    via: str  # direto | firecrawl
    url: str
    status: int | None = None


def direto(
    url: str,
    *,
    metodo: str = "GET",
    json_corpo=None,
    aceitar: str | None = None,
    timeout: float = 45,
    sessao: requests.Session | None = None,
) -> Pagina:
    s = sessao or requests
    cab = {"User-Agent": AGENTE, "Accept-Language": "pt-BR,pt;q=0.9"}
    if aceitar:
        cab["Accept"] = aceitar
    try:
        r = s.request(metodo, url, json=json_corpo, headers=cab, timeout=timeout)
    except requests.RequestException as ex:
        raise FalhaDownload(f"{type(ex).__name__}: {str(ex)[:160]}") from ex
    if r.status_code >= 400:
        raise FalhaDownload(f"HTTP {r.status_code}")
    r.encoding = r.encoding or "utf-8"
    return Pagina(r.text, "direto", url, r.status_code)


def firecrawl(
    url: str,
    *,
    formato: str = "rawHtml",
    esperar_ms: int = 2500,
    timeout: float = 120,
    sessao: requests.Session | None = None,
) -> Pagina:
    chave = chave_firecrawl()
    if not chave:
        raise FalhaDownload("sem FIRECRAWL_API_KEY")
    s = sessao or requests
    corpo = {
        "url": url,
        "formats": [formato],
        "onlyMainContent": False,
        "waitFor": esperar_ms,
        "location": {"country": "BR", "languages": ["pt-BR"]},
    }
    try:
        r = s.post(FIRECRAWL_URL, json=corpo, headers={"Authorization": f"Bearer {chave}"}, timeout=timeout)
    except requests.RequestException as ex:
        raise FalhaDownload(f"Firecrawl: {type(ex).__name__}") from ex
    if r.status_code >= 400:
        raise FalhaDownload(f"Firecrawl HTTP {r.status_code}")
    dados = (r.json() or {}).get("data") or {}
    texto = dados.get(formato) or dados.get("html") or dados.get("markdown")
    if not texto:
        raise FalhaDownload("Firecrawl devolveu página vazia")
    return Pagina(texto, "firecrawl", url, (dados.get("metadata") or {}).get("statusCode"))


def baixar(url: str, *, usar_firecrawl: bool = True, formato_firecrawl: str = "rawHtml", valida=None, **kw) -> Pagina:
    """Direto primeiro; se falhar (ou `valida(pagina)` disser que não é o que se espera), tenta o Firecrawl."""
    erro = None
    try:
        p = direto(url, **kw)
        if valida is None or valida(p):
            return p
        erro = "a página veio sem o conteúdo esperado"
    except FalhaDownload as ex:
        erro = str(ex)
    if not usar_firecrawl:
        raise FalhaDownload(erro)
    log.info("direto falhou em %s (%s): tentando o Firecrawl", url, erro)
    try:
        p = firecrawl(url, formato=formato_firecrawl)
    except FalhaDownload as ex:
        raise FalhaDownload(f"{erro}; {ex}") from ex
    if valida is not None and not valida(p):
        raise FalhaDownload(f"{erro}; Firecrawl também veio sem o conteúdo esperado")
    return p
