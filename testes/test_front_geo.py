"""TI/UC ficam dentro da divisa: gerador real, sem depender de arquivos fora do git.

Substitui as duas conferências Vitest puladas sem front/geo. Só o WFS é falso;
as rotinas de baixar/recortar/salvar recebem município côncavo com uma ilha,
áreas que cruzam a divisa, área inteiramente fora e contato apenas pela borda.
"""

import importlib.util
import json
from types import SimpleNamespace

import pytest
from shapely.geometry import MultiPolygon, Polygon, box, mapping, shape

from raiz import RAIZ_REPO


@pytest.fixture
def geo(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("front_geo_teste", RAIZ_REPO / "front/scripts/geo.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    monkeypatch.setattr(modulo, "SAIDA", tmp_path)
    return modulo


@pytest.mark.parametrize(("camada", "campo"), [("ti", "terrai_nom"), ("uc", "nome")])
def test_camada_e_cache_antigo_nao_passam_da_divisa(geo, tmp_path, monkeypatch, camada, campo):
    concavo = Polygon([(0, 0), (10, 0), (10, 10), (7, 10), (7, 3), (3, 3), (3, 10), (0, 10), (0, 0)])
    divisa = MultiPolygon([concavo, box(12, 3, 14, 5)])
    areas = {
        "cruza": box(-1, 2, 15, 9),
        "dentro": box(0.25, 0.25, 1, 1),
        "fora": box(4, 4, 6, 8),
        "borda": box(14, 3, 15, 4),
    }
    bruto = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {campo: nome, "ignorar": "não publicar"}, "geometry": mapping(g)}
            for nome, g in areas.items()
        ],
    }
    pedidos = []

    def baixar(_url, params, **_kwargs):
        pedidos.append(params)
        return SimpleNamespace(json=lambda: bruto)

    monkeypatch.setattr(geo, "baixar", baixar)
    arquivo = tmp_path / f"{camada}_1507300.geojson"

    def conferir():
        feicoes = json.loads(arquivo.read_text())["features"]
        assert {f["properties"]["nome"] for f in feicoes} == {"cruza", "dentro"}
        for f in feicoes:
            g = shape(f["geometry"])
            assert g.is_valid and g.area > 0
            assert divisa.covers(g), "não basta estar na caixa: precisa respeitar a concavidade e a ilha"
            assert g.equals(areas[f["properties"]["nome"]].intersection(divisa))
            assert set(f["properties"]) == {"nome"}

    geo.camada_tb("1507300", camada, f"teste:{camada}", divisa.bounds, {campo: "nome"}, 0.0005, dentro=divisa)
    assert len(pedidos) == 1 and pedidos[0]["typeName"] == f"teste:{camada}"
    conferir()

    # Arquivo de versão antiga: o caminho do cache também precisa refazer o recorte.
    antigo = {
        "type": "FeatureCollection",
        "features": [geo.feicao(g, {"nome": nome}) for nome, g in areas.items()],
    }
    arquivo.write_text(json.dumps(antigo))
    geo.camada_tb("1507300", camada, f"teste:{camada}", divisa.bounds, {campo: "nome"}, 0.0005, dentro=divisa)
    assert len(pedidos) == 1, "corrigir o cache não deve baixar de novo"
    conferir()
