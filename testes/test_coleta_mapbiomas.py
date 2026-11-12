import io
import json
import zipfile

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from raiz.coleta import mapbiomas as MB
from testes.servidor_falso import sessao_falsa

BASE = "https://prd.plataforma.mapbiomas.org/api/v1/brazil"


def _tif(caminho, dados):
    with rasterio.open(
        caminho,
        "w",
        driver="GTiff",
        height=dados.shape[0],
        width=dados.shape[1],
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(-47.30, -2.29, 0.001, 0.001),
    ) as d:
        d.write(dados, 1)


def test_api_da_plataforma(tmp_path):
    estado = {"consultas": 0}
    cobertura = np.full((10, 10), 3, dtype="uint8")
    _tif(tmp_path / "c.tif", cobertura)
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zz:
        zz.write(tmp_path / "c.tif", "export/coverage_2024.tif")

    def responder(metodo, base, p, h):
        assert h["tenant-id"] == "mapbiomas"
        if "/territories/search/" in base:
            return (
                200,
                {},
                json.dumps(
                    [
                        {"id": 11, "name": "Nova Esperança do Piriá", "category": {"id": 230}},
                        {"id": 12, "name": "Nova Esperança", "category": {"id": 230}},
                        {"id": 99, "name": "Nova Esperança do Piriá", "category": {"id": 1}},
                    ]
                ),
            )
        if metodo == "POST":
            return 200, {}, json.dumps({"id": "exp-1"})
        if base.endswith("/download"):
            return 200, {}, z.getvalue()
        estado["consultas"] += 1
        return 200, {}, json.dumps({"status": "READY" if estado["consultas"] >= 3 else "PROCESSING"})

    s, srv = sessao_falsa(responder)
    assert MB.territorio_municipio(s, "Nova Esperança do Piriá", "PA") == 11
    zb = MB.exportar(s, 11, "coverage_coverage-30m-droufo", [2023, 2024], dormir=lambda _: None)
    corpo = [p for p in srv.pedidos if p[0] == "POST"][0]
    assert estado["consultas"] == 3
    tifs = MB.extrair_tifs(zb, tmp_path / "saida")
    assert [t.name for t in tifs] == ["coverage_2024.tif"]
    assert corpo[1] == f"{BASE}/maps/exports"


def test_exportacao_com_erro(tmp_path):
    s, _ = sessao_falsa(lambda m, b, p, h: (200, {}, json.dumps({"id": 1} if m == "POST" else {"status": "FAILED"})))
    with pytest.raises(MB.ErroMapBiomas, match="FAILED"):
        MB.exportar(s, 1, "x", [2024], dormir=lambda _: None)


def test_transicoes_por_imovel(tmp_path):
    de = np.full((10, 10), 3, dtype="uint8")  # floresta
    para = de.copy()
    para[:, :5] = 15  # metade oeste virou pasto
    _tif(tmp_path / "a.tif", de)
    _tif(tmp_path / "b.tif", para)
    imoveis = gpd.GeoDataFrame(
        {"cod_imovel": ["OESTE", "LESTE"]},
        geometry=[box(-47.30, -2.30, -47.295, -2.29), box(-47.295, -2.30, -47.29, -2.29)],
        crs=4326,
    )
    t = MB.transicoes(tmp_path / "a.tif", tmp_path / "b.tif", imoveis)
    oeste = t[t.cod_imovel == "OESTE"]
    assert list(zip(oeste.de, oeste.para, oeste.pixels, strict=True)) == [(3, 15, 50)]
    assert list(t[t.cod_imovel == "LESTE"].para) == [3]
    # 50 pixels de ~0,001 grau perto do equador ~ 61 ha
    assert 55 < oeste.ha.iloc[0] < 65
