"""Busca semanal: leitura de cada fonte (sem rede), diferença com a semana anterior e relatório."""

import datetime as dt
import json
from types import SimpleNamespace

import pytest

from raiz.documentos.busca import fontes as F
from raiz.documentos.busca import http, semanal


@pytest.fixture(autouse=True)
def pastas(tmp_path, monkeypatch):
    monkeypatch.setenv("RAIZ_DOCUMENTOS_DIR", str(tmp_path / "docs"))
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)


def _html_dou(itens):
    return (
        '<html><script type="application/json" id="_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params">'
        + json.dumps({"jsonArray": itens})
        + "</script></html>"
    )


def test_dou_le_o_bloco_de_resultados_e_tira_nomes_do_resumo():
    texto = _html_dou(
        [
            dict(
                urlTitle="aviso-de-licitacao-123",
                title="AVISO DE LICITAÇÃO",
                pubDate="11/11/2026",
                pubName="DO3",
                hierarchyStr="Ministério do Meio Ambiente/Serviço Florestal Brasileiro",
                content="Concessão florestal na Flona X. Pregoeiro: <span class='highlight'>Fulano Beltrano</span>",
            ),
            dict(urlTitle="", title="sem link"),
        ]
    )
    [it] = F.dou_de_html(texto, '"concessão florestal"')
    assert it.chave == "aviso-de-licitacao-123" and it.data == "2026-11-11" and it.tipo == "publicacao"
    assert it.url == "https://www.in.gov.br/web/dou/-/aviso-de-licitacao-123"
    assert it.orgao.endswith("Serviço Florestal Brasileiro")
    assert "Fulano" not in it.detalhe["resumo"] and "[nome]" in it.detalhe["resumo"]
    with pytest.raises(ValueError):
        F.dou_de_html("<html>sem bloco</html>", "x")


def test_verra_json_e_markdown_filtram_brasil():
    dados = {
        "value": [
            dict(
                resourceIdentifier="5001",
                resourceName="Projeto ARR Pará",
                resourceStatus="Under development",
                country="Brazil",
                createDate="2026-10-30T00:00:00",
            ),
            dict(resourceIdentifier="5002", resourceName="Outro", resourceStatus="Registered", country="Peru"),
        ]
    }
    [it] = F.verra_de_json(dados)
    assert (it.chave, it.marca, it.data, it.tipo) == ("5001", "Under development", "2026-10-30", "projeto")
    md = (
        "| ID | Name | Proponent | Country | Status |\n|---|---|---|---|---|\n"
        "| [5003](https://x) | Restauração Xingu | Empresa | Brazil | Under validation |\n"
        "| 5004 | Outro | Empresa | Colombia | Registered |\n"
    )
    [it] = F.verra_de_markdown(md)
    assert (it.chave, it.titulo, it.marca) == ("5003", "Restauração Xingu", "Under validation")


def test_links_da_pagina_ignora_menu_e_redes():
    html = """<html><nav><a href="/edital-velho">Edital no menu</a></nav><main>
      <a href="/wp-content/uploads/2026/09/EDITAL-PE-90002-2026.pdf">EDITAL PE 90002-2026 Reabertura</a>
      <a href="https://twitter.com/share?url=edital">Compartilhar edital</a>
      <a href="/quem-somos">Quem somos nós</a></main></html>"""
    links = F.links_da_pagina(html, "https://exemplo.gov.br/licitacoes/", ["edital"])
    assert links == [
        (
            "EDITAL PE 90002-2026 Reabertura",
            "https://exemplo.gov.br/wp-content/uploads/2026/09/EDITAL-PE-90002-2026.pdf",
        )
    ]
    assert F._data_do_link(links[0][1]) == "2026-09-01"


class SessaoFalsa:
    def __init__(self, respostas):
        self.respostas, self.urls = respostas, []

    def request(self, metodo, url, **kw):
        self.urls.append(url)
        for chave, corpo in self.respostas.items():
            if chave in url:
                return SimpleNamespace(status_code=200, text=json.dumps(corpo), encoding="utf-8")
        return SimpleNamespace(status_code=404, text="", encoding="utf-8")


def test_sfb_pela_api_do_portal():
    base = "https://www.gov.br/florestal/pt-br/assuntos/concessoes-e-monitoramento/editais-em-licitacao"
    sess = SessaoFalsa(
        {
            "editais-em-licitacao/flona-x": {"modified": "2026-11-04T15:31:17+00:00"},
            "editais-em-licitacao": {"items": [{"@id": f"{base}/flona-x", "title": "Floresta Nacional X"}]},
            "@search": {
                "items": [
                    {
                        "@id": "https://www.gov.br/florestal/pt-br/assuntos/noticias/2026/novembro/sfb-lanca-edital",
                        "title": "SFB lança edital de restauração",
                        "effective": "2026-11-05T10:00:00+00:00",
                        "@type": "News Item",
                    },
                    {
                        "@id": "https://www.gov.br/florestal/pt-br/assuntos/noticias/2013/chamadas",
                        "title": "Chamada antiga",
                        "effective": "2026-11-03T10:00:00+00:00",
                        "@type": "News Item",
                    },
                    {
                        "@id": "https://www.gov.br/florestal/pt-br/assuntos/noticias/2026/novembro/curso",
                        "title": "SFB oferece curso de madeira",
                        "effective": "2026-11-06T10:00:00+00:00",
                        "@type": "News Item",
                    },
                ]
            },
        }
    )
    cfg = dict(
        api="https://www.gov.br/florestal/++api++/pt-br",
        editais="assuntos/concessoes-e-monitoramento/editais-em-licitacao",
        termos=["edital"],
        dias=60,
    )
    r = F.sfb(cfg, hoje=dt.date(2026, 11, 12), sessao=sess, palavras=["edital", "chamada"])
    titulos = [i.titulo for i in r.itens]
    assert titulos == ["Floresta Nacional X", "SFB lança edital de restauração"]
    assert r.itens[0].marca == "2026-11-04T15:31:17+00:00" and r.itens[0].data == "2026-11-04"


def test_baixar_cai_no_firecrawl_e_explica_quando_falta_chave(monkeypatch):
    def falha(url, **kw):
        raise http.FalhaDownload("HTTP 403")

    monkeypatch.setattr(http, "direto", falha)
    with pytest.raises(http.FalhaDownload, match="sem FIRECRAWL_API_KEY"):
        http.baixar("https://exemplo.gov.br")
    monkeypatch.setattr(http, "firecrawl", lambda url, **kw: http.Pagina("<a>ok</a>", "firecrawl", url))
    assert http.baixar("https://exemplo.gov.br").via == "firecrawl"


def _res(fonte, itens):
    return F.ResultadoFonte(fonte, [F.Item(fonte, *i) for i in itens], via="direto")


def test_semanal_linha_de_base_depois_novo_e_mudou(tmp_path):
    est = semanal.EstadoBusca(tmp_path / "busca.sqlite")
    r1 = semanal.rodar(
        est,
        [
            _res("verra", [("1", "Projeto A", "u1", None, None, "projeto", "Under development")]),
            F.ResultadoFonte("dou", erro="o Diário Oficial não respondeu"),
        ],
        hoje=dt.date(2026, 11, 9),
        pasta=tmp_path,
    )
    assert not r1.tem_novidade and r1.linha_de_base == {"verra": 1}
    md1 = r1.arquivo_md.read_text(encoding="utf-8")
    assert "Primeira rodada" in md1 and "Não deu para consultar" in md1
    r2 = semanal.rodar(
        est,
        [
            _res(
                "verra",
                [
                    ("1", "Projeto A", "u1", None, None, "projeto", "Registered"),
                    ("2", "Projeto B", "u2", "2026-11-14", None, "projeto", "Under development"),
                ],
            )
        ],
        hoje=dt.date(2026, 11, 16),
        pasta=tmp_path,
    )
    tipos = sorted((n.tipo, n.item.chave) for n in r2.novidades)
    assert tipos == [("mudou", "1"), ("novo", "2")]
    md2 = r2.arquivo_md.read_text(encoding="utf-8")
    assert "2 novidades" in md2 and "Under development → Registered" in md2 and "[Projeto B](u2)" in md2
    assert r2.arquivo_csv.read_text(encoding="utf-8").count("\n") == 3
    r3 = semanal.rodar(
        est,
        [_res("verra", [("1", "Projeto A", "u1", None, None, "projeto", "Registered")])],
        hoje=dt.date(2026, 11, 23),
        pasta=tmp_path,
    )
    assert not r3.tem_novidade


def test_fontes_json_tem_as_quatro_fontes():
    cfg = F.config()
    assert {"verra", "sfb", "ideflor_bio", "dou"} <= set(cfg)
    assert all('"' in t for t in cfg["dou"]["termos"])  # termos entre aspas: busca pela frase, não palavra solta
