"""Nomes de membros remotos não aparecem em erros públicos de exportação."""

import importlib.util
import io
import json
import struct
import traceback
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

MARCADOR = "marcador-privado-exemplo"


@pytest.fixture
def mapa(monkeypatch, tmp_path):
    motor = Path(__file__).resolve().parents[1] / "motor"
    monkeypatch.syspath_prepend(str(motor))
    spec = importlib.util.spec_from_file_location("mapbiomas_privacidade", motor / "raiz_mapbiomas.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    monkeypatch.setattr(modulo, "CACHE", str(tmp_path))
    monkeypatch.setattr(modulo, "_pedido", lambda *a, **kw: pytest.fail("pedido novo não autorizado no teste"))
    monkeypatch.delenv("RAIZ_PRAZO", raising=False)
    return modulo


def _geotiff():
    with MemoryFile() as memoria:
        with memoria.open(
            driver="GTiff",
            height=2,
            width=2,
            count=1,
            dtype="uint8",
            crs="EPSG:4326",
            transform=from_origin(-50, -5, 0.01, 0.01),
        ) as raster:
            raster.write(np.ones((1, 2, 2), dtype="uint8"))
        return memoria.read()


def _zip(dados, defeito=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as pacote:
        pacote.writestr(f"{MARCADOR}.tif", dados)
    bruto = bytearray(buffer.getvalue())
    if defeito == "crc":
        tamanho_nome, tamanho_extra = struct.unpack_from("<HH", bruto, 26)
        bruto[30 + tamanho_nome + tamanho_extra] ^= 1
    elif defeito == "truncado":
        del bruto[-22:]
    return bytes(bruto)


def _pedido_aceito(mapa, tmp_path, monkeypatch, conteudo):
    pasta = tmp_path / "PA"
    pasta.mkdir()
    chave, ano = mapa.TEMAS["cobertura"]
    pedidos = {"cobertura": {"id": "exportacao-teste", "chave": chave, "ano": ano, "em": mapa.time.time()}}
    caminho = pasta / "pedidos.json"
    caminho.write_text(json.dumps(pedidos))
    chamadas = []

    def resposta(url, **kwargs):
        chamadas.append(url)
        assert url in {
            f"{mapa.API}/maps/exports/exportacao-teste",
            f"{mapa.API}/maps/exports/exportacao-teste/download",
        }
        return SimpleNamespace(status_code=200, ok=True, content=conteudo, json=lambda: {"status": "READY"})

    monkeypatch.setattr(mapa, "_get", resposta)
    return pasta, caminho, chamadas


@pytest.mark.parametrize("defeito", ["crc", "truncado"])
def test_zip_invalido_nao_expoe_nome_nem_perde_pedido(mapa, tmp_path, monkeypatch, capsys, defeito):
    conteudo = _zip(_geotiff(), defeito)
    pasta, pedidos, chamadas = _pedido_aceito(mapa, tmp_path, monkeypatch, conteudo)
    antes = pedidos.read_bytes()

    with pytest.raises(RuntimeError, match="^MapBiomas: ZIP inválido ou incompleto$") as falha:
        mapa.exporta_uf("PA", temas=("cobertura",))

    assert falha.value.__suppress_context__
    assert MARCADOR not in "".join(traceback.format_exception(falha.value))
    assert MARCADOR not in capsys.readouterr().out
    assert pedidos.read_bytes() == antes
    assert sorted(p.name for p in pasta.iterdir()) == ["pedidos.json"]
    assert len(chamadas) == 2


def test_zip_valido_preserva_bytes_e_conclui_pedido(mapa, tmp_path, monkeypatch):
    dados = _geotiff()
    pasta, pedidos, chamadas = _pedido_aceito(mapa, tmp_path, monkeypatch, _zip(dados))

    saidas = mapa.exporta_uf("PA", temas=("cobertura",))

    assert Path(saidas["cobertura"]).read_bytes() == dados
    assert json.loads(pedidos.read_text()) == {}
    assert not list(pasta.glob("*.tmp"))
    assert len(chamadas) == 2
