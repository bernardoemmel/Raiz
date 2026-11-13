"""Descoberta dos documentos públicos de diários estaduais, sem executar JavaScript.

Os adaptadores retornam somente URLs e parâmetros fechados de consulta. Conteúdo
bruto, nomes, CPF e CNPJ nunca saem da memória do coletor.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from raiz.calendario.modelos import url_publica

MODOS = {"diario_portal", "diario_ma", "diario_pi", "diario_links", "diario_ac", "diario_rr", "diario_ce"}


def _dias(fonte: dict) -> int:
    return max(1, min(int(fonte.get("dias", 7)), 31))


def _data(valor: str) -> dt.date | None:
    try:
        if re.fullmatch(r"\d{2}/\d{2}/\d{4}", valor):
            return dt.datetime.strptime(valor, "%d/%m/%Y").date()
        return dt.date.fromisoformat(valor)
    except (ValueError, TypeError):
        return None


def _na_janela(dia: dt.date | None, fonte: dict, hoje: dt.date) -> bool:
    return dia is not None and hoje - dt.timedelta(days=_dias(fonte) - 1) <= dia <= hoje


def _seguras(links: list[str], fonte: dict) -> list[str]:
    hosts = {urlsplit(u).hostname for u in fonte["urls"]} | set(fonte.get("hosts", []))
    saida = []
    for link in links:
        try:
            u = url_publica(link)
        except ValueError:
            continue
        if urlsplit(u).hostname in hosts and u not in saida:
            saida.append(u)
    return saida


def sementes(fonte: dict, hoje: dt.date) -> list[str] | None:
    modo = fonte.get("modo")
    if modo not in MODOS:
        return None
    if modo == "diario_portal":
        base = fonte["urls"][0].rstrip("/")
        if fonte.get("indice") == "ultimas":
            return [f"{base}/apifront/portal/edicoes/ultimas_edicoes.json"]
        # Mesma rota pública usada pelo seletor de data dos portais GO/AP/BA.
        # Consulta cada dia, incluindo suplementos, sem presumir um único jornal.
        return [
            f"{base}/apifront/portal/edicoes/edicoes_from_data/{(hoje - dt.timedelta(days=i)).isoformat()}.json"
            for i in range(_dias(fonte))
        ]
    if modo == "diario_ce":
        base = fonte["urls"][0].rstrip("/")
        # O primeiro caderno informa na capa quantos cadernos compõem a edição.
        # Não presumimos três volumes, nem que fins de semana não publiquem.
        return [
            f"{base}/{d:%Y%m%d}/do{d:%Y%m%d}p01.pdf" for i in range(_dias(fonte)) for d in [hoje - dt.timedelta(days=i)]
        ]
    return list(fonte["urls"])


def preparacao(fonte: dict, url: str) -> str | None:
    """RR entrega o PDF após o formulário público; a sessão pertence ao coletor."""
    if fonte.get("modo") == "diario_rr" and urlsplit(url).path == "/_visualizar-doe/":
        return fonte["urls"][0]
    return None


def pedido(fonte: dict, url: str, texto_preparatorio: str | None = None) -> dict | None:
    if fonte.get("modo") == "diario_rr" and urlsplit(url).path == "/_visualizar-doe/":
        documento = parse_qs(urlsplit(url).query).get("doe", [""])[0]
        if not re.fullmatch(r"20\d{2}/\d{2}/doe-20\d{6}(?:-suplemento)?\.pdf", documento, re.I):
            raise ValueError("documento público do diário inválido")
        campos = {"doe", "ipconexao", "dia", "mes", "ano", "hora"}
        for form in BeautifulSoup(texto_preparatorio or "", "html.parser").select("form"):
            dados = {i.get("name"): i.get("value", "") for i in form.select("input[name]")}
            if dados.get("doe") != documento:
                continue
            action = urljoin(fonte["urls"][0], form.get("action", ""))
            if urlsplit(action).path != "/_visualizar-doe/" or not _seguras([action], fonte):
                raise ValueError("formulário público de edição inválido")
            if not campos <= dados.keys():
                raise ValueError("formulário público de edição incompleto")
            # Valores observados no formulário público, inclusive o horário/IP
            # de sessão, só transitam em memória; nunca são gravados ou logados.
            return {"metodo": "POST", "dados_form": {k: dados[k] for k in campos}}
        raise ValueError("a edição não está no índice público consultado")
    if fonte.get("modo") != "diario_pi" or urlsplit(url).path != "/doe/Api/listardiarios.json":
        return None
    pagina = int(parse_qs(urlsplit(url).query).get("pagina", ["0"])[0])
    if not 0 <= pagina <= 100:
        raise ValueError("paginação do diário inválida")
    return {"metodo": "POST", "json_corpo": {"draw": 1, "start": pagina * 100, "length": 100, "numero": "", "dia": ""}}


def _portal(fonte: dict, texto: str, hoje: dt.date) -> list[str]:
    dados = json.loads(texto)
    if not isinstance(dados, dict) or dados.get("erro") is not False or not isinstance(dados.get("itens"), list):
        raise ValueError("índice público de edições inválido")
    base = fonte.get("base_documentos", fonte["urls"][0]).rstrip("/")
    saida = []
    for item in dados["itens"]:
        if not isinstance(item, dict):
            raise ValueError("edição pública inválida")
        if not _na_janela(_data(str(item.get("data", ""))), fonte, hoje):
            continue
        eid = str(item.get("id", ""))
        if not re.fullmatch(r"[1-9]\d{0,9}", eid):
            raise ValueError("identificador público de edição inválido")
        # BA libera consulta HTML, mas exige cadastro para PDF e FLIP.
        if fonte.get("formato_edicao") == "html":
            saida.append(f"{base}/ver-html/{eid}/")
        else:
            saida.append(f"{base}/portal/edicoes/download/{eid}")
    return saida


def _piaui(fonte: dict, url: str, texto: str, hoje: dt.date) -> list[str]:
    dados = json.loads(texto)
    if not isinstance(dados, dict) or not isinstance(dados.get("data"), list):
        raise ValueError("índice público do diário inválido")
    linhas, datas, saida = dados["data"], [], []
    base = fonte["base_documentos"]
    for linha in linhas:
        if not isinstance(linha, list) or len(linha) < 3:
            raise ValueError("edição pública inválida")
        dia = _data(str(linha[2]))
        if dia:
            datas.append(dia)
        if not _na_janela(dia, fonte, hoje):
            continue
        for a in BeautifulSoup(str(linha[0]), "html.parser").select("a[href]"):
            link = urljoin(base, a["href"])
            if urlsplit(link).path.lower().endswith(".pdf"):
                saida.append(link)
    pagina = int(parse_qs(urlsplit(url).query).get("pagina", ["0"])[0])
    total = int(dados.get("recordsFiltered", dados.get("recordsTotal", 0)))
    # Só continua enquanto a página ainda alcança a janela. O coletor aplica seu
    # limite global e anuncia cobertura parcial se sobrarem URLs na fila.
    if linhas and datas and min(datas) >= hoje - dt.timedelta(days=_dias(fonte) - 1) and (pagina + 1) * 100 < total:
        saida.append(urlsplit(url)._replace(query=urlencode({"pagina": pagina + 1})).geturl())
    return saida


def _maranhao(fonte: dict, url: str, texto: str, hoje: dt.date) -> list[str]:
    sopa = BeautifulSoup(texto, "html.parser")
    saida = []
    for a in sopa.select("[onclick]"):
        m = re.match(r"setModal\(['\"]((?:EX|TE|EE|ET)(\d{8}))['\"]", a.get("onclick", ""))
        if not m:
            continue
        try:
            dia = dt.datetime.strptime(m[2], "%Y%m%d").date()
        except ValueError:
            continue
        if _na_janela(dia, fonte, hoje):
            saida.append(urljoin(url, "download.php") + "?" + urlencode({"arq": m[1]}))
    if not saida:
        raise ValueError("o índice do diário não apresentou edições da janela")
    return saida


def _roraima(fonte: dict, url: str, texto: str, hoje: dt.date) -> list[str]:
    saida = []
    for form in BeautifulSoup(texto, "html.parser").select("form"):
        campo = form.select_one('input[name="doe"]')
        if campo is None:
            continue
        documento = campo.get("value", "")
        m = re.fullmatch(r"20\d{2}/\d{2}/doe-(20\d{2})(\d{2})(\d{2})(?:-suplemento)?\.pdf", documento, re.I)
        if not m or not _na_janela(_data("-".join(m.groups())), fonte, hoje):
            continue
        action = urljoin(url, form.get("action", ""))
        if urlsplit(action).path == "/_visualizar-doe/":
            saida.append(action + "?" + urlencode({"doe": documento}))
    if not saida:
        raise ValueError("o índice público não apresentou formulários de edição reconhecíveis")
    return saida


def _links_pdf(fonte: dict, url: str, texto: str, hoje: dt.date) -> list[str]:
    sopa = BeautifulSoup(texto, "html.parser")
    saida = []
    for a in sopa.select("a[href]"):
        link = urljoin(url, a["href"])
        caminho = urlsplit(link).path
        if fonte.get("modo") == "diario_ac" and caminho.endswith("/download.php"):
            saida.append(link)
            continue
        if not caminho.lower().endswith(".pdf"):
            continue
        if caminho.rsplit("/", 1)[-1] in fonte.get("arquivos_correntes", []):
            saida.append(link)
            continue
        iso = re.search(r"(20\d{2})[-./](\d{2})[-./](\d{2})", caminho)
        br = re.search(r"(\d{2})[-./](\d{2})[-./](20\d{2})", caminho)
        valor = "-".join(iso.groups()) if iso else ("-".join(reversed(br.groups())) if br else "")
        if _na_janela(_data(valor), fonte, hoje):
            saida.append(link)
    if not saida:
        raise ValueError("o índice público não apresentou documentos de edição reconhecíveis")
    return saida


def descobrir(fonte: dict, url: str, texto: str, hoje: dt.date) -> list[str] | None:
    modo = fonte.get("modo")
    if modo not in MODOS:
        return None
    # Downloads PDF são processados diretamente; só os índices têm descoberta.
    if modo == "diario_portal":
        links = _portal(fonte, texto, hoje) if "/apifront/" in urlsplit(url).path else []
    elif modo == "diario_pi":
        links = _piaui(fonte, url, texto, hoje) if "/Api/listardiarios.json" in urlsplit(url).path else []
    elif modo == "diario_ma":
        links = _maranhao(fonte, url, texto, hoje)
    elif modo == "diario_rr":
        links = _roraima(fonte, url, texto, hoje)
    else:
        links = _links_pdf(fonte, url, texto, hoje)
    return _seguras(links, fonte)


def descobrir_pdf(fonte: dict, url: str, texto: str, hoje: dt.date) -> list[str]:
    """Volumes anunciados na capa do próprio DOE CE, sem executar o PDF."""
    if fonte.get("modo") != "diario_ce":
        return []
    caminho = re.fullmatch(r"/PDF/(20\d{6})/do(20\d{6})p(\d{2})\.pdf", urlsplit(url).path)
    if not caminho or caminho[1] != caminho[2]:
        raise ValueError("caminho de edição do diário inválido")
    try:
        dia = dt.datetime.strptime(caminho[1], "%Y%m%d").date()
    except ValueError as exc:
        raise ValueError("data da edição do diário inválida") from exc
    if not _na_janela(dia, fonte, hoje):
        return []
    capa = re.search(r"Caderno\s+(\d{1,2})\s*/\s*(\d{1,2})\b", texto[:1200], re.I)
    if not capa or int(capa[1]) != int(caminho[3]) or not 1 <= int(capa[1]) <= int(capa[2]) <= 20:
        raise ValueError("a capa não confirmou a quantidade de cadernos da edição")
    base = fonte["urls"][0].rstrip("/")
    return _seguras([f"{base}/{dia:%Y%m%d}/do{dia:%Y%m%d}p{n:02d}.pdf" for n in range(1, int(capa[2]) + 1)], fonte)
