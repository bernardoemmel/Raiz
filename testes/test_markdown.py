"""Negociação HTTP e privacidade da versão Markdown, inclusive sem banco ou sessão de navegador."""

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from raiz import front_api, markdown, publico
from raiz.api import criar_app
from testes.test_privacidade import CPF, fmt_cpf


@pytest.mark.parametrize(
    ("accept", "esperado"),
    [
        (None, False),
        ("*/*", False),
        ("text/*", False),
        ("text/markdown", True),
        ("TEXT/MARKDOWN; charset=utf-8", True),
        ("text/markdown, */*", True),
        ("text/markdown;q=0, */*", False),
        ("text/markdown;q=0.2, application/json;q=0.8", False),
        ("text/markdown;q=0.8, application/json;q=0.2", True),
        ("text/markdown, application/json", False),
        ("text/markdown;q=0.5, application/*;q=0.8, application/json;q=0", True),
        ("text/markdown;q=inválido", False),
        ("text/markdown;q=NaN", False),
        ("text/markdown;q=2", False),
    ],
)
def test_preferencia_respeita_formato_padrao_especificidade_e_q(accept, esperado):
    assert markdown.prefere_markdown(accept) is esperado


def test_html_prioritario_e_dados_literais():
    assert not markdown.prefere_markdown("text/html, text/markdown", "text/html")
    assert markdown.prefere_markdown("text/html;q=0.2, text/markdown;q=0.9", "text/html")
    md = markdown.documento(
        {
            "municipio": "São Félix",
            "nota": f"<script> {fmt_cpf(CPF)} [link](javascript:alert(1))",
            "_interno": "segredo",
        },
        "Municípios",
    )
    assert "São Félix" in md and "segredo" not in md and "<script>" not in md
    assert fmt_cpf(CPF) not in md and "javascript:alert(1)" not in md


@pytest.fixture
def cliente(monkeypatch):
    import raiz.api as api

    cfg = type("C", (), {"api_token": SecretStr("teste-markdown"), "api_origens": ""})()
    monkeypatch.setattr(api, "config", lambda: cfg)
    app = criar_app(engine=object(), grafo=object(), deps=object(), whatsapp=False)
    with TestClient(app) as cl:
        yield cl


def test_markdown_da_api_mantem_token_e_representacao_json(cliente, monkeypatch):
    linha = front_api._limpa(
        {"cod_imovel": "PA-1505536-EXEMPLO", "ha": 25, "nota": fmt_cpf(CPF), "nome_dono": "segredo"}
    )
    monkeypatch.setattr(front_api, "imoveis_do_municipio", lambda *args, **kwargs: [linha])
    endereco = "/municipios/1505536/imoveis"
    assert cliente.get(endereco, headers={"Accept": "text/markdown"}).status_code == 401
    headers = {"Authorization": "Bearer teste-markdown", "Accept": "text/markdown"}
    md = cliente.get(endereco, headers=headers)
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert md.headers["vary"] == "Accept"
    assert "Código do CAR" in md.text and linha["cod_imovel"] in md.text and "25" in md.text
    assert fmt_cpf(CPF) not in md.text and "segredo" not in md.text
    headers["Accept"] = "application/json, text/markdown;q=0.1"
    js = cliente.get(endereco, headers=headers)
    assert js.json() == [linha] and js.headers["vary"] == "Accept"


def test_publico_markdown_so_mostra_localizacao_apos_aceite(cliente, monkeypatch):
    d = {
        "codigo": "AB23CD",
        "municipio": "Parauapebas",
        "uf": "PA",
        "hectares": "25",
        "frase": "podem voltar a ser mata",
        "selo": "bronze",
        "aceito": False,
        "_cod_imovel": "PA-1505536-EXEMPLO",
        "_cod_busca": "localizacao-exata",
        "nome_dono": "segredo",
    }
    monkeypatch.setattr(publico, "dados", lambda *_: d)
    chamadas = []
    monkeypatch.setattr(
        publico, "_imagens_do_aceite", lambda d: chamadas.append(d["aceito"]) or {"imagem": "existente"}
    )
    md = cliente.get("/p/AB23CD", headers={"Accept": "text/markdown"})
    arquivo = cliente.get("/p/AB23CD.md")
    assert md.status_code == arquivo.status_code == 200 and md.text == arquivo.text
    assert md.headers["content-type"].startswith("text/markdown") and md.headers["vary"] == "Accept"
    assert "Parauapebas" in md.text and "25" in md.text and "AB23CD" in md.text
    assert all(s not in md.text for s in (d["_cod_imovel"], "localizacao-exata", "segredo", "satelite.webp"))
    assert chamadas == []
    h = cliente.get("/p/AB23CD", headers={"Accept": "text/markdown;q=0, text/html"})
    assert h.headers["content-type"].startswith("text/html") and h.headers["vary"] == "Accept"
    assert 'type="text/markdown"' in h.text and "/p/AB23CD.md" in h.text
    d.update(aceito=True, selo="ouro")
    depois = cliente.get("/p/AB23CD", headers={"Accept": "text/markdown"}).text
    assert d["_cod_imovel"] in depois and "Selo ouro" in depois and "/p/AB23CD/satelite.webp" in depois
    assert "localizacao-exata" not in depois and "segredo" not in depois and chamadas == [True]
