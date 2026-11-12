"""Satélite por fazenda (design v1, item 1): escolha da cena pela máscara de nuvem, mediana, pesos das imagens e rotas.

Sem rede: o catálogo STAC é um servidor falso (httpx.MockTransport) e a leitura dos COGs devolve matrizes prontas."""

import io
import json

import httpx
import numpy as np
import pytest
from PIL import Image
from scipy.ndimage import gaussian_filter
from shapely.geometry import box

from raiz import satelite as S

GEOM = box(-47.30, -2.30, -47.26, -2.27)
PODE_VOLTAR = box(-47.29, -2.29, -47.27, -2.28)


def _textura(h=1100, w=1300, semente=1):
    """Imagem com cara de satélite: manchas suaves de mata e pasto, estradas e ruído fino (comprime como as reais)."""
    rng = np.random.default_rng(semente)
    base = gaussian_filter(rng.normal(size=(h, w)), 25)
    mata = base > 0
    img = np.zeros((h, w, 3))
    img[mata] = (35, 70, 40)
    img[~mata] = (170, 140, 110)
    img += gaussian_filter(rng.normal(size=(h, w, 3)) * 40, (1.2, 1.2, 0))
    img += rng.normal(size=(h, w, 3)) * 6
    for k in range(0, w, 180):
        img[:, k : k + 3] = (220, 200, 170)
    return np.clip(img, 0, 255).astype(np.uint8)


def _cena():
    return S.Cena(_textura(), S.caixa_com_margem(GEOM), "2026-10-28", "Sentinel-2C", S.credito_s2("2026"), "cena")


@pytest.mark.parametrize("tipo", ["hoje", "hoje-produtor", "hoje-celular", "simulacao"])
def test_peso_e_tamanho_das_imagens(tipo):
    img = S.desenhar(_cena(), tipo, GEOM, PODE_VOLTAR)
    t = S.TIPOS[tipo]
    dado = S.webp(img, t["max_kb"], t["min_kb"])
    w, h = Image.open(io.BytesIO(dado)).size
    assert max(w, h) == t["px"]
    assert len(dado) <= t["max_kb"] * 1024, (tipo, len(dado))
    if tipo == "hoje":
        assert len(dado) < 150 * 1024
    if tipo == "hoje-produtor":
        assert 40 * 1024 <= len(dado) <= 80 * 1024, len(dado)


def test_desenho_do_produtor_e_da_simulacao():
    hoje = np.asarray(S.desenhar(_cena(), "hoje-celular", GEOM, PODE_VOLTAR)).astype(int)
    prod = np.asarray(S.desenhar(_cena(), "hoje-produtor", GEOM, PODE_VOLTAR).resize((480, 480 * 1100 // 1300)))
    sim = np.asarray(S.desenhar(_cena(), "simulacao", GEOM, PODE_VOLTAR)).astype(int)
    assert prod[2, 2].sum() < hoje[2, 2].sum()  # entorno escurecido
    assert (sim[20:40, 20:120] >= 240).all(axis=-1).mean() > 0.3  # selo "Simulação" (fundo branco) no canto
    h, w = sim.shape[:2]
    cx, cy = (
        int((-47.28 - S.caixa_com_margem(GEOM)[0]) / (S.caixa_com_margem(GEOM)[2] - S.caixa_com_margem(GEOM)[0]) * w),
        h // 2,
    )
    assert sim[cy, cx, 1] > sim[cy, cx, 0]  # copa verde pintada onde pode voltar


def _stac(features):
    def servir(req):
        return httpx.Response(200, json={"features": features})

    return httpx.Client(transport=httpx.MockTransport(servir))


def _item(i, data):
    return {
        "id": f"S2C_{i}",
        "geometry": json.loads(json.dumps(box(-48, -3, -46, -1).__geo_interface__)),
        "properties": {"datetime": f"{data}T13:00:00Z", "platform": "sentinel-2c", "eo:cloud_cover": 10},
        "assets": {"visual": {"href": f"visual-{i}"}, "scl": {"href": f"scl-{i}"}},
    }


def test_escolhe_a_cena_mais_recente_sem_nuvem():
    itens = [_item(1, "2026-11-10"), _item(2, "2026-11-05"), _item(3, "2026-10-28")]
    nuvem = {"scl-1": 9, "scl-2": 4, "scl-3": 4}  # a mais recente tem nuvem (9); a seguinte está limpa (4 = vegetação)

    def ler(href, caixa, banda_shape=None, **kw):
        if href.startswith("scl"):
            return np.full((1, *banda_shape), nuvem[href], dtype=np.uint8)
        return np.full((3, 50, 60), int(href[-1]) * 40, dtype=np.uint8)

    c = S.cena_sentinel(GEOM, cliente=_stac(itens), ler=ler)
    assert c.data == "2026-11-05" and c.metodo == "cena" and c.satelite == "Sentinel-2C"
    assert c.credito == "Contains modified Copernicus Sentinel data 2026" and (c.rgb == 80).all()


def test_mediana_quando_todas_tem_nuvem():
    itens = [_item(i, f"2026-10-{10 + i}") for i in range(1, 4)]

    def ler(href, caixa, banda_shape=None, **kw):
        if href.startswith("scl"):
            a = np.full((1, *banda_shape), 4, dtype=np.uint8)
            a[0, :10] = 9  # 20% de nuvem em cada uma, em cima
            return a
        return np.full((3, 50, 60), int(href[-1]) * 30, dtype=np.uint8)

    c = S.cena_sentinel(GEOM, cliente=_stac(itens), ler=ler)
    assert c.metodo == "mediana" and c.data == "2026-10-11 a 2026-10-13"
    assert (c.rgb[20:] == 60).all()  # mediana de 30, 60 e 90


def test_rotas_de_imagem(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    import raiz.api as api_mod
    import raiz.front_api as F
    from raiz.api import criar_app

    monkeypatch.setattr(S, "pasta", lambda: tmp_path)
    p = tmp_path / "PA15049500016"
    S.salvar(p, "hoje", _cena(), S.desenhar(_cena(), "hoje", GEOM))
    monkeypatch.setattr(F, "imoveis_do_municipio", lambda *a, **k: [])
    monkeypatch.setattr(F, "nao_achado", lambda e, c: {"mensagem": "não achado"})
    cfg = type("C", (), {"api_token": SecretStr("t"), "api_origens": ""})()
    monkeypatch.setattr(api_mod, "config", lambda: cfg)

    class EngFalso:
        def connect(self):
            class C:
                def __enter__(s):
                    return s

                def __exit__(s, *a):
                    return False

                def execute(s, *a, **k):
                    class R:
                        def first(s):
                            return None

                    return R()

            return C()

    app = criar_app(engine=EngFalso(), grafo=object(), deps=object(), whatsapp=False)
    with TestClient(app, headers={"Authorization": "Bearer t"}) as cl:
        r = cl.get("/imoveis/pa-1504950-0016/imagem/hoje.webp")
        assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
        assert r.headers["x-raiz-credito"] == "Contains modified Copernicus Sentinel data 2026"
        assert r.headers["x-raiz-data-cena"] == "2026-10-28" and len(r.content) < 150 * 1024
        m = cl.get("/imoveis/PA-1504950-0016/imagem/hoje.json").json()
        assert m["satelite"] == "Sentinel-2C" and m["largura"] == 1024 and m["bytes"] == len(r.content)
        assert cl.get("/imoveis/PA-1504950-0016/imagem/qualquer.webp").status_code == 404
        assert cl.get("/imoveis/PA-1504950-0016/imagem/1985.webp").status_code == 404  # sem polígono no banco


def test_capa_com_thumbhash(tmp_path, monkeypatch):
    """A foto do produtor grava o ThumbHash; imagem antiga sem ele ganha o dela na primeira leitura da capa."""
    from raiz.thumbhash import hash_para_rgba

    monkeypatch.setattr(S, "pasta", lambda: tmp_path)
    assert S.capa("PA15049500016") is None  # ainda não gerada: a ficha não espera o satélite
    p = tmp_path / "PA15049500016"
    meta = S.salvar(p, "hoje-produtor", _cena(), S.desenhar(_cena(), "hoje-produtor", GEOM, PODE_VOLTAR))
    assert meta.thumbhash and 20 <= len(__import__("base64").b64decode(meta.thumbhash)) <= 30
    c = S.capa("PA15049500016")
    assert c["caminho"] == "imoveis/PA15049500016/imagem/hoje-produtor.webp"
    assert c["thumbhash"] == meta.thumbhash and (c["largura"], c["altura"]) == (meta.largura, meta.altura)
    # o borrão tem a proporção da foto
    w, h, _ = hash_para_rgba(__import__("base64").b64decode(c["thumbhash"]))
    assert abs(w / h - meta.largura / meta.altura) < 0.35
    # metadados de antes do ThumbHash
    mf = p / "metadados.json"
    tudo = json.loads(mf.read_text(encoding="utf-8"))
    tudo["hoje-produtor"].pop("thumbhash")
    mf.write_text(json.dumps(tudo), encoding="utf-8")
    assert S.capa("PA15049500016")["thumbhash"]
    assert json.loads(mf.read_text(encoding="utf-8"))["hoje-produtor"]["thumbhash"]


def test_foto_da_pagina_publica_com_borrao(tmp_path, monkeypatch):
    from raiz import publico

    monkeypatch.setattr(S, "pasta", lambda: tmp_path)
    S.salvar(tmp_path / "PA15049500016", "hoje-produtor", _cena(), S.desenhar(_cena(), "hoje-produtor", GEOM))
    h = publico._foto({"codigo": "K7M2Q9X", "_cod_busca": "PA15049500016"}, "https://raiz.exemplo")
    assert 'src="https://raiz.exemplo/p/K7M2Q9X/satelite.webp"' in h and 'width="720"' in h
    assert "background:url(data:image/png;base64," in h and "Copernicus" in h
