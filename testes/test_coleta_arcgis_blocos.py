import json

import numpy as np
import pytest
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin

from raiz.coleta import arcgis, blocos
from raiz.coleta.wfs import LeituraIncompleta
from testes.servidor_falso import sessao_falsa

URL = "https://servicos.exemplo/arcgis/rest/services/embargos/FeatureServer/0"


def arcgis_falso(n=7, max_registros=3, edicao=1700000000000, mentir=False):
    def responder(metodo, base, p, h):
        if base == URL:
            return (
                200,
                {},
                json.dumps(
                    {
                        "objectIdField": "OBJECTID",
                        "maxRecordCount": max_registros,
                        "editingInfo": {"lastEditDate": edicao},
                    }
                ),
            )
        if p.get("returnCountOnly") == "true":
            return 200, {}, json.dumps({"count": n + (1 if mentir else 0)})
        ultimo = int(p["where"].split(">")[-1])
        ids = [i for i in range(1, n + 1) if i > ultimo][: int(p["resultRecordCount"])]
        assert p["orderByFields"] == "OBJECTID ASC" and p["outSR"] == "4674"
        feats = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-47.0, -2.0]},
                "properties": {"OBJECTID": i, "SEQ_TAD": f"T{i}"},
            }
            for i in ids
        ]
        return 200, {}, json.dumps({"type": "FeatureCollection", "features": feats})

    return responder


def test_arcgis_pagina_por_objectid_e_pula_sem_edicao():
    s, srv = sessao_falsa(arcgis_falso())
    g, ed = arcgis.ler(s, URL)
    assert list(g.SEQ_TAD) == [f"T{i}" for i in range(1, 8)] and ed == 1700000000000 and g.crs.to_epsg() == 4674
    n = len(srv.pedidos)
    g2, _ = arcgis.ler(s, URL, ultima_edicao_conhecida=1700000000000)
    assert g2 is None and len(srv.pedidos) == n + 1  # só os detalhes da camada


def test_arcgis_incompleto_falha():
    s, _ = sessao_falsa(arcgis_falso(mentir=True))
    with pytest.raises(LeituraIncompleta, match="7 de 8"):
        arcgis.ler(s, URL)


@pytest.fixture
def cog(tmp_path):
    f = tmp_path / "cog.tif"
    dados = (np.arange(64 * 48).reshape(48, 64) % 251).astype("uint8")
    perfil = dict(
        driver="GTiff",
        height=48,
        width=64,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        tiled=True,
        blockxsize=16,
        blockysize=16,
        transform=from_origin(-48.0, -2.0, 0.01, 0.01),
    )
    with rasterio.open(f, "w", **perfil) as d:
        d.write(dados, 1)
        d.build_overviews([2], Resampling.nearest)
    return f, dados


def test_indice_bate_com_o_gdal(cog):
    f, _ = cog
    ind = blocos.indice(f, "cog")
    n0 = ind[ind.nivel == 0]
    assert len(n0) == 4 * 3 and set(ind.nivel) == {0, 1}
    with rasterio.open(f) as src:
        for _, b in n0.sample(5, random_state=1).iterrows():
            off = src.get_tag_item(f"BLOCK_OFFSET_{b.coluna}_{b.linha}", "TIFF", bidx=1)
            assert int(off) == b.offset
    # retângulo do bloco (0,0): canto noroeste
    b00 = n0[(n0.linha == 0) & (n0.coluna == 0)].iloc[0]
    assert (round(b00.x0, 6), round(b00.y1, 6), round(b00.x1, 6), round(b00.y0, 6)) == (-48.0, -2.0, -47.84, -2.16)
    # bytes de um retângulo que cobre só o primeiro bloco
    assert blocos.bytes_no_retangulo(ind, (-47.99, -2.15, -47.85, -2.01)) == b00.bytes


def test_indice_remoto_por_range(cog):
    f, _ = cog
    conteudo = f.read_bytes()

    def responder(metodo, base, p, h):
        if metodo == "HEAD":
            return 200, {"Content-Length": str(len(conteudo))}, ""
        ini, fim = map(int, h["Range"].removeprefix("bytes=").split("-"))
        return 206, {}, conteudo[ini : fim + 1]

    s, _ = sessao_falsa(responder)
    remoto = blocos.ArquivoRemoto("https://nuvem.exemplo/cog.tif", s, bloco=1024)
    ind = blocos.indice(remoto)
    assert ind.equals(blocos.indice(f))
    assert remoto.pedidos * 1024 < len(conteudo) * 2  # só cabeçalhos, não o arquivo todo de novo e de novo


def test_ler_janela(cog):
    f, dados = cog
    m, transform, crs = blocos.ler_janela(str(f), (-47.9, -2.2, -47.8, -2.1))
    assert m.shape == (10, 10) and crs.to_epsg() == 4326
    assert np.array_equal(m, dados[10:20, 10:20])


def _servidor_de(conteudo, etag='"v1"'):
    def responder(metodo, base, p, h):
        if metodo == "HEAD":
            return 200, {"Content-Length": str(len(conteudo)), "ETag": etag}, ""
        ini, fim = map(int, h["Range"].removeprefix("bytes=").split("-"))
        return 206, {}, conteudo[ini : fim + 1]

    return sessao_falsa(responder)


def test_cache_em_disco_le_da_segunda_vez_sem_rede(cog, tmp_path):
    f, dados = cog
    s, srv = _servidor_de(f.read_bytes())
    cache = blocos.CacheDisco(tmp_path / "cache")
    with blocos.abrir_com_cache("https://nuvem.exemplo/cog.tif", cache, s, bloco=1024) as ds:
        assert np.array_equal(ds.read(1), dados)
    gets = sum(1 for p in srv.pedidos if p[0] == "GET")
    with blocos.abrir_com_cache("https://nuvem.exemplo/cog.tif", cache, s, bloco=1024) as ds:
        assert np.array_equal(ds.read(1), dados)
    assert gets > 0 and sum(1 for p in srv.pedidos if p[0] == "GET") == gets  # segunda vez: só o HEAD


def test_cache_poda_e_etag_novo(tmp_path):
    cache = blocos.CacheDisco(tmp_path, limite_gb=3000 / 2**30)  # 3000 bytes
    for i in range(5):
        cache.gravar("k", i, b"x" * 1000)
    cache.podar()
    assert sum(f.stat().st_size for f in tmp_path.glob("*/*.bin")) <= 3000
    assert blocos.CacheDisco.chave("u", '"v1"', 10) != blocos.CacheDisco.chave("u", '"v2"', 10)


def test_ponte_raster_troca_e_devolve(cog, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from raiz.funil import ponte

    f, dados = cog
    s, _ = _servidor_de(f.read_bytes())
    monkeypatch.setattr(blocos, "requests", SimpleNamespace(Session=lambda: s))
    modulo = SimpleNamespace(U={"idade": "/vsicurl/https://nuvem.exemplo/cog.tif", "local": "/tmp/x.tif"})
    original = modulo.U
    with ponte.ponte_raster(modulo, cache=blocos.CacheDisco(tmp_path)) as u:
        assert u["local"] == "/tmp/x.tif" and np.array_equal(u["idade"].read(1), dados)
    assert modulo.U is original
