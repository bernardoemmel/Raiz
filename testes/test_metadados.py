"""Os metadados devem descrever e permitir ler os mesmos bytes publicados."""

import copy
import hashlib
import json
import tarfile

import pytest

from raiz.metadados import CONFORMIDADE, croissant_release, croissant_uf, ficha_arquivo, validar

mlc = pytest.importorskip("mlcroissant")
pytest.importorskip("croissant_baker")


def _entrada(pacote):
    return {
        "url": f"https://example.org/{pacote.name}?v={hashlib.sha256(pacote.read_bytes()).hexdigest()}",
        "sha256": hashlib.sha256(pacote.read_bytes()).hexdigest(),
        "tamanho": pacote.stat().st_size,
        "versao": "1.0.0",
        "atualizado_em": "2026-11-12T20:00:00Z",
    }


def test_croissant_le_tar_com_esquemas_diferentes_sem_rede(tmp_path, monkeypatch):
    pasta = tmp_path / "PA"
    pasta.mkdir()
    (pasta / "imoveis_1504950.csv").write_text("cod_imovel,ha\nCAR-A,3\n", encoding="utf-8")
    (pasta / "imoveis_1504951.csv").write_text("cod_imovel,ha,coluna_nova\nCAR-B,2.5,sim\n", encoding="utf-8")
    (pasta / "extras_direto_1504950.csv").write_text("cod_imovel,tmf_classe\nCAR-A,4\n", encoding="utf-8")
    (pasta / "flag_1504950.csv").write_text("cod_imovel,flag_tco2_ano\n", encoding="utf-8")
    (pasta / "imoveis_1504950.csv.meta.json").write_text('{"segredo":"NAO_PUBLICAR"}', encoding="utf-8")
    (pasta / "geo_1504950.parquet").write_bytes(b"fora do pacote CSV")
    pacote = tmp_path / "raiz_PA.tar.gz"
    with tarfile.open(pacote, "w:gz") as tar:
        for arquivo in pasta.glob("*.csv"):
            tar.add(arquivo, arcname=f"PA/{arquivo.name}")
    # A validação é estática e a prova de leitura usa somente o tar local.
    import requests

    def sem_rede(*args, **kwargs):
        pytest.fail("a ficha não deve baixar dados para validar")

    monkeypatch.setattr(requests.sessions.Session, "request", sem_rede)
    ficha = croissant_uf(pasta, "pa", _entrada(pacote))
    assert ficha["@type"] == "sc:Dataset"
    assert ficha["conformsTo"] == CONFORMIDADE
    assert "@base" not in ficha["@context"]  # o validador não modifica a ficha
    assert "license" not in ficha  # o baker presume CC-BY; a Raíz não presume
    assert "ainda não foi definida" in ficha["conditionsOfAccess"]
    assert ficha["distribution"][0]["sha256"] == _entrada(pacote)["sha256"]
    serializada = json.dumps(ficha)
    assert "CAR-A" not in serializada
    assert "NAO_PUBLICAR" not in serializada
    assert "geo_1504950" not in serializada
    assert '"examples"' not in serializada.replace(json.dumps(ficha["@context"]), "")
    conjuntos = {d["name"]: d for d in ficha["distribution"] if d["@type"] == "cr:FileSet"}
    assert conjuntos["imoveis"]["includes"] == ["PA/imoveis_*.csv"]
    assert conjuntos["extras_direto"]["containedIn"] == {"@id": "arquivo"}
    leitor = mlc.Dataset(copy.deepcopy(ficha), mapping={"arquivo": pacote})
    registros = list(leitor.records("imoveis_1504950"))
    assert registros[0]["imoveis_1504950/ha"] == 3
    registros_novos = list(leitor.records("imoveis_1504951"))
    assert registros_novos[0]["imoveis_1504951/ha"] == 2.5
    assert registros_novos[0]["imoveis_1504951/coluna_nova"] == b"sim"
    assert list(leitor.records("flag_1504950")) == []


def test_ficha_recusa_coluna_pessoal_antes_de_chamar_baker(tmp_path, monkeypatch):
    (tmp_path / "imoveis_1504950.csv").write_text("cod_imovel,nome_proprietario\nCAR-A,NAO_PUBLICAR\n")
    with pytest.raises(ValueError, match="coluna pessoal proibida"):
        croissant_uf(tmp_path, "PA", {"url": "https://example.org/a", "sha256": "a" * 64})


def test_ficha_recusa_csv_corrompido_sem_copiar_valores(tmp_path):
    (tmp_path / "imoveis_1504950.csv").write_text("cod_imovel,ha\nCAR-A,3\n")
    (tmp_path / "filtros_1504950.csv").write_text("cod_imovel,ha\nCAR-A,3,NAO_PUBLICAR\n")
    with pytest.raises(ValueError, match="baker não descreveu") as erro:
        croissant_uf(tmp_path, "PA", {"url": "https://example.org/a", "sha256": "a" * 64})
    assert "NAO_PUBLICAR" not in str(erro.value)


def test_ficha_arquivo_e_catalogo_sem_fingir_hash_ou_licenca():
    with pytest.raises(ValueError, match="SHA-256"):
        ficha_arquivo("raiz_PA.tar.gz", "https://example.org/a", "versao-curta")
    arquivo = ficha_arquivo("URTX.kml", "https://example.org/URTX.kml", "b" * 64, 100)
    validar(arquivo)
    assert arquivo["recordSet"] == []
    assert "license" not in arquivo
    indice = {
        "gerado_em": "2026-11-12T20:00:00Z",
        "estados": {
            "PA": {
                "croissant": {"url": "https://example.org/croissant_PA.json", "sha256": "c" * 64},
                "fichas": {"raiz_geo_PA.tar.gz": "https://example.org/croissant_geo_PA.json"},
            },
            "AM": {"versao": "antigo-sem-ficha"},
        },
        "fichas": {"URTX.kml": "https://example.org/croissant_URTX.kml.json"},
    }
    catalogo = croissant_release(indice, "exemplo/raiz", "dados")
    validar(catalogo)
    assert len(catalogo["hasPart"]) == 3
    assert {p["name"] for p in catalogo["hasPart"]} == {"raiz_PA.tar.gz", "raiz_geo_PA.tar.gz", "URTX.kml"}
    assert len(catalogo["distribution"]) == 1  # só há hash confirmado para a ficha de PA
    assert "antigo-sem-ficha" not in json.dumps(catalogo)


def test_ficha_deterministica_sem_horario_da_geracao(tmp_path):
    (tmp_path / "imoveis_1504950.csv").write_text("cod_imovel,ha\nCAR-A,3\n")
    entrada = {"url": "https://example.org/raiz_PA.tar.gz", "sha256": "a" * 64, "versao": "1.0.0"}
    assert croissant_uf(tmp_path, "PA", entrada) == croissant_uf(tmp_path, "PA", entrada)


def test_inferencia_le_tambem_os_blocos_posteriores(tmp_path):
    # Arrow infere pelo primeiro MiB. Um decimal posterior não pode ficar
    # descrito como inteiro, senão o consumidor trunca a área do imóvel.
    (tmp_path / "imoveis_1504950.csv").write_text("cod_imovel,ha\n" + "CAR-A,3\n" * 160_000 + "CAR-B,2.5\n")
    ficha = croissant_uf(tmp_path, "PA", {"url": "https://example.org/a", "sha256": "a" * 64})
    campos = {c["name"]: c for c in ficha["recordSet"][0]["field"]}
    assert campos["ha"]["dataType"] == "cr:Float64"
