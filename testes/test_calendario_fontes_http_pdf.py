"""Contratos de transporte e fronteiras de atos, sem certidões reais ou gabaritos inventados."""

import datetime as dt
import io
import json

import pytest
import requests
from pypdf import PdfWriter

from raiz.calendario import coleta, diario_pa

AGORA = dt.datetime(2026, 11, 12, 10, tzinfo=dt.UTC)
CAR = "PA-1504950-" + "A" * 32
OUTRO = "PA-1504950-" + "B" * 32
TERCEIRO = "PA-1504950-" + "C" * 32
FONTE = {
    "id": "doe_pa",
    "nome": "Diário Oficial do Pará",
    "grupo": "diario_estadual",
    "modo": "diario_pa",
    "uf": "PA",
    "urls": ["https://www.ioepa.com.br/pages"],
}


def resposta(status, texto="<p>consulta pública</p>", **cab):
    r = requests.Response()
    r.status_code = status
    r._content = texto.encode()
    r._content_consumed = True
    r.headers.update(cab)
    return r


def test_retry_after_e_falha_transitoria_sem_antecipar_nova_leitura(monkeypatch):
    respostas = [resposta(429, **{"Retry-After": "3"}), resposta(503), resposta(200)]
    chamadas, esperas = [], []

    def pedir(*a, **kw):
        chamadas.append(a)
        return respostas.pop(0)

    monkeypatch.setattr(requests.Session, "request", pedir)
    monkeypatch.setattr(coleta.time, "sleep", esperas.append)
    texto, formato = coleta.baixar(FONTE["urls"][0], FONTE)
    assert formato == "html" and "consulta" in texto
    assert esperas == [3, 4] and len(chamadas) == 3
    assert coleta._espera_retry("Thu, 12 Nov 2026 10:00:45 GMT", 0, AGORA) == 45


@pytest.mark.parametrize("status,cab", [(401, {}), (403, {}), (429, {"Retry-After": "120"})])
def test_nao_contorna_restricao_nem_retry_after_longo(monkeypatch, status, cab):
    chamadas = []

    def pedir(*a, **kw):
        chamadas.append(a)
        return resposta(status, **cab)

    monkeypatch.setattr(requests.Session, "request", pedir)
    monkeypatch.setattr(coleta.http, "chave_firecrawl", lambda: "configurado-no-teste")
    monkeypatch.setattr(coleta.http, "firecrawl", lambda *_a, **_kw: pytest.fail("restrição contornada"))
    monkeypatch.setattr(coleta.time, "sleep", lambda *_: pytest.fail("não deve repetir"))
    with pytest.raises(coleta.AcessoRestrito):
        coleta.baixar(FONTE["urls"][0], FONTE)
    assert len(chamadas) == 1


def test_captcha_nao_usa_intermediario(monkeypatch):
    monkeypatch.setattr(requests.Session, "request", lambda *_a, **_kw: resposta(200, "Verify you are human"))
    monkeypatch.setattr(coleta.http, "chave_firecrawl", lambda: "configurado-no-teste")
    monkeypatch.setattr(coleta.http, "firecrawl", lambda *_a, **_kw: pytest.fail("CAPTCHA contornado"))
    with pytest.raises(coleta.AcessoRestrito):
        coleta.baixar(FONTE["urls"][0], FONTE)


def test_timeout_repete_leitura_mas_limite_de_bytes_nao_relaxa(monkeypatch):
    chamadas, esperas = [], []

    def pedir(*a, **kw):
        chamadas.append(a)
        if len(chamadas) < 3:
            raise requests.Timeout("conteúdo da fonte não deve ir ao estado")
        return resposta(200)

    monkeypatch.setattr(requests.Session, "request", pedir)
    monkeypatch.setattr(coleta.time, "sleep", esperas.append)
    coleta.baixar(FONTE["urls"][0], FONTE)
    assert len(chamadas) == 3 and esperas == [2, 4]
    monkeypatch.setattr(coleta.http, "chave_firecrawl", lambda: None)
    with pytest.raises(coleta.http.FalhaDownload, match="limite"):
        coleta.baixar(FONTE["urls"][0], {**FONTE, "max_bytes": 4})


def test_ioepa_seleciona_edicoes_e_extras_da_janela_inclusive_virada_de_ano():
    hoje = dt.date(2027, 1, 3)
    assert diario_pa.sementes(FONTE, hoje) == [
        "https://www.ioepa.com.br/pages/2027/",
        "https://www.ioepa.com.br/pages/2026/",
    ]
    texto = """<a href='/pages/2026/2026.12.30.DOE.pdf'>Diário</a>
      <a href='/pages/2026/2026.12.30.EXTRA.pdf'>Extra</a>
      <a href='/pages/2026/2026.12.30.DOE_old.pdf'>Antigo</a>
      <a href='/pages/2026/2026.12.01.DOE.pdf'>Fora da janela</a>
      <a href='/pages/2027/2027.01.04.DOE.pdf'>Futuro</a>
      <a href='https://externo.example/2027.01.02.DOE.pdf'>Outro host</a>"""
    links = coleta._links(texto, "https://www.ioepa.com.br/pages/2026/", FONTE, hoje)
    assert len(links) == 2 and all("2026.12.30." in u for u in links)


@pytest.mark.parametrize("fid", ["doe_pa", "doe_ac", "dou"])
def test_diario_separa_todos_atos_inclusive_administrativo_posterior(fid):
    fonte = {**FONTE, "id": fid}
    tx = f"""Diário Oficial - edição de 12/11/2026
Edital de leilão rural nº 1/2026
CAR {CAR}. Leilão em 30/11/2026.
AVISO DE LEILÃO rural nº 2/2026
CAR {OUTRO}. Leilão em 01/12/2026.
EXTRATO DE CONTRATO ADMINISTRATIVO
CAR {TERCEIRO}. Prazo até 31/12/2026.
"""
    eventos, _ = coleta.extrair(tx, fonte, fonte["urls"][0] + "/edicao.pdf", AGORA, "pdf")
    assert [(e.data, e.codigos_car) for e in eventos] == [
        (dt.date(2026, 11, 30), [CAR]),
        (dt.date(2026, 12, 1), [OUTRO]),
    ]
    sem_fronteiras = tx.replace("Edital de leilão", "Anúncio de leilão").replace("AVISO DE LEILÃO", "Anúncio")
    sem_fronteiras = sem_fronteiras.split("EXTRATO")[0]
    assert coleta.extrair(sem_fronteiras, fonte, fonte["urls"][0], AGORA, "pdf") == ([], 1)


def test_ioepa_protocolo_delimita_anuncio_mesmo_sem_titulo_padrao():
    tx = f"Imóvel rural CAR {CAR}. Leilão em 30/11/2026.\nProtocolo: 1234567\n"
    tx += f"Licença de atividade CAR {OUTRO}.\nProtocolo: 1234568\n"
    eventos, _ = coleta.extrair(tx, FONTE, FONTE["urls"][0] + "/edicao.pdf", AGORA, "pdf")
    assert len(eventos) == 1 and eventos[0].codigos_car == [CAR]


def test_djen_nao_confunde_resposta_de_erro_com_busca_vazia():
    fonte = {**FONTE, "id": "djen", "modo": "djen"}
    with pytest.raises(ValueError, match="contrato"):
        coleta.extrair(json.dumps({"error": "indisponível"}), fonte, fonte["urls"][0], AGORA)


def test_csv_caixa_latin1_preserva_imovel_rural_sem_expor_campos(monkeypatch):
    base = "https://venda-imoveis.caixa.gov.br"
    fonte = {"id": "caixa", "modo": "caixa_csv", "nome": "CAIXA", "urls": [base], "_ufs_processadas": ["PA"]}
    detalhe = base + "/sistema/detalhe-imovel.asp?hdnimovel=42"
    csv = "N° do imóvel;UF;Cidade;Descrição;Modalidade de venda;Link de acesso\n"
    csv += f"42;PA;Cidade;Imóvel Rural;Leilão SFI;{detalhe}\n"
    r = resposta(200)
    r._content = csv.encode("latin-1")
    r.encoding = "utf-8"  # cabeçalho ausente/errado não pode apagar o tipo rural
    monkeypatch.setattr(requests.Session, "request", lambda *_a, **_kw: r)
    url = base + "/listaweb/Lista_imoveis_BR.csv"
    texto, formato = coleta.baixar(url, fonte)
    assert formato == "html" and "Imóvel Rural" in texto
    assert coleta._links(texto, url, fonte, AGORA.date()) == [detalhe]


def test_calendario_usa_dia_brasileiro_na_virada_utc():
    visitadas = []

    def obter(url, _):
        visitadas.append(url)
        return "<main>Índice sem publicação</main>", "html"

    coleta.coletar_fonte(FONTE, dt.datetime(2027, 1, 1, 1, tzinfo=dt.UTC), obter=obter)
    assert visitadas == ["https://www.ioepa.com.br/pages/2026/"]


def test_restricao_interrompe_as_outras_consultas_da_mesma_fonte():
    fonte = {**FONTE, "modo": "djen", "termos": ["leilão rural", "penhora rural"]}
    visitadas = []

    def obter(url, _):
        visitadas.append(url)
        raise coleta.AcessoRestrito("HTTP 403")

    _, estado = coleta.coletar_fonte(fonte, AGORA, obter=obter)
    assert len(visitadas) == 1 and estado.situacao == "erro"
    assert "restrição" in estado.erro


def test_rr_formulario_publico_prepara_a_mesma_sessao_antes_do_pdf(monkeypatch):
    fonte = {
        "id": "doe_rr",
        "modo": "diario_rr",
        "nome": "Diário de Roraima",
        "urls": ["https://imprensaoficial.rr.gov.br/_inicial/"],
    }
    documento = "2026/11/doe-20261112.pdf"
    campos = {"doe": documento, "ipconexao": "192.0.2.2", "dia": "12", "mes": "11", "ano": "2026", "hora": "10"}
    form = (
        '<form action="../_visualizar-doe/">'
        + "".join(f'<input name="{k}" value="{v}">' for k, v in campos.items())
        + "</form>"
    )
    pdf, buf = PdfWriter(), io.BytesIO()
    pdf.add_blank_page(width=100, height=100)
    pdf.write(buf)
    chamadas = []

    def pedir(sessao, metodo, url, **kw):
        chamadas.append((id(sessao), metodo, url, kw))
        if metodo == "GET":
            return resposta(200, form)
        r = resposta(200)
        r._content = buf.getvalue()
        return r

    monkeypatch.setattr(requests.Session, "request", pedir)
    _, formato = coleta.baixar("https://imprensaoficial.rr.gov.br/_visualizar-doe/?doe=" + documento, fonte)
    assert formato == "pdf" and len(chamadas) == 2
    assert chamadas[0][0] == chamadas[1][0] and chamadas[0][1] == "GET" and chamadas[1][1] == "POST"
    assert chamadas[1][3]["data"] == campos


def test_coleta_caixa_confirma_car_somente_no_pdf_do_mesmo_anuncio_e_conta_limite():
    from testes.test_calendario_leiloes_abertos import DETALHE, PDF, csv, detalhe

    fonte = {
        "id": "caixa",
        "modo": "caixa_csv",
        "nome": "CAIXA",
        "urls": ["https://venda-imoveis.caixa.gov.br"],
        "_ufs_processadas": ["PA"],
        "max_paginas": 3,
    }
    indice = coleta._sementes(fonte, AGORA.date())[0]
    paginas = {
        indice: (csv(f"42;PA;Cidade;Imóvel rural;Leilão SFI;{DETALHE}"), "html"),
        DETALHE: (detalhe(), "html"),
        PDF: (f"MATRÍCULA Nº 5178\nCAR: {CAR}", "pdf"),
    }
    visitadas = []

    def obter(url, _):
        visitadas.append(url)
        return paginas[url]

    eventos, estado = coleta.coletar_fonte(fonte, AGORA, obter=obter)
    assert visitadas == [indice, DETALHE, PDF] and estado.paginas == 3
    assert len(eventos) == 2 and all(e.codigos_car == [CAR] and e.car_fonte_url == PDF for e in eventos)
    assert all(e.municipio == "1504950" and e.fonte_url == DETALHE for e in eventos)
    limitados, estado = coleta.coletar_fonte({**fonte, "max_paginas": 2}, AGORA, obter=obter)
    assert len(limitados) == 2 and all(not e.codigos_car and e.car_fonte_url is None for e in limitados)
    assert estado.situacao == "parcial" and estado.paginas == 2


def test_retificacao_em_outro_pdf_preserva_uid_so_com_correspondencia_unica():
    fonte = {**FONTE, "id": "leilao_oficial", "modo": "portal"}
    original = f"EDITAL DE LEILÃO rural nº 7/2026\nCAR {CAR}. Leilão em 30/11/2026."
    antigos, _ = coleta.extrair(original, fonte, fonte["urls"][0] + "/edital.pdf", AGORA, "pdf")
    novo = original.replace("30/11/2026", "04/12/2026").replace("Leilão em", "Retificação. Nova data do leilão em")
    eventos, _ = coleta.extrair(novo, fonte, fonte["urls"][0] + "/retificacao.pdf", AGORA, "pdf", antigos)
    assert eventos[0].id == antigos[0].id and eventos[0].data == dt.date(2026, 12, 4)
    duas_pracas = antigos + [antigos[0].model_copy(update={"id": "outra-praca", "data": dt.date(2026, 12, 1)})]
    ambiguos, _ = coleta.extrair(novo, fonte, fonte["urls"][0] + "/retificacao.pdf", AGORA, "pdf", duas_pracas)
    assert ambiguos[0].id not in {e.id for e in duas_pracas}
