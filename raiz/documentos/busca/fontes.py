"""Fontes da busca de registros e editais. Cada fonte devolve itens com uma chave estável (para saber o que é novo) e
uma marca (o que, mudando, faz o item voltar à lista: situação do projeto, data de modificação da página).

verra         projetos no Brasil no registro da Verra (VCS): API antiga do registro; se ela não responder JSON, a
              página nova do registro pelo Firecrawl (ela só abre no navegador).
sfb           Serviço Florestal Brasileiro: editais em licitação (cada edital com a data de modificação) e busca no
              portal por edital, chamada pública e concessão, pela API do portal gov.br (Plone).
ideflor_bio   Ideflor-Bio (Pará): links de edital, aviso, resultado e concessão nas páginas de licitações e concessão.
dou           Diário Oficial da União: busca do portal in.gov.br por termos (requisição direta ou Firecrawl).
paginas       páginas extras do fontes.json: links novos com as palavras da lista.

Texto livre (resumo do DOU) passa pela máscara de CPF/CNPJ e pela tranca de nomes antes de ir para o relatório.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from raiz.documentos.busca import http
from raiz.documentos.privacidade import mascarar, tirar_nomes

CONFIG = Path(__file__).with_name("fontes.json")


def config(caminho: Path | None = None) -> dict:
    return json.loads((caminho or CONFIG).read_text(encoding="utf-8"))


@dataclass
class Item:
    fonte: str
    chave: str
    titulo: str
    url: str | None = None
    data: str | None = None  # AAAA-MM-DD (publicação ou modificação)
    orgao: str | None = None
    tipo: str = "edital"  # projeto | edital | publicacao | noticia | documento
    marca: str | None = None  # muda -> o item volta como "mudou"
    detalhe: dict = field(default_factory=dict)


@dataclass
class ResultadoFonte:
    fonte: str
    itens: list[Item] = field(default_factory=list)
    via: str | None = None
    erro: str | None = None
    avisos: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.erro is None


def _texto(s: str | None, limite: int = 300, nomes: bool = True) -> str | None:
    if not s:
        return None
    s = BeautifulSoup(html.unescape(s), "html.parser").get_text(" ", strip=True)
    s = mascarar(" ".join(s.split()))
    return (tirar_nomes(s) if nomes else s)[:limite]


def _data_iso(s: str | None) -> str | None:
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(s[:10], fmt).date().isoformat()
        except ValueError:
            pass
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) if m else None


# --- Verra -----------------------------------------------------------------------------------------------------------

STATUS_VERRA = [
    "Registered",
    "Under development",
    "Under validation",
    "Registration requested",
    "Registration and verification approval requested",
    "Verification approval requested",
    "Under verification",
    "On Hold",
    "Withdrawn",
    "Inactive",
    "Rejected",
    "Late to verify",
    "Crediting Period Renewal Requested",
    "Crediting Period Renewal and Verification Approval Requested",
    "Units Transferred from Approved GHG Program",
]


def _primeiro(d: dict, *chaves):
    for k in chaves:
        if d.get(k) not in (None, ""):
            return d[k]
    return None


def verra_de_json(dados, pais: str = "Brazil") -> list[Item]:
    linhas = dados.get("value") if isinstance(dados, dict) else dados
    out = []
    for r in linhas or []:
        p = _primeiro(r, "country", "countryName", "projectCountry") or ""
        if pais.lower() not in str(p).lower():
            continue
        pid = str(_primeiro(r, "resourceIdentifier", "projectId", "id") or "").strip()
        if not pid:
            continue
        status = _primeiro(r, "resourceStatus", "status", "projectStatus")
        categoria = _primeiro(r, "protocolCategories", "protocolSubCategories", "afoluActivities", "projectType")
        out.append(
            Item(
                fonte="verra",
                chave=pid,
                titulo=str(_primeiro(r, "resourceName", "projectName", "name") or f"Projeto {pid}"),
                url=f"https://registry.verra.org/app/projectDetail/VCS/{pid}",
                data=_data_iso(_primeiro(r, "createDate", "registrationDate", "updateDate", "statusDate")),
                orgao="Verra (VCS)",
                tipo="projeto",
                marca=str(status) if status else None,
                detalhe={
                    k: v
                    for k, v in dict(
                        situacao=status, categoria=categoria, estado=_primeiro(r, "region", "state")
                    ).items()
                    if v
                },
            )
        )
    return out


def verra_de_markdown(md: str, pais: str = "Brazil") -> list[Item]:
    """Tabela da página do registro (Firecrawl, markdown): | ID | Nome | Proponente | ... | País | Situação |."""
    out = []
    for linha in md.splitlines():
        if not linha.strip().startswith("|") or pais.lower() not in linha.lower():
            continue
        cel = [c.strip() for c in linha.strip().strip("|").split("|")]
        idx = next((i for i, c in enumerate(cel) if re.fullmatch(r"\[?\d{2,6}\]?(\(.*\))?", c)), None)
        if idx is None:
            continue
        pid = re.search(r"\d{2,6}", cel[idx]).group(0)
        nome = next((re.sub(r"\[(.*?)\]\(.*?\)", r"\1", c) for c in cel[idx + 1 :] if c and not c.isdigit()), pid)
        status = next((s for s in STATUS_VERRA for c in cel if c.lower() == s.lower()), None)
        out.append(
            Item(
                "verra",
                pid,
                nome,
                f"https://registry.verra.org/app/projectDetail/VCS/{pid}",
                orgao="Verra (VCS)",
                tipo="projeto",
                marca=status,
                detalhe={"situacao": status} if status else {},
            )
        )
    return out


def verra(cfg: dict, usar_firecrawl: bool = True) -> ResultadoFonte:
    res = ResultadoFonte("verra")
    pais = cfg.get("pais", "Brazil")
    try:
        p = http.direto(cfg["api"], metodo="POST", json_corpo={"program": "VCS"}, aceitar="application/json")
        dados = json.loads(p.texto)
        res.itens, res.via = verra_de_json(dados, pais), "direto"
        return res
    except (http.FalhaDownload, json.JSONDecodeError, ValueError) as ex:
        res.avisos.append(f"API antiga do registro não respondeu JSON ({str(ex)[:80]})")
    if not usar_firecrawl:
        res.erro = "o registro novo da Verra só abre no navegador: defina FIRECRAWL_API_KEY"
        return res
    try:
        p = http.firecrawl(cfg["pagina"], formato="markdown", esperar_ms=6000)
        res.itens, res.via = verra_de_markdown(p.texto, pais), "firecrawl"
        if not res.itens:
            res.erro = "a página do registro veio sem a tabela de projetos"
    except http.FalhaDownload as ex:
        res.erro = f"registro da Verra indisponível: {ex}"
    return res


# --- SFB (portal gov.br, Plone REST) ------------------------------------------------------------------------------


def sfb(cfg: dict, hoje: dt.date | None = None, sessao=None, palavras: list[str] | None = None) -> ResultadoFonte:
    hoje = hoje or dt.date.today()
    res = ResultadoFonte("sfb", via="direto")
    api = cfg["api"].rstrip("/")
    try:
        pasta = json.loads(http.direto(f"{api}/{cfg['editais']}", aceitar="application/json", sessao=sessao).texto)
    except (http.FalhaDownload, json.JSONDecodeError) as ex:
        res.erro = f"lista de editais do SFB indisponível: {ex}"
        return res
    for it in pasta.get("items") or []:
        url = it.get("@id")
        if not url:
            continue
        marca, data = it.get("modified"), _data_iso(it.get("effective"))
        try:  # a data de modificação de cada edital (o item da lista não traz)
            det = json.loads(
                http.direto(
                    url.replace("/florestal/pt-br", "/florestal/++api++/pt-br"),
                    aceitar="application/json",
                    sessao=sessao,
                ).texto
            )
            marca, data = det.get("modified") or marca, _data_iso(det.get("modified") or det.get("effective")) or data
        except (http.FalhaDownload, json.JSONDecodeError):
            res.avisos.append(f"sem data de modificação: {it.get('title')}")
        res.itens.append(
            Item(
                "sfb",
                url,
                it.get("title") or url,
                url,
                data,
                "Serviço Florestal Brasileiro",
                "edital",
                marca,
                {"lista": "editais em licitação"},
            )
        )
    vistos = {i.chave for i in res.itens}
    limite = hoje - dt.timedelta(days=int(cfg.get("dias", 60)))
    rx = re.compile("|".join(re.escape(p) for p in palavras), re.IGNORECASE) if palavras else None
    for termo in cfg.get("termos") or []:
        q = (
            f"{api}/@search?SearchableText={quote_plus(termo)}&sort_on=effective&sort_order=descending&b_size=25"
            "&metadata_fields=effective&metadata_fields=modified"
        )
        try:
            achados = json.loads(http.direto(q, aceitar="application/json", sessao=sessao).texto).get("items") or []
        except (http.FalhaDownload, json.JSONDecodeError) as ex:
            res.avisos.append(f"busca '{termo}' falhou: {ex}")
            continue
        for it in achados:
            url, data = it.get("@id"), _data_iso(it.get("effective"))
            ano = re.search(r"/noticias/(\d{4})/", url or "")
            if not url or url in vistos or not data or dt.date.fromisoformat(data) < limite:
                continue
            if ano and int(ano.group(1)) < hoje.year - 1:  # notícia antiga republicada na migração do portal
                continue
            if it.get("@type") == "Folder" or (rx and not rx.search(it.get("title") or "")):
                continue  # pasta do portal ou notícia sem edital, chamada, concessão etc. no título
            vistos.add(url)
            res.itens.append(
                Item(
                    "sfb",
                    url,
                    it.get("title") or url,
                    url,
                    data,
                    "Serviço Florestal Brasileiro",
                    "noticia" if it.get("@type") == "News Item" else "documento",
                    it.get("modified"),
                    {"termo": termo},
                )
            )
    return res


# --- páginas de links (Ideflor-Bio e extras) ----------------------------------------------------------------------


def links_da_pagina(texto_html: str, base: str, palavras: list[str]) -> list[tuple[str, str]]:
    sopa = BeautifulSoup(texto_html, "html.parser")
    for t in sopa(["header", "nav", "footer", "script", "style"]):
        t.decompose()
    rx = re.compile("|".join(re.escape(p) for p in palavras), re.IGNORECASE)
    out, vistos = [], set()
    for a in sopa.find_all("a", href=True):
        titulo = " ".join(a.get_text(" ", strip=True).split())
        url = urljoin(base, a["href"])
        if not url.startswith("http") or url in vistos or len(titulo) < 6:
            continue
        if any(x in url for x in ("whatsapp.com", "twitter.com", "facebook.com", "linkedin.com")):
            continue
        if rx.search(titulo) or rx.search(url.rsplit("/", 1)[-1]):
            vistos.add(url)
            out.append((titulo, url))
    return out


def _data_do_link(url: str) -> str | None:
    m = re.search(r"/uploads/(\d{4})/(\d{2})/", url)
    return f"{m.group(1)}-{m.group(2)}-01" if m else None


def paginas_de_links(
    fonte: str, orgao: str, urls: list[str], palavras: list[str], usar_firecrawl: bool = True
) -> ResultadoFonte:
    res = ResultadoFonte(fonte)
    vias = set()
    for url in urls:
        try:
            p = http.baixar(url, usar_firecrawl=usar_firecrawl, valida=lambda p: "<a" in p.texto)
        except http.FalhaDownload as ex:
            res.avisos.append(f"{url}: {ex}")
            continue
        vias.add(p.via)
        for titulo, link in links_da_pagina(p.texto, url, palavras):
            res.itens.append(
                Item(fonte, link, mascarar(titulo), link, _data_do_link(link), orgao, "edital", detalhe={"pagina": url})
            )
    res.via = ",".join(sorted(vias)) or None
    if not vias:
        res.erro = "nenhuma página respondeu"
    return res


def ideflor_bio(cfg: dict, palavras: list[str], usar_firecrawl: bool = True) -> ResultadoFonte:
    return paginas_de_links("ideflor_bio", "Ideflor-Bio (Pará)", cfg["paginas"], palavras, usar_firecrawl)


# --- Diário Oficial da União -------------------------------------------------------------------------------------

_DOU_JSON = re.compile(
    r'<script[^>]*id="_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params"[^>]*>(.*?)</script>', re.S
)


def dou_de_html(texto: str, termo: str) -> list[Item]:
    m = _DOU_JSON.search(texto)
    if not m:
        raise ValueError("página do DOU sem o bloco de resultados")
    out = []
    for r in json.loads(m.group(1)).get("jsonArray") or []:
        slug = r.get("urlTitle")
        if not slug:
            continue
        # título e órgão são institucionais: só a máscara de CPF/CNPJ; o resumo (trecho do ato) passa pela de nomes
        titulo = _texto(r.get("title") or r.get("titulo"), 200, nomes=False) or slug
        out.append(
            Item(
                "dou",
                slug,
                titulo,
                f"https://www.in.gov.br/web/dou/-/{slug}",
                _data_iso(r.get("pubDate")),
                _texto(r.get("hierarchyStr"), 160, nomes=False),
                "publicacao",
                detalhe={
                    k: v
                    for k, v in dict(
                        secao=r.get("pubName"),
                        tipo_ato=r.get("artType"),
                        edicao=r.get("editionNumber"),
                        pagina=r.get("numberPage"),
                        termo=termo,
                        resumo=_texto(r.get("content")),
                    ).items()
                    if v
                },
            )
        )
    return out


def dou(cfg: dict, usar_firecrawl: bool = True) -> ResultadoFonte:
    res = ResultadoFonte("dou")
    vistos, vias = set(), set()
    for termo in cfg.get("termos") or []:
        url = f"{cfg['busca']}?q={quote_plus(termo)}&s=todos&exactDate={cfg.get('periodo', 'mes')}&sortType=0"
        try:
            p = http.baixar(url, usar_firecrawl=usar_firecrawl, valida=lambda p: _DOU_JSON.search(p.texto) is not None)
            itens = dou_de_html(p.texto, termo)
        except (http.FalhaDownload, ValueError, json.JSONDecodeError) as ex:
            res.avisos.append(f"termo {termo}: {str(ex)[:160]}")
            continue
        vias.add(p.via)
        for it in itens:
            if it.chave not in vistos:
                vistos.add(it.chave)
                res.itens.append(it)
    res.via = ",".join(sorted(vias)) or None
    if not vias:
        dica = "" if usar_firecrawl else " (defina FIRECRAWL_API_KEY: o portal recusa conexão de fora do Brasil)"
        res.erro = "o Diário Oficial não respondeu" + dica
    return res


def todas(cfg: dict | None = None, usar_firecrawl: bool = True, so: list[str] | None = None) -> list[ResultadoFonte]:
    cfg = cfg or config()
    palavras = cfg.get("palavras") or []
    fc = usar_firecrawl and http.chave_firecrawl() is not None
    tarefas = {
        "verra": lambda: verra(cfg["verra"], fc),
        "sfb": lambda: sfb(cfg["sfb"], palavras=palavras),
        "ideflor_bio": lambda: ideflor_bio(cfg["ideflor_bio"], palavras, fc),
        "dou": lambda: dou(cfg["dou"], fc),
    }
    for extra in cfg.get("paginas") or []:
        nome = extra.get("nome") or extra["url"]
        tarefas[nome] = lambda e=extra, n=nome: paginas_de_links(
            n, e.get("orgao") or n, [e["url"]], e.get("palavras") or palavras, fc
        )
    out = []
    for nome, fazer in tarefas.items():
        if so and nome not in so:
            continue
        try:
            out.append(fazer())
        except Exception as ex:  # noqa: BLE001 - uma fonte quebrada não derruba as outras
            out.append(ResultadoFonte(nome, erro=f"falha inesperada: {type(ex).__name__}: {str(ex)[:160]}"))
    return out
