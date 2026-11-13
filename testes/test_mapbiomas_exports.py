"""Fila e cache MapBiomas com HTTP simulado e GeoTIFFs reais; não consulta nem cria exports remotos."""

import io
import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import requests
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "motor"))
import raiz_mapbiomas as M  # noqa: E402


def resposta(status=200, objeto=None, dados=None, headers=None):
    r = requests.Response()
    r.status_code = status
    r._content = dados if dados is not None else json.dumps(objeto or {}).encode()
    r.headers.update(headers or {})
    return r


def tiff(*, big=False, crs="EPSG:4326"):
    with MemoryFile() as m:
        with m.open(
            driver="GTiff",
            width=2,
            height=2,
            count=1,
            dtype="uint8",
            transform=from_origin(-40, -4, 0.01, 0.01),
            crs=crs,
            BIGTIFF="YES" if big else "NO",
        ) as src:
            src.write(np.ones((1, 2, 2), dtype="uint8"))
        return m.read()


def zipado(arquivos):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for nome, dados in arquivos.items():
            z.writestr(nome, dados)
    return b.getvalue()


@pytest.fixture
def mundo(tmp_path, monkeypatch):
    relogio = {"agora": 1000.0, "esperas": []}

    def dormir(segundos):
        relogio["esperas"].append(segundos)
        relogio["agora"] += segundos

    monkeypatch.setattr(M, "time", SimpleNamespace(time=lambda: relogio["agora"], sleep=dormir))
    monkeypatch.setattr(M, "CACHE", str(tmp_path))
    monkeypatch.delenv("RAIZ_PRAZO", raising=False)
    monkeypatch.setattr(M, "estado", lambda uf, prazo=None: 123)
    chamadas, respostas = [], []

    def pedir(metodo, url, **kwargs):
        chamadas.append((metodo, url.removeprefix(M.API), kwargs))
        assert respostas, f"pedido excedente: {metodo}"
        esperado, rota, r = respostas.pop(0)
        assert (metodo, url.removeprefix(M.API)) == (esperado, rota)
        return r

    monkeypatch.setattr(M.requests, "request", pedir)
    return SimpleNamespace(pasta=tmp_path, relogio=relogio, chamadas=chamadas, respostas=respostas)


def pedido(mundo, tema, id="aceito"):
    pasta = mundo.pasta / "RN"
    pasta.mkdir(exist_ok=True)
    arquivo = pasta / "pedidos.json"
    p = json.loads(arquivo.read_text()) if arquivo.exists() else {}
    chave, ano = M.TEMAS[tema]
    p[tema] = {"id": id, "chave": chave, "ano": ano, "em": -50 * 86400}
    arquivo.write_text(json.dumps(p))
    return arquivo


def pronto(mundo, id="aceito", dados=None):
    mundo.respostas.extend(
        [
            ("GET", f"/maps/exports/{id}", resposta(objeto={"status": "READY"})),
            ("GET", f"/maps/exports/{id}/download", resposta(dados=dados or tiff())),
        ]
    )


def criar(mundo, id="novo"):
    mundo.respostas.append(("POST", "/maps/exports", resposta(201, {"exports": [{"id": id}]})))


def test_consome_cache_antes_de_nova_exportacao_e_preserva_payload(mundo):
    fp = pedido(mundo, "cobertura", "cobertura-antiga")
    pedido(mundo, "desmat", "desmat-antigo")
    pronto(mundo, "cobertura-antiga")
    mundo.respostas.append(("GET", "/maps/exports/desmat-antigo", resposta(objeto={"status": "QUEUED"})))
    pronto(mundo, "desmat-antigo")
    criar(mundo)
    pronto(mundo, "novo")
    out = M.exporta_uf("RN", temas=("cobertura", "desmat", "pasto_idade"))
    assert len(out) == 3 and all(Path(p).exists() for p in out.values())
    post = [c for c in mundo.chamadas if c[0] == "POST"]
    assert len(post) == 1
    assert post[0][2]["json"] == {
        "territoryId": 123,
        "subthemeKey": M.TEMAS["pasto_idade"][0],
        "years": [2025],
        "exportType": "range",
    }
    assert mundo.chamadas.index(post[0]) == 5
    assert mundo.relogio["esperas"] == [30] and json.loads(fp.read_text()) == {}


def test_cinco_temas_sequenciais_sem_descartar_produto(mundo):
    for tema in M.TEMAS:
        criar(mundo, tema)
        pronto(mundo, tema)
    out = M.exporta_uf("RN")
    assert set(out) == set(M.TEMAS)
    assert [c[0] for c in mundo.chamadas] == ["POST", "GET", "GET"] * 5
    assert [c[2]["json"]["subthemeKey"] for c in mundo.chamadas if c[0] == "POST"] == [
        chave for chave, ano in M.TEMAS.values()
    ]
    assert not mundo.respostas


def test_quota_explicita_espera_e_limita_tentativas(mundo):
    mundo.respostas.extend([("POST", "/maps/exports", resposta(422, {"message": "Request limit reached"}))] * 8)
    with pytest.raises(RuntimeError, match="quota.*oito tentativas"):
        M.exporta_uf("RN", temas=("cobertura",))
    assert len(mundo.chamadas) == 8
    assert mundo.relogio["esperas"] == [30, 60, 120, 240, 300, 300, 300]
    assert not (mundo.pasta / "RN/pedidos.json").exists()


def test_quota_recupera_com_retry_after_e_nao_muda_ano(mundo):
    mundo.respostas.append(
        ("POST", "/maps/exports", resposta(422, {"code": "request_limit"}, headers={"Retry-After": "75"}))
    )
    criar(mundo)
    pronto(mundo, "novo")
    M.exporta_uf("RN", temas=("cobertura",))
    assert mundo.relogio["esperas"] == [75]
    assert [c[2]["json"]["years"] for c in mundo.chamadas if c[0] == "POST"] == [[2025], [2025]]


@pytest.mark.parametrize(
    "corpo",
    [
        {"message": "invalid subthemeKey"},
        {"message": "invalid limit"},
        {"field": "quota", "message": "invalid"},
        {},
        None,
    ],
)
def test_422_ambiguo_ou_validacao_falha_sem_repeticao(mundo, corpo, capsys):
    mundo.respostas.append(
        ("POST", "/maps/exports", resposta(422, corpo, dados=b"<html>erro</html>" if corpo is None else None))
    )
    with pytest.raises(RuntimeError, match="quota não confirmada"):
        M.exporta_uf("RN", temas=("pasto_vigor",))
    assert len(mundo.chamadas) == 1 and not mundo.relogio["esperas"]
    assert "invalid" not in capsys.readouterr().out


def test_prazo_preserva_pedido_sem_repost_e_baixa_pronto_antes(mundo):
    fp = pedido(mundo, "cobertura", "pronto")
    pedido(mundo, "desmat", "esperando")
    pronto(mundo, "pronto")
    mundo.respostas.append(("GET", "/maps/exports/esperando", resposta(objeto={"status": "QUEUED"})))
    with pytest.raises(RuntimeError, match="prazo.*pedidos aceitos"):
        M.exporta_uf("RN", espera=20, temas=("cobertura", "desmat", "fogo"))
    assert json.loads(fp.read_text())["desmat"]["id"] == "esperando"
    assert set(json.loads(fp.read_text())) == {"desmat"}
    assert (mundo.pasta / "RN/RN_cobertura_2025.tif").exists()
    assert all(c[0] == "GET" for c in mundo.chamadas)


def test_prazo_job_limita_retry_quota(mundo, monkeypatch):
    monkeypatch.setenv("RAIZ_PRAZO", "1140")  # 20 s úteis, reservando 120 s para publicação
    mundo.respostas.append(("POST", "/maps/exports", resposta(422, {"message": "Too many maps"})))
    with pytest.raises(RuntimeError, match="prazo"):
        M.exporta_uf("RN", temas=("cobertura",))
    assert len(mundo.chamadas) == 1 and not mundo.relogio["esperas"]


def test_prazo_http_nao_dorme_alem_do_limite(mundo):
    mundo.respostas.append(("GET", "/teste", resposta(503)))
    with pytest.raises(RuntimeError, match="prazo"):
        M._get(M.API + "/teste", prazo=1020)
    assert mundo.chamadas[0][2]["timeout"] == 20
    assert not mundo.relogio["esperas"]


@pytest.mark.parametrize("falha", [resposta(400, {"erro": "privado"}), resposta(dados=b'{"erro":"privado"}')])
def test_download_ruim_nao_vira_cache_e_preserva_id(mundo, falha):
    fp = pedido(mundo, "cobertura")
    mundo.respostas.extend(
        [
            ("GET", "/maps/exports/aceito", resposta(objeto={"status": "READY"})),
            ("GET", "/maps/exports/aceito/download", falha),
        ]
    )
    with pytest.raises(RuntimeError):
        M.exporta_uf("RN", temas=("cobertura",))
    assert not list((mundo.pasta / "RN").glob("*.tif*"))
    assert json.loads(fp.read_text())["cobertura"]["id"] == "aceito"


@pytest.mark.parametrize("big", [False, True])
def test_tiff_classico_e_bigtiff_validados(big):
    b = tiff(big=big)
    assert M._geotiff(b) == b
    assert M._geotiff(zipado({"ano.TIFF": b, "README.txt": b"licenca"})) == b


@pytest.mark.parametrize("nomes", [[], ["a.tif", "b.tif"]])
def test_zip_sem_tiff_ou_ambiguo_recusado(nomes):
    with pytest.raises(RuntimeError, match="exatamente um"):
        M._geotiff(zipado({nome: tiff() for nome in nomes}))


def test_tiff_sem_crs_e_tiff_corrompido_recusados():
    with pytest.raises(RuntimeError, match="georreferência"):
        M._geotiff(tiff(crs=None))
    with pytest.raises(RuntimeError, match="inválido"):
        M._geotiff(b"II\x2a\x00" + b"0" * 20)


def test_404_remove_apenas_id_obsoleto_sem_recriar_na_mesma_rodada(mundo):
    fp = pedido(mundo, "cobertura")
    mundo.respostas.append(("GET", "/maps/exports/aceito", resposta(404)))
    with pytest.raises(RuntimeError, match="não existe mais"):
        M.exporta_uf("RN", temas=("cobertura",))
    assert json.loads(fp.read_text()) == {} and len(mundo.chamadas) == 1


@pytest.mark.parametrize(
    "corpo",
    [
        {"message": "Invalid quota field"},
        {"message": "Too many years supplied; only one allowed"},
        {"details": {"quota": "must be integer"}},
        {"message": "Invalid export limit field"},
    ],
)
def test_classificacao_nao_confunde_validacao_com_quota(corpo):
    assert not M._quota_exportacao(resposta(422, corpo))


def test_tiff_truncado_no_ultimo_tile_nao_apaga_pedido(mundo):
    with MemoryFile() as m:
        with m.open(
            driver="GTiff",
            width=512,
            height=512,
            count=1,
            dtype="uint8",
            tiled=True,
            blockxsize=16,
            blockysize=16,
            transform=from_origin(-40, -4, 0.01, 0.01),
            crs="EPSG:4326",
        ) as src:
            src.write(np.ones((1, 512, 512), dtype="uint8"))
        quebrado = m.read()[:-128]
    # Cabeçalho e primeiro tile continuam legíveis: regressão precisa validar também o último tile.
    with MemoryFile(quebrado) as m, m.open() as src:
        assert src.read(1, window=((0, 1), (0, 1)))[0, 0] == 1
    fp = pedido(mundo, "cobertura")
    pronto(mundo, dados=quebrado)
    with pytest.raises(RuntimeError, match="inválido ou incompleto"):
        M.exporta_uf("RN", temas=("cobertura",))
    assert json.loads(fp.read_text())["cobertura"]["id"] == "aceito"
    assert not list((mundo.pasta / "RN").glob("*.tif*"))


def test_estado_transitorio_nao_documentado_aguarda_sem_repost(mundo, capsys):
    fp = pedido(mundo, "cobertura")
    mundo.respostas.append(("GET", "/maps/exports/aceito", resposta(objeto={"status": "ESTADO-NAO-DOCUMENTADO"})))
    pronto(mundo)
    M.exporta_uf("RN", temas=("cobertura",))
    assert mundo.relogio["esperas"] == [30]
    assert all(c[0] == "GET" for c in mundo.chamadas)
    assert json.loads(fp.read_text()) == {}
    saida = capsys.readouterr().out
    assert "pedido ainda não pronto" in saida
    assert "ESTADO-NAO-DOCUMENTADO" not in saida
