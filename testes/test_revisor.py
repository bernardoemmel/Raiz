"""Revisor de estilo e legibilidade (raiz/revisor.py) contra um servidor do LanguageTool falso, com respostas no
formato da API v2: só os avisos de estilo ficam, servidor fora do ar não trava a mensagem e sem URL não chama nada."""

import httpx
import pytest

from raiz import revisor

TEXTO = "Em virtude do fato de que a área é grande, ele subiu para cima. A Raíz manda."
PLEONASMO = TEXTO.index("subiu para cima")
RAIZ = TEXTO.index("Raíz")


def _resposta(req: httpx.Request) -> httpx.Response:
    corpo = dict(x.split("=", 1) for x in req.content.decode().split("&"))
    assert req.url.path == "/v2/check"
    assert corpo["language"] == "pt-BR" and corpo["level"] == "picky"
    assert "READABILITY_RULE_DIFFICULT_PT" in corpo["enabledRules"]
    regra = lambda i, c, t: {"id": i, "category": {"id": c}, "issueType": t}  # noqa: E731
    return httpx.Response(
        200,
        json={
            "software": {"version": "6.6"},
            "matches": [
                {"message": "Evite pleonasmos.", "offset": PLEONASMO, "length": 15,
                 "replacements": [{"value": "subiu"}], "rule": regra("REDUNDANCY_SUBIR", "CLARITY", "style")},
                {"message": "Possível erro de ortografia.", "offset": RAIZ, "length": 4,
                 "replacements": [{"value": "Raiz"}], "rule": regra("MORFOLOGIK_RULE_PT_BR", "TYPOS", "misspelling")},
                {"message": "Legibilidade {FRE: 59}: difícil.", "offset": 0, "length": 63, "replacements": [],
                 "rule": regra("READABILITY_RULE_DIFFICULT_PT", "TEXT_ANALYSIS", "style")},
            ],
        },
    )  # fmt: skip


def test_so_avisos_de_estilo_e_legibilidade():
    c = httpx.Client(transport=httpx.MockTransport(_resposta))
    r = revisor.revisar(TEXTO, "http://lt:8010/", c)
    assert r["versao"] == "6.6" and r["total"] == 2
    assert [a["regra"] for a in r["avisos"]] == ["REDUNDANCY_SUBIR", "READABILITY_RULE_DIFFICULT_PT"]
    assert r["avisos"][0]["trecho"] == "subiu para cima"
    assert r["avisos"][0]["sugestoes"] == ["subiu"]


def test_sem_url_nao_chama_nada(monkeypatch):
    monkeypatch.setattr(revisor, "url_padrao", lambda: None)
    assert revisor.revisar(TEXTO) is None
    nota = revisor.nota_de_envio(TEXTO)
    assert "languagetool" not in nota and nota["versao"].startswith("legibilidade-")


def test_fora_do_ar_nao_trava_e_tenta_de_novo(monkeypatch):
    def caiu(req):
        raise httpx.ConnectError("recusada", request=req)

    c = httpx.Client(transport=httpx.MockTransport(caiu))
    assert "erro" in revisor.revisar(TEXTO, "http://lt:8010", c)

    chamadas = []
    respostas = iter([caiu, _resposta])

    def alterna(req):
        chamadas.append(1)
        return next(respostas)(req)

    original = httpx.Client
    monkeypatch.setattr(revisor.httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(alterna)))
    revisor._revisar_em_cache.cache_clear()
    primeira = revisor.nota_de_envio(TEXTO, "http://lt:8010")
    assert "erro" in primeira["languagetool"] and primeira["flesch_martins"]  # a nota do medidor sai mesmo assim
    segunda = revisor.nota_de_envio(TEXTO, "http://lt:8010")  # a falha não ficou em cache
    assert segunda["languagetool"]["total"] == 2 and len(chamadas) == 2
    revisor.nota_de_envio(TEXTO, "http://lt:8010")  # a resposta boa fica em cache
    assert len(chamadas) == 2
    revisor._revisar_em_cache.cache_clear()


@pytest.mark.skipif(not revisor.url_padrao(), reason="sem RAIZ_LANGUAGETOOL_URL (servidor próprio do LanguageTool)")
def test_servidor_de_verdade():
    r = revisor.revisar("Ele subiu para cima. " * 3)
    assert r and "erro" not in r and any(a["regra"] == "REDUNDANCY_SUBIR" for a in r["avisos"])
