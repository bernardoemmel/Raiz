"""Cota, revalidação autorizada e disputa realista de trava sem esperas de relógio."""

import gzip
import json
from types import SimpleNamespace

import httpx
import pytest

from raiz.executor import armazem as A
from raiz.executor import http_github as H

URL = "https://api.github.com/repos/exemplo/raiz/releases/7/assets"
CABECALHOS = {"Authorization": "Bearer teste-sintetico", "Accept": "application/vnd.github+json"}


@pytest.fixture
def relogio(monkeypatch):
    r = SimpleNamespace(agora=0.0, esperas=[])

    def dormir(segundos):
        r.esperas.append(segundos)
        r.agora += segundos

    tempo = SimpleNamespace(monotonic=lambda: r.agora, time=lambda: 1000 + r.agora, sleep=dormir)
    monkeypatch.setattr(H, "time", tempo)
    monkeypatch.setattr(A, "time", tempo)
    return r


def test_revalidacao_sempre_remota_preserva_bytes_gzip_e_cota():
    chamadas = []
    dados = [{"id": 1, "name": "sintetico.json"}]

    def servidor(req):
        chamadas.append(req)
        if req.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304, headers={"ETag": '"v1"'})
        return httpx.Response(200, content=gzip.compress(json.dumps(dados).encode()),
                              headers={"ETag": '"v1"', "Content-Encoding": "gzip"})  # fmt: skip

    with httpx.Client(transport=httpx.MockTransport(servidor)) as cliente:
        c = H.ClienteGitHub(cliente)
        for _ in range(10):
            assert c.get(URL, headers=CABECALHOS, params={"page": 1}).json() == dados
        assert len(chamadas) == 10
        assert sum("if-none-match" in r.headers for r in chamadas) == 9
        assert all(r.headers["authorization"] == CABECALHOS["Authorization"] for r in chamadas)


@pytest.mark.parametrize("status", [401, 403, 404, 500])
def test_falha_nunca_reaproveita_resposta_anterior(status):
    respostas = [httpx.Response(200, json={"draft": True}, headers={"ETag": '"v1"'}),
                 httpx.Response(status, json={"message": "acesso recusado"})]  # fmt: skip
    with httpx.Client(transport=httpx.MockTransport(lambda _: respostas.pop(0))) as cliente:
        c = H.ClienteGitHub(cliente)
        assert c.get(URL, headers=CABECALHOS).status_code == 200
        assert c.get(URL, headers=CABECALHOS).status_code == status
        assert not c._cache


def test_cache_separa_credencial_pagina_e_representacao():
    chamadas = []

    def servidor(req):
        chamadas.append(req)
        return httpx.Response(200, json={"draft": True}, headers={"ETag": '"v1"'})

    with httpx.Client(transport=httpx.MockTransport(servidor)) as cliente:
        c = H.ClienteGitHub(cliente)
        c.get(URL, headers=CABECALHOS, params={"page": 1})
        c.get(URL, headers=CABECALHOS, params={"page": 2})
        c.get(URL, headers={**CABECALHOS, "Authorization": "Bearer outro-sintetico"}, params={"page": 1})
        c.get(URL, headers={**CABECALHOS, "Accept": "application/octet-stream"}, params={"page": 1})
        assert all("if-none-match" not in r.headers for r in chamadas)


@pytest.mark.parametrize("metodo", ["get", "post", "delete"])
def test_recusa_de_cota_espera_reset_e_preserva_requisicao(relogio, metodo, caplog):
    chamadas = []

    def servidor(req):
        chamadas.append(req)
        if len(chamadas) == 1:
            return httpx.Response(403, json={"message": "API rate limit exceeded for installation"},
                                  headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1120"})  # fmt: skip
        return httpx.Response(200, json={"ok": True})

    with httpx.Client(transport=httpx.MockTransport(servidor)) as cliente:
        c = H.ClienteGitHub(cliente, espera_max_s=3700)
        kwargs = {"content": b"bytes-sinteticos"} if metodo == "post" else {}
        assert getattr(c, metodo)(URL, headers=CABECALHOS, **kwargs).status_code == 200
    assert relogio.agora == 121
    assert max(relogio.esperas) <= 60
    assert len(chamadas) == 2 and chamadas[0].content == chamadas[1].content
    assert "teste-sintetico" not in caplog.text and URL not in caplog.text


@pytest.mark.parametrize(
    "headers,esperado",
    [
        ({"retry-after": "12"}, 12),
        ({"retry-after": "Thu, 01 Jan 1970 00:17:00 GMT"}, 20),
        ({}, 60),
    ],
)
def test_retry_after_e_limite_secundario(relogio, headers, esperado):
    respostas = [httpx.Response(429, headers=headers), httpx.Response(200)]
    with httpx.Client(transport=httpx.MockTransport(lambda _: respostas.pop(0))) as cliente:
        assert H.ClienteGitHub(cliente).get(URL).status_code == 200
    assert relogio.agora == esperado


def test_cota_persistente_tem_orcamento_limitado(relogio):
    chamadas = []

    def servidor(req):
        chamadas.append(req)
        return httpx.Response(429, headers={"retry-after": "30"})

    with httpx.Client(transport=httpx.MockTransport(servidor)) as cliente:
        c = H.ClienteGitHub(cliente, espera_max_s=45)
        assert c.get(URL).status_code == 429
    assert relogio.agora == 30 and len(chamadas) == 2


def test_recusa_longa_nao_dispara_outras_chamadas_antes_da_renovacao(relogio):
    chamadas = []

    def servidor(req):
        chamadas.append(req)
        if len(chamadas) == 1:
            return httpx.Response(403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "4600"})
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(servidor)) as cliente:
        c = H.ClienteGitHub(cliente, espera_max_s=120)
        assert c.get(URL).status_code == 403
        assert c.post(URL, content=b"outro-municipio").status_code == 403
        assert len(chamadas) == 1 and not relogio.esperas
        relogio.agora = 3602
        assert c.get(URL).status_code == 200
        assert len(chamadas) == 2


@pytest.mark.parametrize("status", [403, 422, 500])
def test_mutacao_sem_recusa_explicita_de_cota_nao_repete(relogio, status):
    chamadas = []

    def servidor(req):
        chamadas.append(req)
        return httpx.Response(status, json={"message": "outra falha"})

    with httpx.Client(transport=httpx.MockTransport(servidor)) as cliente:
        assert H.ClienteGitHub(cliente).post(URL, content=b"sintetico").status_code == status
    assert len(chamadas) == 1 and not relogio.esperas


def test_visibilidade_e_revalidada_e_mudanca_para_publico_bloqueia(tmp_path, relogio):
    versao = [1]

    def servidor(req):
        if req.url.path.endswith("/releases/tags/dados-privados"):
            return httpx.Response(200, json={"id": 7, "draft": versao[0] == 1}, headers={"ETag": f'"v{versao[0]}"'})
        assert req.url.path == "/repos/exemplo/raiz"
        return httpx.Response(200, json={"private": False}, headers={"ETag": '"repo"'})

    with httpx.Client(transport=httpx.MockTransport(servidor)) as cliente:
        arm = A.ArmazemRelease(
            "exemplo/raiz", "dados-privados", tmp_path, token="sintetico", cliente=cliente, privado=True
        )
        assert arm._exigir_privado()["draft"]
        versao[0] = 2
        with pytest.raises(PermissionError):
            arm._exigir_privado()


def test_trava_ocupada_revalida_sem_repetir_escrita_ate_liberacao(tmp_path, relogio, monkeypatch):
    metodos = []
    leituras = [0]
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)

    def servidor(req):
        metodos.append(req.method)
        if req.method == "POST":
            if metodos.count("POST") == 1:
                return httpx.Response(422, json={"message": "Reference already exists"})
            return httpx.Response(201)
        if req.method == "GET":
            leituras[0] += 1
            if leituras[0] == 4:
                return httpx.Response(404)
            if req.headers.get("if-none-match"):
                return httpx.Response(304)
            return httpx.Response(200, json={"ref": "refs/tags/trava"}, headers={"ETag": '"dono"'})
        return httpx.Response(204)

    with httpx.Client(transport=httpx.MockTransport(servidor)) as cliente:
        arm = A.ArmazemRelease("exemplo/raiz", "dados", tmp_path, token="sintetico", cliente=cliente)
        with arm._trava("trava", velha_s=120):
            assert metodos == ["POST", "GET", "GET", "GET", "GET", "POST"]
    assert metodos[-1] == "DELETE"


def test_checkpoint_sobrevive_cota_durante_upload_e_restaura_mesmos_bytes(tmp_path, relogio, monkeypatch):
    from raiz.executor import checkpoint as C
    from testes.test_armazem_release import GitHubFalso
    from testes.test_checkpoint_executor import bytes_arquivos, fontes, raizes

    remoto = GitHubFalso()
    recusou = []

    def servidor(req):
        if req.url.host == "uploads.github.com" and not recusou:
            recusou.append(True)
            return httpx.Response(403, json={"message": "API rate limit exceeded for installation"},
                                  headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "4600"})  # fmt: skip
        return remoto(req)

    monkeypatch.setenv("RAIZ_GITHUB_ESPERA_MAX_S", "3700")
    roots = raizes(tmp_path / "origem")
    fontes(roots)
    esperado = bytes_arquivos(roots)
    with httpx.Client(transport=httpx.MockTransport(servidor)) as cliente:
        arm = A.ArmazemRelease("exemplo/raiz", "dados-privados", tmp_path / "api", token="segredo",
                               cliente=cliente, privado=True)  # fmt: skip
        assert C.salvar("PA-1", arm=arm, raizes=roots)["situacao"] == "preservado"
        assert relogio.agora == 3601
        destino = raizes(tmp_path / "destino")
        assert C.restaurar("PA-1", arm=arm, raizes=destino)["arquivos"] == len(esperado)
        assert bytes_arquivos(destino) == esperado
    assert remoto.uploads[-1] == "checkpoint-PA-1-latest.json"


def test_workflow_reserva_tempo_para_preservar_depois_da_cota():
    from pathlib import Path

    import yaml

    workflow = yaml.safe_load((Path(__file__).parents[1] / ".github/workflows/processar-estados.yml").read_text())
    job = workflow["jobs"]["processar"]
    checkpoint = next(
        s for s in job["steps"] if s.get("name") == "Preservar resultados e retratos opacos no checkpoint privado"
    )
    assert checkpoint["env"]["RAIZ_GITHUB_ESPERA_MAX_S"] == "3700"
    assert checkpoint["timeout-minutes"] == 75
    assert int(job["env"]["RAIZ_MARGEM_MIN"]) >= checkpoint["timeout-minutes"] + 30
    assert "always()" in checkpoint["if"]
    assert job["strategy"]["max-parallel"] == 15
    assert job["concurrency"]["cancel-in-progress"] is False
