"""Falhas remotas não podem apagar a agenda anterior nem transportar campos privados."""

import json
from unittest.mock import MagicMock

import pytest
import requests

from raiz.calendario import arquivos
from testes.test_calendario import evento, fonte
from testes.test_privacidade import CPF


def resposta(monkeypatch, dados, *, status=200):
    r = MagicMock()
    r.__enter__.return_value = r
    r.iter_content.return_value = [json.dumps(dados).encode()]
    if status != 200:
        r.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status}")
    monkeypatch.setattr(arquivos.requests, "get", lambda *a, **kw: r)
    return r


def retrato():
    return {"eventos": [evento(vinculo="car").model_dump(mode="json")], "fontes": [], "total": 1}


def test_recupera_uid_e_car_sem_transportar_rotulo_ou_campo_remoto(monkeypatch, tmp_path):
    dados = retrato()
    dados["eventos"][0].update(fonte_nome="rótulo remoto", campo_interno="não permitido")
    dados["campo_interno"] = "não permitido"
    resposta(monkeypatch, dados)
    destino = tmp_path / "calendario" / "estado.json"
    assert arquivos.recuperar_publico(destino) == 1
    eventos, _ = arquivos.ler(destino)
    assert eventos[0].id == dados["eventos"][0]["id"]
    assert eventos[0].codigos_car_publicos == dados["eventos"][0]["codigos_car"]
    assert eventos[0].fonte_nome == fonte()["nome"]
    assert "campo_interno" not in destino.read_text()
    assert "rótulo remoto" not in destino.read_text()


@pytest.mark.parametrize("status", [401, 403, 404, 429, 503])
def test_erro_http_preserva_arquivo_e_nao_vira_historico_vazio(monkeypatch, tmp_path, status):
    resposta(monkeypatch, {}, status=status)
    destino = tmp_path / "estado.json"
    destino.write_text("histórico anterior")
    with pytest.raises(ValueError, match="histórico público"):
        arquivos.recuperar_publico(destino)
    assert destino.read_text() == "histórico anterior"


@pytest.mark.parametrize("mudanca", ["ausente", "contagem", "booleano", "duplicata", "fonte", "pessoal", "limite"])
def test_retrato_invalido_nao_substitui_historico(monkeypatch, tmp_path, mudanca):
    dados = retrato()
    if mudanca == "ausente":
        dados = {}
    elif mudanca == "contagem":
        dados["total"] = 2
    elif mudanca == "booleano":
        dados["total"] = True
    elif mudanca == "duplicata":
        dados["eventos"] *= 2
        dados["total"] = 2
    elif mudanca == "fonte":
        dados["eventos"][0]["fonte_url"] = "https://fora.example/edital"
    elif mudanca == "pessoal":
        dados["campo_extra"] = CPF
    elif mudanca == "limite":
        monkeypatch.setattr(arquivos, "MAX_ESTADO", 1)
    resposta(monkeypatch, dados)
    destino = tmp_path / "estado.json"
    destino.write_text("histórico anterior")
    with pytest.raises(ValueError, match="histórico público") as erro:
        arquivos.recuperar_publico(destino)
    assert CPF not in str(erro.value)
    assert destino.read_text() == "histórico anterior"


def test_documento_com_escape_json_nao_burla_mascaramento(monkeypatch, tmp_path):
    dados = retrato()
    dados["eventos"][0]["matricula"] = CPF.replace(".", "").replace("-", "")
    r = resposta(monkeypatch, dados)
    bruto = json.dumps(dados).replace(
        dados["eventos"][0]["matricula"], "".join(f"\\u{ord(c):04x}" for c in dados["eventos"][0]["matricula"])
    )
    r.iter_content.return_value = [bruto.encode()]
    destino = tmp_path / "estado.json"
    with pytest.raises(ValueError, match="histórico público"):
        arquivos.recuperar_publico(destino)
    assert not destino.exists()
