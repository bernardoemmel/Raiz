"""Coleta diária limitada às fontes oficiais do manifesto.

Só datas explicitamente ligadas a um evento entram no calendário. Publicação,
modificação e anos soltos não viram prazo. HTML/PDF ficam em memória; o banco
recebe campos fechados e identificadores de imóvel, nunca o texto do edital.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import logging
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

import requests
import yaml
from bs4 import BeautifulSoup
from pypdf import PdfReader

from raiz.calendario import atos_pdf, diario_pa, diarios, leiloes_abertos, ocr_pdf
from raiz.calendario.modelos import CAR, SIGEF, Evento, FonteEstado, identificador, normalizar_car, url_publica
from raiz.documentos.busca import http
from raiz.documentos.certidao.regras import normalizar_cns, normalizar_matricula

MANIFESTO = Path(__file__).with_name("fontes.yaml")
MAX_BYTES = 64 * 1024 * 1024
# PDFs públicos podem conter pessoas até em objetos malformados. O pypdf pode
# registrar esses objetos completos em warnings; a coleta só divulga falha fixa.
logging.getLogger("pypdf").setLevel(logging.CRITICAL + 1)
MESES = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "dec": 12,
}
_MES = "(?:" + "|".join(MESES) + ")"
_DATA = (
    rf"(?:\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}[/.-]\d{{1,2}}[/.-]\d{{4}}|"
    rf"\d{{1,2}}\s+(?:de\s+)?{_MES}\s+(?:de\s+)?\d{{4}}|{_MES}\s+\d{{1,2}},?\s+\d{{4}})"
)
DATAS = re.compile(rf"\b{_DATA}\b")
_DOU = re.compile(
    r'<script[^>]*id="_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params"[^>]*>(.*?)</script>', re.S
)


def _normal(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


def _data(texto: str) -> dt.date | None:
    texto = _normal(texto).strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto):
            return dt.date.fromisoformat(texto)
        partes = re.split(r"[\s/,.-]+", re.sub(r"\bde\b", "", texto))
        partes = [x for x in partes if x]
        if partes[0] in MESES:
            mes, dia, ano = MESES[partes[0]], int(partes[1]), int(partes[2])
        else:
            dia, ano = int(partes[0]), int(partes[2])
            mes = MESES[partes[1]] if partes[1] in MESES else int(partes[1])
        return dt.date(ano, mes, dia) if 2000 <= ano <= 2100 else None
    except (ValueError, IndexError):
        return None


def fontes(caminho: Path | None = None) -> list[dict]:
    itens = yaml.safe_load((caminho or MANIFESTO).read_text(encoding="utf-8"))["fontes"]
    if len({x["id"] for x in itens}) != len(itens):
        raise ValueError("fonte duplicada no manifesto")
    for f in itens:
        for u in f["urls"]:
            url_publica(u)
    return itens


def _hosts(fonte: dict) -> set[str]:
    return {urlsplit(u).hostname for u in fonte["urls"]} | set(fonte.get("hosts", []))


def _permitida(url: str, fonte: dict) -> bool:
    try:
        return urlsplit(url_publica(url)).hostname in _hosts(fonte)
    except ValueError:
        return False


class _Sessao:
    """O HTTP da busca semanal com limite de bytes e redirecionamentos no mesmo manifesto."""

    def __init__(self, fonte):
        self.fonte = fonte
        self.resposta = None
        self.sessao = requests.Session()

    def _requisitar(self, metodo, url, **kw):
        """Só repete leituras transitórias; 401/403 nunca provocam troca de identidade."""
        for tentativa in range(3):
            try:
                r = self.sessao.request(metodo, url, stream=True, allow_redirects=False, **kw)
            except (requests.Timeout, requests.ConnectionError):
                if tentativa == 2 or metodo.upper() not in {"GET", "HEAD"}:
                    raise
                time.sleep(2 ** (tentativa + 1))
                continue
            if r.status_code not in {429, 500, 502, 503, 504} or tentativa == 2:
                return r
            if metodo.upper() not in {"GET", "HEAD"}:
                return r
            espera = _espera_retry(r.headers.get("Retry-After"), tentativa)
            # Não encurta Retry-After. Esperas longas ficam para a próxima rodada,
            # evitando manter um worker preso ou fazer outra chamada antes da hora.
            if espera > 60:
                return r
            r.close()
            time.sleep(espera)
        raise http.FalhaDownload("fonte indisponível após tentativas limitadas")

    def request(self, metodo, url, **kw):
        for _ in range(5):
            if not _permitida(url, self.fonte):
                raise AcessoRestrito("redirecionamento fora das fontes permitidas")
            r = self._requisitar(metodo, url, **kw)
            if r.is_redirect:
                url = urljoin(url, r.headers.get("Location", ""))
                r.close()
                continue
            blocos, total, inicio = [], 0, time.monotonic()
            limite = min(MAX_BYTES, int(self.fonte.get("max_bytes", 16 * 1024 * 1024)))
            try:
                for bloco in r.iter_content(65536):
                    total += len(bloco)
                    if total > limite or time.monotonic() - inicio > 90:
                        raise http.FalhaDownload("documento acima do limite de leitura")
                    blocos.append(bloco)
            finally:
                r.close()
            r._content = b"".join(blocos)
            self.resposta = r
            return r
        raise http.FalhaDownload("redirecionamentos em excesso")


class AcessoRestrito(http.FalhaDownload):
    """O acesso exige intervenção da fonte; não usar um intermediário para contorná-lo."""


def _espera_retry(valor: str | None, tentativa: int, agora: dt.datetime | None = None) -> float:
    if valor:
        try:
            return max(0.0, float(valor))
        except ValueError:
            try:
                prazo = parsedate_to_datetime(valor)
                if prazo.tzinfo is None:
                    prazo = prazo.replace(tzinfo=dt.UTC)
                return max(0.0, (prazo - (agora or dt.datetime.now(dt.UTC))).total_seconds())
            except (TypeError, ValueError, OverflowError):
                pass
    return float(2 ** (tentativa + 1))


def baixar(url: str, fonte: dict) -> tuple[str, str]:
    """HTML ou texto PDF, sempre em memória. Sem driblar login, CAPTCHA ou bloqueio."""
    s = _Sessao(fonte)
    pedido = {}
    try:
        preparacao = diarios.preparacao(fonte, url)
        indice = http.direto(preparacao, timeout=25, sessao=s).texto if preparacao else None
        pedido = diarios.pedido(fonte, url, indice) or {}
        if "dados_form" in pedido:
            r = s.request(
                pedido.get("metodo", "POST"),
                url,
                data=pedido["dados_form"],
                headers={"User-Agent": http.AGENTE, "Accept-Language": "pt-BR,pt;q=0.9"},
                timeout=25,
            )
            if r.status_code >= 400:
                raise http.FalhaDownload(f"HTTP {r.status_code}")
            r.encoding = r.encoding or "utf-8"
            pagina = http.Pagina(r.text, "direto", url, r.status_code)
        else:
            pagina = http.direto(url, timeout=25, sessao=s, **pedido)
        r = s.resposta
        if fonte.get("modo") == "caixa_csv" and urlsplit(url).path.lower().endswith(".csv"):
            # O CSV institucional usa Windows-1252/Latin-1. Nunca deixar o decode
            # com replacement trocar “Imóvel rural” por “Im�vel” e esvaziar a busca.
            for codificacao in ("utf-8-sig", "cp1252", "latin-1"):
                try:
                    return r.content.decode(codificacao), "html"
                except UnicodeDecodeError:
                    continue
        if r.content.startswith(b"%PDF"):
            pdf = PdfReader(io.BytesIO(r.content))
            if len(pdf.pages) > 250:
                raise http.FalhaDownload("PDF acima do limite de páginas")
            paginas = [p.extract_text() or "" for p in pdf.pages]
            sem_texto = [i + 1 for i, p in enumerate(paginas) if len(p.strip()) < 200 and len(pdf.pages[i].images) > 0]
            if sem_texto:
                if not fonte.get("ocr"):
                    raise http.FalhaDownload("PDF escaneado requer OCR habilitado para a fonte")
                reconhecidas = ocr_pdf.extrair(r.content, sem_texto)
                for i, texto in reconhecidas.items():
                    paginas[i - 1] = texto
            return "\n\f\n".join(paginas), "pdf"
        if re.search(r"just a moment|verify you are human|captcha|access denied", pagina.texto[:3000], re.I):
            raise AcessoRestrito("fonte exige acesso interativo")
        return pagina.texto, "html"
    except AcessoRestrito:
        raise
    except http.FalhaDownload:
        if s.resposta is not None and s.resposta.status_code in {401, 403, 429}:
            raise AcessoRestrito(f"fonte indisponível: HTTP {s.resposta.status_code}") from None
        if (
            fonte.get("modo") == "djen"
            or pedido.get("metodo") == "POST"
            or not http.chave_firecrawl()
            or urlsplit(url).path.lower().endswith(".pdf")
        ):
            raise
        # A mesma API hospedada já usada pela busca semanal; não instala código AGPL.
        return http.firecrawl(url, timeout=60).texto, "html"
    finally:
        s.sessao.close()


def _tipo(texto: str, fonte: dict) -> str | None:
    t = _normal(texto)
    if re.search(r"credenciamento de leiloeir|leiloeir.{0,30}credenciad|vaga de emprego|open tender", t):
        return None
    if fonte["id"] == "sbti" and re.search(r"\btender\b|freelance|secondment|recruit|vacanc|job opportunit|hiring", t):
        return None  # a página Take part mistura consultas e contratação de serviços
    if "profloresta" in t:
        return "profloresta"
    if "fundo amazonia" in t or "restaura amazonia" in t:
        return "fundo_amazonia"
    if re.search(r"concess[aã]o florestal|concessoes florestais", t):
        return "concessao"
    if "rural" in t or CAR.search(texto) or re.search(r"\bsigef\b", t):
        if "leilao" in t or "hasta publica" in t:
            return "leilao_imovel"
        if "penhora" in t:
            return "penhora"
    if "leilao" in t and ("carbono" in t or "credito" in t):
        return "leilao_credito"
    if "sbce" in t:
        return "sbce"
    # O mesmo portal florestal publica pregões de máquinas, escritório e obras.
    # Sem menção explícita à concessão florestal, o órgão não define o tipo do ato.
    return fonte.get("tipo") if fonte.get("tipo") != "concessao" else None


def _marco(antes: str, depois: str, tipo: str) -> str | None:
    # Só a cláusula da data. Não usa a palavra "prazo" de um parágrafo remoto.
    antes = re.split(r"[;\n]", antes)[-1][-150:]
    if re.search(r"publicad|publicacao|modificad|atualizad|published|updated|copyright|cut-off|in force since", antes):
        return None
    if re.search(r"\b(?:lei|decreto|portaria|resolucao|instrucao normativa)\b.{0,85}\bde\s*$", antes):
        return None  # data de edição de norma citada não é um prazo do edital
    if re.search(r"\bopens?\s*$", antes):
        return None
    if re.search(r"propostas|proposals|submissions|recebimento|entrega de", antes):
        return "propostas"
    if re.search(r"inscrico|inscricao|registration|applications", antes):
        return "inscricoes"
    if re.search(
        r"deadline|closes|closing|comment period|consulta|contribuico|comments|respond.*by|survey.{0,70}until", antes
    ):
        return "consulta"
    if re.search(
        r"vigencia|aplicacao|aplica.*partir|entry into application|apply from|operators|"
        r"come into scope|date of application",
        antes,
    ):
        return "vigencia"
    if tipo == "eudr" and re.search(r"apply|applies|application|operators", depois[:80]):
        return "vigencia"
    if tipo == "leilao_imovel" and re.search(r"\bdata\s*:\s*$", antes):
        return "evento"
    if re.search(r"leilao|hasta publica|sessao publica|realiza|auction", antes):
        return "evento"
    if tipo == "penhora" and re.search(r"penhora.*(?:em|data|dia)|data da penhora", antes):
        return "penhora"
    return None


def _identificadores(texto: str) -> dict:
    cods = []
    for m in CAR.finditer(texto):
        try:
            cods.append(normalizar_car(m[0]))
        except ValueError:
            pass
    cns = re.search(r"\bCNS\s*[:nº°.\s-]*([\d.\-]{5,9})", texto, re.I)
    mat = re.search(r"matr[ií]cula\s*[:nº°.\s-]*([\d.]+[A-Z]?)", texto, re.I)
    sigef = re.findall(
        r"(?:SIGEF|c[oó]digo da parcela)\s*[:nº°.\s-]*(" + SIGEF.pattern.removeprefix(r"\b").removesuffix(r"\b") + ")",
        texto,
        re.I,
    )
    return {
        "codigos_car": sorted(set(cods)),
        "cns": normalizar_cns(cns[1]) if cns else None,
        "matricula": normalizar_matricula(mat[1]) if mat else None,
        "sigef": sigef,
        "vinculo": "car" if cods else "pendente",
    }


def _referencia(texto: str) -> str | None:
    padrao = (
        r"\bedital(?:\s+(?:de\s+)?(?:concorrencia(?:\s+publica)?|"
        r"leilao(?:\s+(?:rural|judicial|extrajudicial|eletronico)){0,3}|pregao(?:\s+eletronico)?))?"
        r"\s*(?P<indicador>n[º°o.]*)?\s*(?P<numero>\d{1,5}(?:[/.-]\d{1,4}){0,3})"
    )
    for m in re.finditer(padrao, texto):
        numero = m["numero"]
        if m["indicador"] or re.search(r"[/.-]", numero):
            return numero
    return None  # “deste edital. 2. Objeto” é item do texto, não número de edital


def _extrair(texto: str, fonte: dict, url: str, agora: dt.datetime, chave: str, anteriores=()) -> list[Evento]:
    tipo = _tipo(texto, fonte)
    if tipo is None:
        return []
    n = _normal(" ".join(texto.split()))
    ref = _referencia(n)
    situacao = (
        "cancelado" if re.search(r"(?:leilao|edital|evento|consulta).{0,30}(?:cancelad|revogad)", n) else "previsto"
    )
    if re.search(r"(?:leilao|edital|evento).{0,30}adiad.{0,20}(?:sem|nova data a)", n):
        situacao = "adiado"
    ids = _identificadores(texto)
    uf = fonte.get("uf")
    if len({c[:2] for c in ids["codigos_car"]}) == 1:
        uf = ids["codigos_car"][0][:2]
    municipios = {c.split("-")[1] for c in ids["codigos_car"]}
    municipio = next(iter(municipios)) if len(municipios) == 1 else None
    out, anterior, conta = [], 0, {}
    datas = list(DATAS.finditer(n))
    for i, m in enumerate(datas):
        data = _data(m[0])
        antes = n[anterior : m.start()]
        anterior = m.end()
        marco = _marco(antes, n[m.end() :], tipo)
        if data is None or marco is None:
            continue
        # Intervalo de uma mesma consulta/inscrição: a segunda data é o encerramento,
        # nunca a data de publicação. Os dois dias ficam preservados.
        prazo = data if marco in ("consulta", "propostas", "inscricoes") else None
        if i + 1 < len(datas) and re.fullmatch(r"\s*(?:-|a|ate|to|through|–|—)\s*", n[m.end() : datas[i + 1].start()]):
            fim = _data(datas[i + 1][0])
            if fim and fim >= data and marco in ("consulta", "propostas", "inscricoes"):
                prazo = fim
        conta[marco] = conta.get(marco, 0) + 1
        eid = identificador(fonte["id"], url, tipo, f"{chave}:{marco}:{conta[marco]}")
        out.append(
            Evento(
                id=eid,
                tipo=tipo,
                marco=marco,
                referencia=ref,
                data=data,
                prazo=prazo,
                uf=uf,
                municipio=municipio,
                fonte_id=fonte["id"],
                fonte_nome=fonte["nome"],
                fonte_url=url,
                coletado_em=agora,
                atualizado_em=agora,
                confianca=0.85,
                situacao=situacao,
                **ids,
            )
        )
    if situacao != "previsto":
        retificados = []
        # Retificações podem omitir a data antiga. Só substitui atos anteriores
        # com referência explícita na mesma fonte e imóvel, ou no mesmo permalink.
        for antigo in anteriores:
            mesma_publicacao = antigo.fonte_url == url and url not in fonte["urls"]
            mesmo_edital = bool(ref and antigo.referencia == ref)
            mesmo_imovel = bool(set(antigo.codigos_car) & set(ids["codigos_car"]))
            if (
                antigo.fonte_id == fonte["id"]
                and antigo.tipo == tipo
                and ((mesmo_edital and (mesmo_imovel or antigo.fonte_url == url)) or (mesma_publicacao and not ref))
            ):
                retificados.append(
                    antigo.model_copy(update={"situacao": situacao, "coletado_em": agora, "fonte_url": url})
                )
        if retificados:
            return retificados
    if (
        len(out) == 1
        and ref
        and ids["codigos_car"]
        and re.search(r"\bretifica\w*|\bprorrog\w*|\badiad\w*|\bnova data\b", n)
    ):
        novo = out[0]
        candidatos = [
            e
            for e in anteriores
            if e.fonte_id == fonte["id"]
            and e.tipo == tipo
            and e.marco == novo.marco
            and e.referencia == ref
            and set(e.codigos_car) == set(ids["codigos_car"])
        ]
        # Uma referência homônima ou duas praças anteriores não provam qual data
        # mudou. A continuidade em outro PDF exige correspondência única.
        if len(candidatos) == 1:
            return [novo.model_copy(update={"id": candidatos[0].id})]
    return out


def _deduplicar(eventos: list[Evento]) -> list[Evento]:
    unicos = {}
    for e in eventos:
        chave = (
            e.fonte_url,
            e.tipo,
            e.marco,
            e.data,
            e.prazo,
            e.referencia,
            tuple(e.codigos_car),
            e.cns,
            e.matricula,
            tuple(e.sigef),
            e.situacao,
        )
        # A mesma data pode estar no resumo, corpo e anexo do mesmo documento.
        # Preserva a primeira identidade; não junta imóveis ou publicações distintas.
        unicos.setdefault(chave, e)
    return list(unicos.values())


def extrair(
    texto: str, fonte: dict, url: str, agora: dt.datetime, formato: str = "html", anteriores=()
) -> tuple[list[Evento], int]:
    """Extrai por ato/bloco; nunca cruza CAR de um anúncio com a data de outro."""
    url = url_publica(url)
    if fonte.get("modo") == "djen":
        out, sem = [], 0
        dados = json.loads(texto)
        if not isinstance(dados, dict) or not isinstance(dados.get("items"), list):
            raise ValueError("resposta DJEN fora do contrato público")
        for item in dados["items"]:
            if not isinstance(item, dict):
                sem += 1
                continue
            h = str(item.get("hash") or "")
            if not re.fullmatch(r"[a-zA-Z0-9]{10,100}", h):
                sem += 1
                continue
            link = fonte["urls"][0] + f"/{h}/certidao"
            tx = BeautifulSoup(item.get("texto") or "", "html.parser").get_text(" ", strip=True)
            novos = _extrair(tx, fonte, link, agora, h, anteriores)
            out.extend(novos)
            if not novos and _tipo(tx, fonte):
                sem += 1
        return _deduplicar(out), sem
    if formato == "pdf":
        if fonte.get("modo") == "caixa_csv":
            return [], 0  # matrícula só prova o CAR do anúncio; não é novo leilão
        # Edições podem trazer vários editais na mesma página. Separa também pelo
        # cabeçalho; nunca usa todos os CARs da edição em todos os eventos.
        blocos, delimitado = atos_pdf.blocos(texto, fonte)
        if not delimitado:
            return [], 1  # edição inteira sem limites claros de atos: não adivinhar vínculos
        out = []
        for bloco in blocos:
            out.extend(_extrair(bloco, fonte, url, agora, _chave_bloco(bloco), anteriores))
        return _deduplicar(out), max(0, sum(1 for b in blocos if _tipo(b, fonte)) - len(out))
    sopa = BeautifulSoup(texto, "html.parser")
    for tag in sopa(["nav", "header", "footer", "style", "script", "form"]):
        tag.decompose()
    main = sopa.find("main") or sopa
    # Contêineres conhecidos delimitam um anúncio. Um <article> genérico pode
    # conter dezenas de editais diferentes: nunca o assume como um único ato.
    seletores = fonte.get("seletores", ".consultation-card, .spoiler-content, [data-calendario-evento]")
    if fonte["id"] == "eudr":
        # O quadro oficial distingue aplicação, entrada em vigor e corte florestal.
        # Apenas as três linhas de aplicação são prazos operacionais.
        titulo = next(
            (h for h in main.find_all(["h2", "h3"]) if _normal(h.get_text(strip=True)) == "application dates"), None
        )
        quadro = titulo.find_parent(class_="ewcms-page-section") if titulo else None
        blocos = quadro.select("li") if quadro else []
        if not blocos:
            return [], 1
    else:
        blocos = main.select(seletores)
    if not blocos:
        blocos = main.select("tr, p, li")
    # Tag.__eq__ compara toda a árvore: usar `p in blocos` torna páginas de
    # diários com milhares de parágrafos quadráticas. Aqui interessa identidade.
    ids_blocos = {id(b) for b in blocos}
    blocos = [b for b in blocos if not any(id(p) in ids_blocos for p in b.parents)]
    out, sem_data = [], 0
    for b in blocos:
        tx = b.get_text(" ", strip=True)
        # Cabeçalho imediato é contexto institucional, usado só em memória.
        cab = b.find_previous_sibling()
        if cab is not None and cab.name in {"h1", "h2", "h3", "h4"}:
            tx = cab.get_text(" ", strip=True) + " " + tx
        chave = b.get("id") or _chave_bloco(tx)
        link = url
        # Cards de consulta têm um permalink que conserva a identidade mesmo
        # quando o cartão muda de posição ou o prazo é retificado.
        if "consultation-card" in b.get("class", []):
            a = b.select_one("a[href]")
            if a and _permitida(urljoin(url, a["href"]), fonte):
                link = url_publica(urljoin(url, a["href"]))
                chave = "consulta"
        eventos = _extrair(tx, fonte, link, agora, chave, anteriores)
        if (
            not eventos
            and _tipo(tx, fonte)
            and (DATAS.search(_normal(tx)) or re.search(r"cancelad|revogad|adiad", _normal(tx)))
        ):
            sem_data += 1
        out.extend(eventos)
    return _deduplicar(list({e.id: e for e in out}.values())), max(0, sem_data)


def _chave_bloco(texto: str) -> str:
    # Data fica fora da identidade. Número de edital e contexto antes do primeiro
    # prazo sobrevivem a inserções de parágrafos e retificações de data.
    n = _normal(" ".join(texto.split()))
    ref = _referencia(n)
    prefixo = DATAS.split(n, maxsplit=1)[0]
    prefixo = re.sub(r"\b(?:prorrogad[oa]|retificad[oa]|cancelad[oa]|adiad[oa])\b", "", prefixo)
    return ref if ref else hashlib.sha256(prefixo.strip().encode()).hexdigest()[:16]


def _sementes(fonte: dict, hoje: dt.date) -> list[str]:
    for adaptador in (diario_pa, diarios, leiloes_abertos):
        especificas = adaptador.sementes(fonte, hoje)
        if especificas is not None:
            return especificas
    base = fonte["urls"][0]
    if fonte.get("modo") == "djen":
        desde = hoje - dt.timedelta(days=int(fonte.get("dias", 7)))
        return [
            base
            + "?"
            + urlencode(
                {
                    "texto": t,
                    "dataDisponibilizacaoInicio": desde.isoformat(),
                    "dataDisponibilizacaoFim": hoje.isoformat(),
                    "pagina": 1,
                    "itensPorPagina": 100,
                }
            )
            for t in fonte["termos"]
        ]
    if fonte.get("modo") == "dou":
        return [f"{base}?q={quote_plus(t)}&s=todos&exactDate=semana&sortType=0" for t in fonte["termos"]]
    if fonte.get("modo") == "busca_pa":
        desde = (hoje - dt.timedelta(days=7)).strftime("%Y%m%d")
        return [f"{base}?q={quote_plus(t)}&di={desde}&df={hoje:%Y%m%d}" for t in fonte["termos"]]
    return list(fonte["urls"])


def _links(texto: str, url: str, fonte: dict, hoje: dt.date | None = None) -> list[str]:
    if fonte.get("seguir_links") is False:
        return []
    especificos = diario_pa.links(texto, url, fonte, hoje or dt.date.today())
    if especificos is not None:
        return [u for u in especificos if _permitida(u, fonte)]
    especificos = diarios.descobrir(fonte, url, texto, hoje or dt.date.today())
    if especificos is not None:
        return [u for u in especificos if _permitida(u, fonte)]
    especificos = leiloes_abertos.links(texto, url, fonte)
    if especificos is not None:
        return [u for u in especificos if _permitida(u, fonte)]
    if fonte.get("modo") == "djen":
        d = json.loads(texto)
        p = urlsplit(url)
        params = {k: v[0] for k, v in parse_qs(p.query).items()}
        pagina = int(params.get("pagina", 1))
        if pagina * 100 < int(d.get("count", 0)):
            params["pagina"] = pagina + 1
            return [p._replace(query=urlencode(params)).geturl()]
        return []
    m = _DOU.search(texto)
    if m:
        rows = json.loads(m[1]).get("jsonArray", [])
        return [f"https://www.in.gov.br/web/dou/-/{r['urlTitle']}" for r in rows if r.get("urlTitle")]
    sopa = BeautifulSoup(texto, "html.parser")
    for tag in sopa(["nav", "header", "footer"]):
        tag.decompose()
    if fonte["id"] == "fomento_pr":
        # A página também contém compras urbanas e credenciamentos. O limite da
        # rodada deve visitar primeiro os editais dos próprios anúncios rurais.
        links = []
        for bloco in sopa.select(".spoiler-content"):
            if _tipo(bloco.get_text(" ", strip=True), fonte) != "leilao_imovel":
                continue
            for a in bloco.select("a[href]"):
                u = urljoin(url, a["href"])
                if _permitida(u, fonte) and urlsplit(u).path.lower().endswith(".pdf"):
                    if not re.search(r"ata|homologa|dioe", _normal(a.get_text(" ", strip=True) + " " + u)):
                        links.append(u)
        return list(dict.fromkeys(links))
    palavras = fonte.get("palavras", ["leilao", "penhora", "concessao", "carbono", "rural", "edital", "diario"])
    rx = re.compile("|".join(re.escape(_normal(p)) for p in palavras))
    links = []
    for a in sopa.find_all("a", href=True):
        if rx.search(_normal(a.get_text(" ", strip=True) + " " + a["href"])):
            link = urljoin(url, a["href"])
            if _permitida(link, fonte):
                links.append(url_publica(link))
    return list(dict.fromkeys(links))


def coletar_fonte(fonte: dict, agora: dt.datetime, obter=None, anteriores=()) -> tuple[list[Evento], FonteEstado]:
    obter = obter or baixar
    hoje = agora.astimezone(ZoneInfo("America/Sao_Paulo")).date()
    fila, vistos, eventos, falhas, sem_data = _sementes(fonte, hoje), set(), {}, 0, 0
    maximo = int(fonte.get("max_paginas", 8))
    acesso_restrito = False
    complementos = {}
    conhecidos = [e.fonte_url for e in anteriores if e.fonte_id == fonte["id"] and e.dia >= hoje]
    # Reconsulta detalhes de eventos ainda futuros para observar cancelamentos.
    # A API DJEN já busca as novas publicações; suas certidões são PDFs, não JSON.
    if fonte.get("modo") != "djen" and fonte.get("seguir_links") is not False:
        fila = list(dict.fromkeys(fila[:1] + conhecidos[: maximo // 2] + fila[1:]))
    while fila and len(vistos) < maximo:
        url = fila.pop(0)
        if url in vistos or not _permitida(url, fonte):
            continue
        vistos.add(url)
        try:
            texto, formato = obter(url, fonte)
            especifico = leiloes_abertos.texto_evento(texto, url, fonte) if formato == "html" else None
            novos, sem = extrair(
                especifico if especifico is not None else texto, fonte, url, agora, formato, anteriores
            )
            for evento in novos:
                anterior = eventos.get(evento.id)
                # Uma resposta pode repetir o edital original depois de sua
                # retificação, inclusive em outra página. A ordem da fonte não
                # pode reabrir um cancelamento observado nesta mesma rodada.
                prioridade = {"previsto": 0, "adiado": 1, "cancelado": 2}
                if anterior and prioridade[anterior.situacao] > prioridade[evento.situacao]:
                    continue
                eventos[evento.id] = evento
            if formato == "pdf" and url in complementos:
                detalhe, origem, ids_eventos = complementos.pop(url)
                prova = leiloes_abertos.complemento_matricula(detalhe, origem, texto, url, fonte)
                if prova:
                    for eid in ids_eventos:
                        evento = eventos[eid]
                        if evento.codigos_car and set(evento.codigos_car) != set(prova["codigos_car"]):
                            sem += 1  # anúncio e documento discordam; não escolhe uma versão
                            continue
                        codigo = prova["codigos_car"][0]
                        eventos[eid] = evento.model_copy(
                            update={**prova, "uf": codigo[:2], "municipio": codigo.split("-")[1]}
                        )
                else:
                    sem += 1  # PDF sem matrícula/CAR inequívocos permanece pendente
            sem_data += sem
            if formato == "html":
                links = _links(texto, url, fonte, hoje)
                documento = leiloes_abertos.documento_matricula(texto, url, fonte)
                if documento and novos and _permitida(documento, fonte) and documento not in vistos:
                    complementos[documento] = (texto, url, [e.id for e in novos])
                    # A prova do imóvel conta no mesmo limite de páginas e tem
                    # prioridade sobre o próximo anúncio, sem segundo downloader.
                    if documento in fila:
                        fila.remove(documento)
                    fila.insert(0, documento)
                fila.extend(u for u in links if u not in vistos and u not in fila)
        except AcessoRestrito:
            falhas += 1
            acesso_restrito = True
            fila.clear()  # não dispara as próximas buscas contra a mesma restrição/limite
            break
        except Exception:  # noqa: BLE001 - uma fonte não derruba as outras; nunca grava a exceção com texto pessoal
            falhas += 1
    parcial = bool(falhas or fila or (eventos and sem_data) or fonte.get("cobertura_parcial"))
    situacao = "erro" if falhas == len(vistos) else ("parcial" if parcial else ("ok" if eventos else "sem_data"))
    erro = None
    if falhas:
        erro = f"{falhas} página(s) não puderam ser lidas; consulte a fonte oficial."
    if acesso_restrito:
        erro = "Fonte restringiu o acesso ou pediu espera; consultas interrompidas sem contornar a restrição."
    if sem_data and eventos:
        erro = (erro + " " if erro else "") + "Há atos cuja data ou vínculo com o imóvel não pôde ser confirmado."
    if fila:
        erro = (erro + " " if erro else "") + "Limite de páginas da rodada atingido; cobertura parcial."
    if fonte.get("cobertura_parcial"):
        erro = (erro + " " if erro else "") + "A fonte mostra destaques, sem inventário completo dos imóveis."
    estado = FonteEstado(
        id=fonte["id"],
        nome=fonte["nome"],
        coletado_em=agora,
        situacao=situacao,
        erro=erro,
        paginas=len(vistos),
        eventos=len(eventos),
        sem_data=sem_data,
    )
    return list(eventos.values()), estado


def coletar(lista: list[dict] | None = None, agora: dt.datetime | None = None, obter=None, anteriores=()):
    agora = agora or dt.datetime.now(dt.UTC)
    with ThreadPoolExecutor(max_workers=4) as pool:
        resultados = list(pool.map(lambda f: coletar_fonte(f, agora, obter, anteriores), lista or fontes()))
    return [e for es, _ in resultados for e in es], [s for _, s in resultados]
