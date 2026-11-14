"""Catalogação pública não altera a projeção nem introduz derivados pagos."""

import hashlib
import json

import httpx
import pytest

from raiz.catalogo_publico import catalogar_publico
from raiz.executor.armazem import ArmazemRelease
from raiz.executor.publicacao_aberta import validar_asset_publico
from testes.test_armazem_release import GitHubFalso


def _aberto(tmp_path):
    github = GitHubFalso()
    github.privado = False
    github.assets["estados.json"] = json.dumps(
        {
            "escopo": "publico_basico",
            "versao_publicacao": 1,
            "repo": "bernardoemmel/Raiz",
            "tag": "dados",
            "estados": {},
        }
    ).encode()
    armazem = ArmazemRelease(
        "bernardoemmel/Raiz",
        "dados",
        tmp_path / "espelho",
        token="segredo",
        cliente=httpx.Client(transport=httpx.MockTransport(github)),
    )
    return github, armazem


def test_catalogo_basico_preserva_bytes_e_trata_estado_sem_csv(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    github, armazem = _aberto(tmp_path)
    csv = (
        "cod_imovel,cod_ibge,municipio,uf,situacao_basica\nRO-1100015-"
        + "A" * 32
        + ",1100015,Alta Floresta D'Oeste,RO,apto\n"
    ).encode()
    github.assets["raiz_RO.tar.gz"] = ArmazemRelease._tar("RO", {"imoveis_basicos_1100015.csv": csv})
    github.assets["raiz_AM.tar.gz"] = ArmazemRelease._tar("AM", {})
    originais = dict(github.assets)
    catalogar_publico(armazem, "RO")
    catalogar_publico(armazem, "AM")
    assert all(github.assets[n] == b for n, b in originais.items())
    assert set(github.assets) - set(originais) == {
        "croissant_RO.json",
        "croissant_AM.json",
        "croissant_estados.json",
        "croissant_cartao_modelo.md.json",
        "cartao_modelo.md",
        "croissant.json",
    }
    for nome, dados in github.assets.items():
        validar_asset_publico(nome, dados)
    for uf in ("RO", "AM"):
        ficha = json.loads(github.assets[f"croissant_{uf}.json"])
        assert ficha["isAccessibleForFree"] is True
        assert ficha["distribution"][0]["sha256"] == hashlib.sha256(originais[f"raiz_{uf}.tar.gz"]).hexdigest()
    assert not (tmp_path / "atestar-privado.txt").exists()
    assert "croissant_RO.json" in (tmp_path / "atestar.txt").read_text()


def test_pacote_completo_nao_e_reinterpretado_como_basico(tmp_path):
    github, armazem = _aberto(tmp_path)
    github.assets["raiz_RO.tar.gz"] = ArmazemRelease._tar(
        "RO", {"desenvolvedor_1100015.csv": b"cod_imovel,credito_p50\nCAR-A,100\n"}
    )
    antes = dict(github.assets)
    with pytest.raises(ValueError, match="privado"):
        catalogar_publico(armazem, "RO")
    assert github.assets == antes and not github.uploads
