"""Mapa base do Brasil (design v1 do front, item 5): recorte do build diário do Protomaps até o zoom 14, servido pela
Raíz com resposta a Range, mais as fontes e os sprites do protomaps/basemaps-assets.

Rios e estradas vêm daqui (OpenStreetMap, ODbL; crédito "© colaboradores do OpenStreetMap"), não da Base
Cartográfica do IBGE, que veda uso comercial. O recorte usa o `pmtiles extract` do go-pmtiles (BSD-3), que junta
faixas contíguas: o Brasil até o zoom 14 sai em ~3 GB e ~100 pedidos.

`raiz mapa atualizar` faz o recorte do build mais recente, baixa fontes e sprites e grava manifesto.json; o recorte
anterior só é apagado depois que o novo terminou.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
from pathlib import Path

import httpx

from raiz import RAIZ_REPO
from raiz.config import config

BRASIL = (-74.1, -33.8, -34.7, 5.3)
ZOOM_MAX = 14
ASSETS = "https://protomaps.github.io/basemaps-assets"
FONTES = ("Noto Sans Regular", "Noto Sans Medium", "Noto Sans Italic")
# Latim básico, Latim-1, Latim estendido adicional e pontuação: bastam para os nomes de lugar do Brasil
FAIXAS = ("0-255", "256-511", "7680-7935", "8192-8447")
SPRITES = ("light", "dark", "white", "grayscale", "black")
ATRIBUICAO = '<a href="https://openstreetmap.org/copyright">© colaboradores do OpenStreetMap</a>, Protomaps'


def pasta() -> Path:
    return Path(getattr(config(), "mapa_dir", None) or RAIZ_REPO / "dados" / "mapa")


def manifesto(p: Path | None = None) -> dict | None:
    f = (p or pasta()) / "manifesto.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def arquivo_atual(p: Path | None = None) -> Path | None:
    m = manifesto(p)
    if not m:
        return None
    f = (p or pasta()) / m["arquivo"]
    return f if f.exists() else None


def _binario() -> str:
    for c in (shutil.which("go-pmtiles"), shutil.which("pmtiles"), str(Path.home() / "go" / "bin" / "go-pmtiles")):
        if c and Path(c).exists():
            return c
    raise FileNotFoundError(
        "go-pmtiles não encontrado: instale com `go install github.com/protomaps/go-pmtiles@latest` (BSD-3)"
    )


def extrair(dia: str, p: Path | None = None, caixa=BRASIL, zoom_max: int = ZOOM_MAX, fonte: str | None = None) -> Path:
    """Recorta o build `dia` (AAAAMMDD) do Protomaps para brasil_<dia>.pmtiles. Devolve o caminho."""
    p = p or pasta()
    p.mkdir(parents=True, exist_ok=True)
    destino = p / f"brasil_{dia}.pmtiles"
    if destino.exists():
        return destino
    tmp = destino.with_suffix(".pmtiles.tmp")
    origem = fonte or f"https://build.protomaps.com/{dia}.pmtiles"
    bbox = ",".join(str(x) for x in caixa)
    subprocess.run(
        [_binario(), "extract", origem, str(tmp), f"--bbox={bbox}", f"--maxzoom={zoom_max}", "--download-threads=4"],
        check=True,
        timeout=4 * 3600,
    )
    tmp.replace(destino)
    return destino


def baixar_assets(p: Path | None = None, cliente: httpx.Client | None = None) -> int:
    """Fontes (Noto Sans, OFL) e sprites do basemaps-assets, só o que falta. Devolve quantos arquivos baixou."""
    p = p or pasta()
    c = cliente or httpx.Client(timeout=60, follow_redirects=True)
    n = 0
    alvos = [(f"fonts/{f}/{fx}.pbf", p / "fontes" / f / f"{fx}.pbf") for f in FONTES for fx in FAIXAS]
    for s in SPRITES:
        for sufixo in ("", "@2x"):
            for ext in ("json", "png"):
                alvos.append((f"sprites/v4/{s}{sufixo}.{ext}", p / "sprites" / f"{s}{sufixo}.{ext}"))
    for url, destino in alvos:
        if destino.exists():
            continue
        r = c.get(f"{ASSETS}/{url.replace(' ', '%20')}")
        r.raise_for_status()
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(r.content)
        n += 1
    return n


def gravar_manifesto(arquivo: Path, dia: str, p: Path | None = None, zoom_max: int = ZOOM_MAX) -> dict:
    p = p or pasta()
    m = {
        "arquivo": arquivo.name,
        "build_protomaps": dia,
        "bytes": arquivo.stat().st_size,
        "zoom_max": zoom_max,
        "caixa": list(BRASIL),
        "fontes": list(FONTES),
        "sprites": list(SPRITES),
        "atribuicao": ATRIBUICAO,
        "gerado_em": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    }
    tmp = p / "manifesto.json.tmp"
    tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p / "manifesto.json")
    return m


def atualizar(dia: str | None = None, p: Path | None = None) -> dict:
    """Recorte novo, assets e manifesto; apaga os recortes antigos só no fim."""
    from raiz.osm import build_recente

    p = p or pasta()
    dia = dia or build_recente()
    f = extrair(dia, p)
    baixar_assets(p)
    m = gravar_manifesto(f, dia, p)
    for velho in p.glob("brasil_*.pmtiles"):
        if velho.name != f.name:
            velho.unlink()
    return m
