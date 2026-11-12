"""Mapa base do Brasil (design v1, item 5): manifesto, PMTiles com Range, fontes e sprites, e nomes que não servem."""

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from raiz import mapa_base


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    import raiz.api as api_mod
    from raiz.api import criar_app

    pm = tmp_path / "brasil_20261111.pmtiles"
    pm.write_bytes(bytes(range(256)) * 64)
    (tmp_path / "fontes" / "Noto Sans Regular").mkdir(parents=True)
    (tmp_path / "fontes" / "Noto Sans Regular" / "0-255.pbf").write_bytes(b"letras")
    (tmp_path / "sprites").mkdir()
    (tmp_path / "sprites" / "light.json").write_text('{"x": 1}')
    (tmp_path / "sprites" / "light@2x.png").write_bytes(b"\x89PNG")
    mapa_base.gravar_manifesto(pm, "20261111", tmp_path)
    monkeypatch.setattr(mapa_base, "pasta", lambda: tmp_path)
    cfg = type("C", (), {"api_token": SecretStr("t"), "api_origens": ""})()
    monkeypatch.setattr(api_mod, "config", lambda: cfg)
    app = criar_app(engine=object(), grafo=object(), deps=object(), whatsapp=False)
    with TestClient(app, headers={"Authorization": "Bearer t"}) as cl:
        yield cl


def test_manifesto_e_range(cliente):
    m = cliente.get("/mapa/manifesto.json").json()
    assert m["arquivo"] == "brasil_20261111.pmtiles" and m["zoom_max"] == 14 and "OpenStreetMap" in m["atribuicao"]
    r = cliente.get("/mapa/brasil.pmtiles", headers={"Range": "bytes=0-126"})
    assert r.status_code == 206 and len(r.content) == 127 and r.headers["content-range"] == "bytes 0-126/16384"
    assert "gzip" not in r.headers.get("content-encoding", "")  # o PMTiles nunca vai recomprimido


def test_fontes_e_sprites(cliente):
    assert cliente.get("/mapa/fontes/Noto Sans Regular/0-255.pbf").content == b"letras"
    assert cliente.get("/mapa/sprites/light.json").json() == {"x": 1}
    assert cliente.get("/mapa/sprites/light@2x.png").headers["content-type"] == "image/png"
    for url in (
        "/mapa/fontes/Arial/0-255.pbf",
        "/mapa/fontes/Noto Sans Regular/..%2F..%2Fsegredo.pbf",
        "/mapa/sprites/qualquer.json",
        "/mapa/sprites/light.svg",
        "/mapa/fontes/Noto Sans Medium/0-255.pbf",  # fonte certa, arquivo não baixado
    ):
        assert cliente.get(url).status_code == 404, url


def test_sem_mapa(tmp_path, monkeypatch):
    monkeypatch.setattr(mapa_base, "pasta", lambda: tmp_path)
    assert mapa_base.manifesto() is None and mapa_base.arquivo_atual() is None
