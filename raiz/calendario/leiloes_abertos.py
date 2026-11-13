"""Índices públicos de imóveis rurais e prova do CAR no documento do próprio bem.

CSV, páginas e certidões permanecem em memória. A saída contém apenas links,
datas e identificadores de imóvel; nunca devolve preço, endereço ou titular.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
import unicodedata
from html import escape
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from raiz.calendario.modelos import CAR, SIGEF, UFS, normalizar_car, url_publica
from raiz.documentos.certidao.regras import normalizar_cns, normalizar_matricula

CAIXA = "https://venda-imoveis.caixa.gov.br"
BB = "https://www.seuimovelbb.com.br"
TRT16 = "https://www.trt16.jus.br"
MODOS = {"caixa_csv", "bb_imoveis"}
_DATA = r"\d{1,2}/\d{1,2}/\d{4}"
_MAT = re.compile(r"matr[ií]cula(?:\(s\)|s)?\s*(?:n[º°o.]*)?\s*[:.\-]?\s*([\d.]+[A-Z]?)", re.I)


def _normal(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


def _ufs(fonte: dict) -> set[str]:
    return {str(x).upper() for x in fonte.get("_ufs_processadas", UFS)} & UFS


def _caixa_detalhe(url: str) -> str | None:
    try:
        p = urlsplit(url_publica(url))
    except ValueError:
        return None
    ids = parse_qs(p.query).get("hdnimovel", [])
    if p.scheme != "https" or p.hostname != "venda-imoveis.caixa.gov.br":
        return None
    if p.path.lower() != "/sistema/detalhe-imovel.asp" or len(ids) != 1 or not re.fullmatch(r"\d{1,20}", ids[0]):
        return None
    return ids[0].lstrip("0") or "0"


def _bb_detalhe(url: str) -> bool:
    try:
        p = urlsplit(url_publica(url))
    except ValueError:
        return False
    return bool(
        p.scheme == "https"
        and p.hostname in {"www.seuimovelbb.com.br", "seuimovelbb.com.br"}
        and re.fullmatch(r"/imovel/id/\d{1,10}/?", p.path)
        and not p.query
    )


def sementes(fonte: dict, hoje: dt.date) -> list[str] | None:
    """O CSV nacional oficial evita depender de uma lista fixa de IDs de imóveis."""
    if fonte.get("modo") == "caixa_csv":
        return [f"{CAIXA}/listaweb/Lista_imoveis_geral.csv"]
    if fonte.get("modo") == "bb_imoveis":
        return [f"{BB}/"]
    if fonte.get("modo") == "trt16_leiloes":
        return [f"{TRT16}/servicos/publicacoes/leilao-judicial"]
    return None


def _links_csv(texto: str, fonte: dict) -> list[str]:
    leitor = csv.reader(io.StringIO(texto), delimiter=";")
    cabecalho = None
    for _ in range(10):
        linha = next(leitor, None)
        if linha is None:
            break
        normal = [_normal(c.strip().lstrip("\ufeff")) for c in linha]
        # CSV do portal pode vir Latin-1 sem charset. "descri" também reconhece
        # o cabeçalho quando o cliente anterior substituiu um acento inválido.
        if "link de acesso" in normal and "uf" in normal and any(c.startswith("descri") for c in normal):
            cabecalho = normal
            break
    if cabecalho is None:
        raise ValueError("índice de imóveis sem o cabeçalho público esperado")
    idx_uf, idx_link = cabecalho.index("uf"), cabecalho.index("link de acesso")
    idx_desc = next(i for i, c in enumerate(cabecalho) if c.startswith("descri"))
    links = []
    for linha in leitor:
        if len(linha) != len(cabecalho) or linha[idx_uf].strip().upper() not in _ufs(fonte):
            continue
        # Não usa bairro/endereço nem "zona rural" de imóvel urbano: a
        # descrição oficial precisa identificar o tipo do bem como rural.
        if not re.search(r"\b(?:imovel|terreno|propriedade)\s+rural\b", _normal(linha[idx_desc])):
            continue
        bruto = linha[idx_link].strip()
        if _caixa_detalhe(bruto) is not None:
            # Elimina parâmetros opcionais do portal; não transporta texto do CSV.
            codigo = parse_qs(urlsplit(bruto).query)["hdnimovel"][0]
            links.append(f"{CAIXA}/sistema/detalhe-imovel.asp?hdnimovel={codigo}")
    return list(dict.fromkeys(links))


def _escopo_caixa(texto: str) -> tuple[BeautifulSoup, str, str | None]:
    sopa = BeautifulSoup(texto, "html.parser")
    tipo = next(
        (p for p in sopa.find_all("p") if re.match(r"tipo de im[oó]vel\s*:", p.get_text(" ", strip=True), re.I)),
        None,
    )
    if tipo is None or not re.match(r"tipo de im[oó]vel\s*:\s*im[oó]vel rural\b", tipo.get_text(" ", strip=True), re.I):
        return sopa, "", None
    metadados = tipo.get_text(" ", strip=True)
    m = re.search(r"matr[ií]cula\(s\)\s*:\s*([\d.]+)\s*(?:comarca|of[ií]cio|inscri[cç][aã]o|$)", metadados, re.I)
    return sopa, metadados, normalizar_matricula(m[1]) if m else None


def _identificadores(texto: str) -> str:
    """Projeta somente identificadores; texto pessoal nunca sai do adaptador."""
    partes = []
    for m in CAR.finditer(texto):
        try:
            partes.append(normalizar_car(m[0]))
        except ValueError:
            continue
    m = _MAT.search(texto)
    if m:
        partes.append("Matrícula: " + normalizar_matricula(m[1]))
    cns = re.search(r"\bCNS\s*[:nº°.\s-]*([\d.\-]{5,9})", texto, re.I)
    if cns:
        normal = normalizar_cns(cns[1])
        if normal:
            partes.append("CNS: " + normal)
    for m in re.finditer(r"(?:SIGEF|c[oó]digo da parcela)\s*[:nº°.\s-]*(" + SIGEF.pattern + ")", texto, re.I):
        partes.append("SIGEF: " + m[1])
    return "; ".join(dict.fromkeys(partes))


def texto_evento(texto: str, url: str, fonte: dict) -> str | None:
    """Reúne a data e os IDs do mesmo anúncio, sem misturar cartões vizinhos."""
    modo = fonte.get("modo")
    if modo == "trt16_leiloes":
        return ""  # o índice reúne datas de vários editais; só o PDF identifica os bens
    if modo not in MODOS:
        return None
    if modo == "caixa_csv":
        if _caixa_detalhe(url) is None:
            return ""
        sopa, metadados, _ = _escopo_caixa(texto)
        if not metadados:
            return ""
        for tag in sopa(["nav", "header", "footer", "script", "style"]):
            tag.decompose()
        tx = sopa.get_text(" ", strip=True)
        datas = re.findall(r"Data do\s+([12])[º°o]?\s+Leil[aã]o\s*[-:]\s*(" + _DATA + ")", tx, re.I)
        if not datas:
            return ""  # venda direta/online não vira leilão sem data explícita
        descr = next(
            (
                p.get_text(" ", strip=True)
                for p in sopa.find_all("p")
                if re.match(r"descri[cç][aã]o\s*:", p.get_text(" ", strip=True), re.I)
            ),
            "",
        )
        ids = _identificadores(metadados + " " + descr)
    else:
        if not _bb_detalhe(url):
            return ""
        sopa = BeautifulSoup(texto, "html.parser")
        cab = next((h for h in sopa.find_all("h4") if _normal(h.get_text(strip=True)) == "descricao"), None)
        descricao = cab.find_next_sibling("div") if cab else None
        if descricao is None:
            return ""
        desc = descricao.get_text(" ", strip=True)
        if not re.search(r"\b(?:imovel|terreno|propriedade)\s+rural\b", _normal(desc)):
            return ""
        # A data do leilão é um h4 separado da descrição. Não aceita datas
        # citadas no histórico jurídico nem cartões recomendados do rodapé.
        datas = [
            (None, m[1])
            for h in sopa.find_all("h4")
            if (
                m := re.fullmatch(r"Data do leil[aã]o:\s*(" + _DATA + r")(?:\s+.*)?", h.get_text(" ", strip=True), re.I)
            )
        ]
        ids = _identificadores(desc)
    if not datas:
        return ""
    clausulas = "; ".join(f"Data do {i + 'º ' if i else ''}leilão: {d}" for i, d in dict.fromkeys(datas))
    return '<p data-calendario-evento="1">' + escape(f"Imóvel rural. {clausulas}. {ids}") + "</p>"


def documento_matricula(texto: str, url: str, fonte: dict) -> str | None:
    """Só o PDF que o portal associa explicitamente ao número do próprio imóvel."""
    if fonte.get("modo") != "caixa_csv" or (codigo := _caixa_detalhe(url)) is None:
        return None
    sopa, _, matricula = _escopo_caixa(texto)
    if not matricula:
        return None
    encontrados = []
    for a in sopa.select("a[onclick]"):
        m = re.fullmatch(r"(?:javascript:)?ExibeDoc\(\s*['\"]([^'\"]+)['\"]\s*\)\s*;?", a["onclick"], re.I)
        if not m:
            continue
        try:
            link = url_publica(urljoin(url, m[1]))
        except ValueError:
            continue
        p = urlsplit(link)
        arq = re.fullmatch(r"/editais/matricula/([A-Z]{2})/(\d{1,20})\.pdf", p.path, re.I)
        if p.scheme == "https" and p.hostname == "venda-imoveis.caixa.gov.br" and arq and not p.query:
            if arq[1].upper() in UFS and (arq[2].lstrip("0") or "0") == codigo:
                encontrados.append(link)
    distintos = list(dict.fromkeys(encontrados))
    return distintos[0] if len(distintos) == 1 else None


def complemento_matricula(texto: str, url: str, texto_pdf: str, url_pdf: str, fonte: dict) -> dict | None:
    """Confere o bem antes de aproveitar um CAR explicitamente impresso na certidão."""
    if documento_matricula(texto, url, fonte) != url_pdf:
        return None
    _, _, esperada = _escopo_caixa(texto)
    # A primeira matrícula do cabeçalho deve ser a do anúncio. Menções a
    # matrículas anteriores na cadeia dominial não bastam para comprovar o bem.
    prim = _MAT.search(texto_pdf[:3000])
    if not prim or normalizar_matricula(prim[1]) != esperada:
        return None
    try:
        codigos = {normalizar_car(m[0]) for m in CAR.finditer(texto_pdf)}
    except ValueError:
        return None
    if len(codigos) != 1:
        return None
    codigo = next(iter(codigos))
    uf = re.search(r"/matricula/([A-Z]{2})/", urlsplit(url_pdf).path, re.I)
    if not uf or codigo[:2] != uf[1].upper():
        return None
    return {"codigos_car": [codigo], "matricula": esperada, "car_fonte_url": url_pdf, "vinculo": "car"}


def _pdf_trt16(url: str) -> bool:
    try:
        p = urlsplit(url_publica(url))
    except ValueError:
        return False
    return bool(
        p.scheme == "https"
        and p.hostname == "www.trt16.jus.br"
        and p.path.startswith("/sites/portal/files/roles/leilao_unificado/")
        and p.path.lower().endswith(".pdf")
        and not p.query
    )


def texto_pdf(texto: str, url: str, fonte: dict) -> str | None:
    """Edital unificado: data do cabeçalho + descrição do próprio bem.

    Não trata a edição inteira como um imóvel. Partes processuais, avaliações,
    endereço e descrição livre nunca saem desta função. Formato alterado é
    falha explícita; ausência de CAR/CNS continua pendência de vínculo.
    """
    if fonte.get("modo") != "trt16_leiloes":
        return None
    if not _pdf_trt16(url):
        return ""
    anexos = re.split(r"(?im)^\s*ANEXO(?:\s+[IVX]+)?\s*$", texto, maxsplit=1)
    if len(anexos) != 2:
        raise ValueError("edital sem separação verificável entre cabeçalho e bens")
    cabecalho, anexo = anexos
    padrao_data = rf"(?:{_DATA}|\d{{1,2}}\s+de\s+[a-zç]+\s+de\s+\d{{4}})"
    datas = re.findall(r"DATA\s+DO\s+LEIL[AÃ]O\s*:\s*(?:Dia\s+)?(" + padrao_data + ")", cabecalho, re.I)
    if len(set(datas)) != 1:
        raise ValueError("edital sem data comum inequívoca do leilão")
    inicios = list(re.finditer(r"(?im)^\s*(\d{1,3})[.]\s*PROCESSO\s+N[º°O.]*\s*", anexo))
    if not inicios:
        raise ValueError("edital sem limites verificáveis entre bens")
    saida = []
    for i, inicio in enumerate(inicios):
        bloco = anexo[inicio.end() : inicios[i + 1].start() if i + 1 < len(inicios) else None]
        desc = re.search(
            r"Descri[cç][aã]o\s+do(?:\(s\))?\s+bem(?:\(ns\))?[^:\n]{0,140}[:\-]\s*(.*)", bloco, re.I | re.S
        )
        if not desc:
            continue
        descricao = " ".join(desc[1].split())
        # Um veículo depositado em zona rural não é imóvel rural. Exige o
        # tipo do bem no início da descrição, antes dos endereços/confrontantes.
        if not re.match(
            r"[-\s]*(?:0?1\s*(?:\(um\))?\s*|um\s+)?(?:im[oó]vel|terreno|propriedade)\s+rural\b", descricao, re.I
        ):
            continue
        mat = re.findall(
            r"matr[ií]cula\s*(?:registro\s+geral\s*)?(?:n[º°o.]*)?\s*[:.\-]?\s*([\d.]+[A-Z]?)",
            descricao,
            re.I,
        )
        # Há editais que identificam a matrícula como o número do registro,
        # sem repetir a palavra matrícula. Exige o contexto cartorial inteiro.
        registrada = re.search(
            r"im[oó]vel\s+rural\s+registrado\s+no\s+cart[oó]rio\s+de\s+registro\s+de\s+im[oó]veis"
            r".{0,180}?\bsob\s+o\s+n[º°o.]+\s*([\d.]+)",
            descricao,
            re.I,
        )
        if registrada:
            mat.append(registrada[1])
        matriculas = {normalizar_matricula(x) for x in mat}
        codigos = {m[0] for m in CAR.finditer(descricao)}
        # Mais de um imóvel na mesma descrição não autoriza escolher um CAR.
        ids = _identificadores(descricao) if len(codigos) <= 1 and len(matriculas) <= 1 else ""
        if len(matriculas) == 1 and not re.search(r"Matrícula:", ids):
            ids += "; Matrícula: " + next(iter(matriculas))
        if len(codigos) > 1:
            ids = ""
        # O número do item é identidade do bem; nenhuma parte processual
        # participa da chave ou do conteúdo persistido.
        conteudo = f"Imóvel rural. Data do leilão: {datas[0]}. {ids}"
        saida.append(f'<p data-calendario-evento="1" id="bem-{inicio[1]}">{escape(conteudo)}</p>')
    return "".join(saida)


def links(texto: str, url: str, fonte: dict) -> list[str] | None:
    modo = fonte.get("modo")
    if modo == "trt16_leiloes":
        sopa = BeautifulSoup(texto, "html.parser")
        encontrados = []
        for a in sopa.select("a[href]"):
            link = urljoin(url, a["href"])
            if _pdf_trt16(link):
                anos = re.findall(r"\b20\d{2}\b", unquote(urlsplit(link).path).replace("_", " "))
                encontrados.append((max(anos, default="0000"), link))
        if not encontrados:
            raise ValueError("tribunal sem o índice público de editais esperado")
        # O portal mantém o arquivo desde 2008. Lê diariamente os últimos
        # editais, ordenados por ano, preservando a ordem de publicação no ano.
        recentes = sorted(encontrados, key=lambda x: x[0], reverse=True)
        return list(dict.fromkeys(link for _, link in recentes))[: int(fonte.get("max_editais", 2))]
    if modo == "caixa_csv":
        if urlsplit(url).path.lower().endswith(".csv"):
            return _links_csv(texto, fonte)
        documento = documento_matricula(texto, url, fonte)
        return [documento] if documento else []
    if modo == "bb_imoveis":
        if _bb_detalhe(url):
            return []  # não herda documentos gerais do leiloeiro de outro bem
        sopa = BeautifulSoup(texto, "html.parser")
        destaques = sopa.select_one(".box-rural-highlights")
        if destaques is None:
            raise ValueError("portal sem o índice público de imóveis rurais esperado")
        out = []
        for card in destaques.select(".carta"):
            texto_card = card.get_text(" ", strip=True)
            ufs = set(re.findall(r",\s*([A-Z]{2})\b", texto_card)) & UFS
            if ufs and not ufs & _ufs(fonte):
                continue
            for a in card.select("a[href]"):
                link = urljoin(url, a["href"])
                if _bb_detalhe(link):
                    out.append(link)
        return list(dict.fromkeys(out))
    return None
