"""Limites secundários: checksum, licença, país e exclusão de pontos/dados livres."""

import hashlib
import json

import geopandas as gpd
import httpx
import pytest
from shapely.geometry import Point, box

from raiz.coleta import compromissos_pesquisa as pesquisa


@pytest.fixture
def arquivo(tmp_path):
    caminho = tmp_path / "south_america.gpkg"
    gpd.GeoDataFrame(
        {
            "ProjectID": ["ECO123", "ACR1", "VCS1"],
            "Registry Name": ["EcoRegistry", "American Carbon Registry", "Verra"],
            "Geometry Type": ["Polygon", "Point", "Polygon"],
            "Country": ["Brazil", "Brazil", "Peru"],
            "Project Start Date": ["01/01/2020"] * 3,
            "Project End Date": ["01/01/2050"] * 3,
            "Owner": ["NAO_PUBLICAR"] * 3,
            "geometry": [box(-60, -10, -59.9, -9.9), Point(-60, -10), box(-70, -10, -69.9, -9.9)],
        },
        crs=4326,
    ).to_file(caminho, driver="GPKG")
    return caminho


def metadados(arquivo):
    return {
        "id": 11459391,
        "metadata": {"license": {"id": "cc-by-4.0"}, "publication_date": "2024-06-01"},
        "files": [
            {
                "key": pesquisa.ARQUIVO,
                "checksum": "md5:" + hashlib.md5(arquivo.read_bytes()).hexdigest(),
                "size": arquivo.stat().st_size,
            }
        ],
    }


def test_apenas_poligonos_brasileiros_sem_contato_e_com_certeza_secundaria(arquivo):
    meta = metadados(arquivo)
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=meta))) as c:
        resultado = pesquisa.coletar_limites_pesquisa(arquivo=arquivo, cliente=c, observado_em="2026-11-12")
    assert len(resultado["registros"]) == 1
    r = resultado["registros"][0]
    assert r["registro"] == "ECOREGISTRY" and r["certeza"] == "poligono_secundario"
    assert r["situacao"] == "desconhecido" and r["inicio"] == "2020-01-01"
    assert r["data_referencia"] is None
    assert resultado["cobertura"]["estado"] == "parcial"
    assert "NAO_PUBLICAR" not in json.dumps(resultado, default=str)


@pytest.mark.parametrize("mudanca", ["checksum", "licenca", "versao"])
def test_cache_local_tambem_exige_integridade_e_licenca(arquivo, mudanca):
    meta = metadados(arquivo)
    if mudanca == "checksum":
        meta["files"][0]["checksum"] = "md5:" + "0" * 32
    elif mudanca == "licenca":
        meta["metadata"]["license"]["id"] = "cc-by-nc-4.0"
    else:
        meta["id"] = 1
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=meta))) as c:
        with pytest.raises(ValueError):
            pesquisa.coletar_limites_pesquisa(arquivo=arquivo, cliente=c)
