"""A atestação identifica os bytes enviados, sem incluir upload que falhou."""

import hashlib

import httpx
import pytest

from raiz.atestacao import registrar
from raiz.executor.armazem import ArmazemRelease


def test_conserva_ultimo_digest_por_nome_e_arquivos_distintos(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    registrar("raiz_PA.tar.gz", b"antigo")
    registrar("croissant_PA.json", b"ficha")
    registrar("raiz_PA.tar.gz", b"novo")
    linhas = (tmp_path / "atestar.txt").read_text().splitlines()
    assert len(linhas) == 2
    assert f"{hashlib.sha256(b'novo').hexdigest()}  raiz_PA.tar.gz" in linhas
    assert f"{hashlib.sha256(b'ficha').hexdigest()}  croissant_PA.json" in linhas


def test_upload_falho_nao_e_atestado(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    cliente = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    a = ArmazemRelease(espelho=tmp_path / "espelho", token="teste", cliente=cliente)
    with pytest.raises(httpx.HTTPStatusError):
        a._subir({"id": 1, "assets": []}, "raiz_PA.tar.gz", b"pacote")
    assert not (tmp_path / "atestar.txt").exists()


def test_upload_concluido_registra_checksum(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    cliente = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(201)))
    a = ArmazemRelease(espelho=tmp_path / "espelho", token="teste", cliente=cliente)
    a._subir({"id": 1, "assets": []}, "raiz_PA.tar.gz", b"pacote")
    assert (tmp_path / "atestar.txt").read_text() == f"{hashlib.sha256(b'pacote').hexdigest()}  raiz_PA.tar.gz\n"
