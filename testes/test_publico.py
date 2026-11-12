"""Link público, cartão e vídeo pelo código curto (design v1, item 6): sem token, só município, hectares, selo e
código antes do aceite; pesos e tamanhos dos cartões; Open Graph; vídeo em 1080 e 720p."""

import datetime as dt
import io
import shutil
import subprocess

import pytest
from PIL import Image
from sqlalchemy import create_engine, text

from raiz import publico
from testes.conftest import AMOSTRA

pytestmark = pytest.mark.banco
TEM_TAKUMI = shutil.which("node") and (publico.SERVICO / "node_modules" / "@takumi-rs" / "core").exists()
TEM_FFMPEG = shutil.which("ffmpeg") is not None


@pytest.fixture
def cliente(banco_url, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    import raiz.api as api_mod
    from raiz.api import criar_app
    from raiz.carga import carregar_municipio

    eng = create_engine(banco_url)
    with eng.begin() as c:
        c.execute(text("truncate funil.rodada, funil.imovel, funil.vigente, funil.municipio_busca cascade"))
        c.execute(text("truncate negocio.codigo_curto, negocio.aceite cascade"))
    pasta = tmp_path / "PA"
    pasta.mkdir()
    shutil.copy(AMOSTRA / "imoveis_1504950.csv", pasta / "imoveis_1504950.csv")
    with eng.begin() as c:
        carregar_municipio(c, pasta, 1504950, dt.date(2026, 11, 12))
        cod, codigo = c.execute(
            text("""select k.cod_imovel, k.codigo from negocio.codigo_curto k
                    join funil.resultado_imovel r on r.cod_imovel = k.cod_imovel where r.carbono_ha > 10 limit 1""")
        ).one()
    monkeypatch.setattr(publico, "pasta", lambda: tmp_path / "publico")
    cfg = type("C", (), {"api_token": SecretStr("t"), "api_origens": ""})()
    monkeypatch.setattr(api_mod, "config", lambda: cfg)
    app = criar_app(engine=eng, grafo=object(), deps=object(), whatsapp=False)
    with TestClient(app) as cl:  # sem token: rotas públicas
        yield cl, eng, cod, codigo
    eng.dispose()


def test_pagina_publica_sem_dado_antes_do_aceite(cliente):
    cl, eng, cod, codigo = cliente
    r = cl.get(f"/p/{codigo}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    h = r.text
    assert len(r.content) <= 150 * 1024
    assert 'property="og:image"' in h and f"/cartao/{codigo}/previa.jpg" in h and 'property="og:title"' in h
    assert "Nova Esperança do Piriá" in h and "Selo bronze" in h and codigo in h
    assert cod not in h and "CAR PA-" not in h  # código do CAR só depois do aceite
    assert cl.get(f"/p/{codigo}/satelite.webp").status_code == 404
    assert cl.get(f"/p/{codigo.lower()}").status_code == 200
    assert cl.get("/p/ZZZZZZZ").status_code == 404 and cl.get("/p/não-existe").status_code == 404
    assert cl.get("/municipios").status_code in (401, 503)  # as rotas internas continuam pedindo token
    with eng.begin() as c:
        c.execute(text("insert into negocio.aceite (cod_imovel, estado) values (:c, 'aceito')"), {"c": cod})
    h2 = cl.get(f"/p/{codigo}").text
    assert cod in h2 and "Selo ouro" in h2


@pytest.mark.skipif(not TEM_TAKUMI, reason="Takumi não instalado (npm ci em servicos/cartao)")
def test_cartoes_tamanho_e_peso(cliente):
    cl, eng, cod, codigo = cliente
    for nome, tam, tipo, max_kb in (
        ("previa.jpg", (1200, 630), "image/jpeg", 250),
        ("retrato.jpg", (1080, 1350), "image/jpeg", 600),
        ("adesivo.png", (512, 512), "image/png", 300),
        # WebP para a ficha e o site: mais leve que o JPEG e o PNG
        ("previa.webp", (1200, 630), "image/webp", 150),
        ("retrato.webp", (1080, 1350), "image/webp", 350),
        ("adesivo.webp", (512, 512), "image/webp", 150),
    ):
        r = cl.get(f"/cartao/{codigo}/{nome}")
        assert r.status_code == 200 and r.headers["content-type"] == tipo, nome
        img = Image.open(io.BytesIO(r.content))
        assert img.size == tam and len(r.content) < max_kb * 1024, (nome, img.size, len(r.content))
        if nome.startswith("adesivo"):
            assert img.convert("RGBA").getpixel((0, 0))[3] == 0  # fundo transparente
    assert len(cl.get(f"/cartao/{codigo}/previa.webp").content) < len(cl.get(f"/cartao/{codigo}/previa.jpg").content)
    assert cl.get(f"/cartao/{codigo}/previa.png").status_code == 404
    assert cl.get(f"/cartao/{codigo}/adesivo.jpg").status_code == 404
    assert cl.get(f"/cartao/{codigo}/outro.jpg").status_code == 404
    # o cartão mostra o selo novo quando o dono aceita (o cache é refeito)
    antes = cl.get(f"/cartao/{codigo}/previa.jpg").content
    with eng.begin() as c:
        c.execute(text("insert into negocio.aceite (cod_imovel, estado) values (:c, 'aceito')"), {"c": cod})
    assert cl.get(f"/cartao/{codigo}/previa.jpg").content != antes


@pytest.mark.skipif(not (TEM_TAKUMI and TEM_FFMPEG), reason="Takumi ou FFmpeg não instalados")
def test_video_1080_e_720p(cliente, tmp_path):
    cl, _, _, codigo = cliente
    for nome, (w, h) in ((f"{codigo}.mp4", (1080, 1920)), (f"{codigo}-720p.mp4", (720, 1280))):
        r = cl.get(f"/video/{nome}")
        assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
        f = tmp_path / nome
        f.write_bytes(r.content)
        info = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,codec_name",
             "-of", "csv=p=0", str(f)], capture_output=True, text=True,
        ).stdout.strip()  # fmt: skip
        assert info == f"h264,{w},{h}", info
        assert r.headers.get("x-raiz-aviso") in (None, "sem voz")
