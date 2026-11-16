"""Upload incompleto conserva os arquivos vigentes; promoção tem cópias recuperáveis."""

import hashlib
import json
from unittest.mock import MagicMock

import pytest
import requests

from raiz.calendario import arquivos, publicacao
from testes.test_calendario import evento


class GitHubSimulado:
    def __init__(self, falha=None):
        self.falha = falha
        self.ativos = {i: {"id": i, "name": n, "conteudo": b"anterior"} for i, n in enumerate(publicacao.ARQUIVOS, 1)}
        self.operacoes = []
        self.proximo = 10

    def request(self, metodo, url, **kw):
        self.operacoes.append((metodo, url))
        assert kw["headers"]["Authorization"] == "Bearer credencial-teste"
        falhar = False
        if metodo == "GET" and url.endswith("/tags/calendario"):
            dados = {"id": 20, "tag_name": "calendario", "draft": self.falha == "privado"}
            falhar = self.falha == "consulta"
        elif metodo == "GET":
            dados = list(self.ativos.values())
        elif metodo == "POST":
            assert url.startswith("https://uploads.github.com/repos/")
            assert kw["headers"]["Content-Type"] == "application/octet-stream"
            falhar = self.falha == "upload" and self.proximo == 11
            bruto = kw["data"]
            dados = {
                "id": self.proximo,
                "name": kw["params"]["name"],
                "conteudo": bruto,
                "state": "uploaded",
                "size": len(bruto),
                "digest": "sha256:" + hashlib.sha256(bruto).hexdigest(),
            }
            if self.falha == "hash":
                dados["digest"] = "sha256:incorreto"
            if not falhar:
                self.ativos[self.proximo] = dados.copy()
                self.proximo += 1
        elif metodo == "PATCH":
            identificador = int(url.rsplit("/", 1)[1])
            nome = kw["json"]["name"]
            falhar = self.falha == "promocao" and nome == "eventos.json"
            if falhar:
                self.falha = None
            else:
                assert not any(a["name"] == nome for i, a in self.ativos.items() if i != identificador)
                self.ativos[identificador]["name"] = nome
            dados = self.ativos[identificador].copy()
        elif metodo == "DELETE":
            self.ativos.pop(int(url.rsplit("/", 1)[1]))
            dados = None
        r = MagicMock()
        r.__enter__.return_value = r
        r.status_code = 204 if metodo == "DELETE" else 200
        r.json.return_value = dados
        if falhar:
            r.raise_for_status.side_effect = requests.HTTPError("falha remota")
        return r


def pasta(tmp_path):
    arquivos.publicar(tmp_path, [evento(vinculo="car")], [])
    return tmp_path


def test_publica_os_tres_so_depois_de_conferir_uploads(monkeypatch, tmp_path):
    gh = GitHubSimulado()
    monkeypatch.setattr(publicacao.requests, "request", gh.request)
    publicacao.publicar_release(pasta(tmp_path), "exemplo/repositorio", "credencial-teste")
    assert {a["name"] for a in gh.ativos.values()} == set(publicacao.ARQUIVOS)
    assert all(a["conteudo"] == (tmp_path / a["name"]).read_bytes() for a in gh.ativos.values())
    primeira_mudanca = next(i for i, (metodo, _) in enumerate(gh.operacoes) if metodo == "PATCH")
    assert sum(m == "POST" for m, _ in gh.operacoes[:primeira_mudanca]) == 3
    assert not {1, 2, 3}.intersection(gh.ativos)


@pytest.mark.parametrize("falha", ["consulta", "privado", "upload", "hash", "promocao"])
def test_falha_conserva_conteudo_anterior(monkeypatch, tmp_path, falha):
    gh = GitHubSimulado(falha)
    monkeypatch.setattr(publicacao.requests, "request", gh.request)
    with pytest.raises(ValueError, match="anteriores preservados"):
        publicacao.publicar_release(pasta(tmp_path), "exemplo/repositorio", "credencial-teste")
    for i, nome in enumerate(publicacao.ARQUIVOS, 1):
        assert gh.ativos[i] == {"id": i, "name": nome, "conteudo": b"anterior"}
    assert not any(m == "DELETE" for m, _ in gh.operacoes)


def test_repositorio_invalido_nao_envia_credencial(monkeypatch, tmp_path):
    gh = GitHubSimulado()
    monkeypatch.setattr(publicacao.requests, "request", gh.request)
    with pytest.raises(ValueError):
        publicacao.publicar_release(pasta(tmp_path), "../fora/repositorio", "credencial-teste")
    assert not gh.operacoes


@pytest.mark.parametrize("campo", ["proprietario", "car_inferido", "rotulo"])
def test_conteudo_privado_ou_rotulo_remoto_nao_sai_da_maquina(monkeypatch, tmp_path, campo):
    gh = GitHubSimulado()
    monkeypatch.setattr(publicacao.requests, "request", gh.request)
    pasta(tmp_path)
    caminho = tmp_path / "estado.json"
    dados = json.loads(caminho.read_text())
    if campo == "proprietario":
        dados["eventos"][0]["proprietario"] = "campo vedado"
    elif campo == "car_inferido":
        dados["eventos"][0]["vinculo"] = "sigef"
    else:
        dados["eventos"][0]["fonte_nome"] = "rótulo não institucional"
    caminho.write_text(json.dumps(dados))
    with pytest.raises(ValueError, match="anteriores preservados"):
        publicacao.publicar_release(tmp_path, "exemplo/repositorio", "credencial-teste")
    assert not gh.operacoes
