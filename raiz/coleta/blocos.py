"""Índice de blocos de rasters na nuvem (COG/GeoTIFF em blocos) e leitura só dos blocos do município (E1 passos 3 e 4).

- Índice: lê uma vez só o cabeçalho de cada arquivo (tifffile sobre um arquivo remoto que pede intervalos de bytes)
  e guarda em Parquet a tabela de blocos: nível (0 = resolução cheia, 1.. = visões reduzidas), linha, coluna,
  offset, bytes e o retângulo do bloco. Com ela, os bytes de um município saem sem baixar nada (lógica do fetch_size).
- Leitura: GDAL /vsicurl/ com pedidos de intervalo agrupados (GDAL_HTTP_MULTIRANGE) e cache em memória, lendo só a
  janela do município.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pandas as pd
import requests
import tifffile

GDAL_REMOTO = dict(
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_LIST",
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff",
    GDAL_HTTP_MULTIRANGE="YES",
    GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
    VSI_CACHE="TRUE",
    GDAL_HTTP_MAX_RETRY="4",
    GDAL_HTTP_RETRY_DELAY="5",
)


class CacheDisco:
    """Pedaços de arquivos remotos guardados em disco entre rodadas (chave = endereço + ETag: se o arquivo mudar na
    nuvem, a chave muda e o cache velho sai pela poda). Teto em GB; a poda apaga os pedaços usados há mais tempo."""

    def __init__(self, pasta: str | Path, limite_gb: float = 20.0):
        self.pasta = Path(pasta)
        self.limite = int(limite_gb * 2**30)
        self.pasta.mkdir(parents=True, exist_ok=True)
        self._gravados = 0

    @staticmethod
    def chave(url: str, etag: str | None, tamanho: int) -> str:
        import hashlib

        return hashlib.sha256(f"{url}|{etag or ''}|{tamanho}".encode()).hexdigest()[:24]

    def ler(self, chave: str, i: int) -> bytes | None:
        f = self.pasta / chave / f"{i}.bin"
        if not f.exists():
            return None
        os.utime(f)  # marca uso recente para a poda
        return f.read_bytes()

    def gravar(self, chave: str, i: int, dados: bytes) -> None:
        d = self.pasta / chave
        d.mkdir(exist_ok=True)
        tmp = d / f"{i}.{os.getpid()}.tmp"
        tmp.write_bytes(dados)
        os.replace(tmp, d / f"{i}.bin")
        self._gravados += len(dados)
        if self._gravados > self.limite // 20:  # poda de vez em quando, não a cada pedaço
            self.podar()
            self._gravados = 0

    def podar(self) -> None:
        arqs = [(f.stat().st_mtime, f.stat().st_size, f) for f in self.pasta.glob("*/*.bin")]
        total = sum(t for _, t, _ in arqs)
        for _, tam, f in sorted(arqs):
            if total <= self.limite:
                break
            f.unlink(missing_ok=True)
            total -= tam


class ArquivoRemoto(io.RawIOBase):
    """Arquivo de leitura sobre HTTP com Range, em pedaços de `bloco` bytes guardados em memória e, com `cache`,
    também em disco (próxima rodada não baixa de novo)."""

    def __init__(
        self, url: str, s: requests.Session | None = None, bloco: int = 1 << 16, cache: CacheDisco | None = None
    ):
        self.url, self.s, self.bloco = url, s or requests.Session(), bloco
        self.pos, self._cache = 0, {}
        r = self.s.head(url, allow_redirects=True, timeout=30)
        r.raise_for_status()
        self.tamanho = int(r.headers["Content-Length"])
        self.disco = cache
        self.chave = CacheDisco.chave(url, r.headers.get("ETag"), self.tamanho) if cache else None
        self.pedidos = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def seek(self, pos, whence=io.SEEK_SET):
        self.pos = {io.SEEK_SET: pos, io.SEEK_CUR: self.pos + pos, io.SEEK_END: self.tamanho + pos}[whence]
        return self.pos

    def tell(self):
        return self.pos

    def _pedaco(self, i: int) -> bytes:
        if i not in self._cache and self.disco is not None:
            guardado = self.disco.ler(self.chave, i)
            if guardado is not None:
                self._cache[i] = guardado
        if i not in self._cache:
            ini = i * self.bloco
            fim = min(ini + self.bloco, self.tamanho) - 1
            r = self.s.get(self.url, headers={"Range": f"bytes={ini}-{fim}"}, timeout=60)
            if r.status_code != 206:
                raise OSError(f"servidor não aceitou Range ({r.status_code})")
            self._cache[i] = r.content
            self.pedidos += 1
            if self.disco is not None:
                self.disco.gravar(self.chave, i, r.content)
        return self._cache[i]

    def readinto(self, b) -> int:
        n = min(len(b), max(0, self.tamanho - self.pos))
        lido = 0
        while lido < n:
            i, desl = divmod(self.pos + lido, self.bloco)
            pedaco = self._pedaco(i)[desl : desl + n - lido]
            b[lido : lido + len(pedaco)] = pedaco
            lido += len(pedaco)
        self.pos += n
        return n


def indice(origem: str | Path | io.IOBase, nome: str | None = None) -> pd.DataFrame:
    """Tabela de blocos de todos os níveis do arquivo (local, ou ArquivoRemoto para um endereço na nuvem)."""
    linhas = []
    with tifffile.TiffFile(origem) as tf:
        p0 = tf.pages[0]
        escala = p0.tags["ModelPixelScaleTag"].value
        ponto = p0.tags["ModelTiepointTag"].value
        x0 = ponto[3] - ponto[0] * escala[0]
        y0 = ponto[4] + ponto[1] * escala[1]
        largura0 = p0.imagewidth
        for nivel, pg in enumerate(tf.pages):
            if not pg.is_tiled:
                continue
            fator = largura0 / pg.imagewidth
            px, py = escala[0] * fator, escala[1] * fator
            tw, tl = pg.tilewidth, pg.tilelength
            colunas = -(-pg.imagewidth // tw)
            for k, (off, n) in enumerate(zip(pg.dataoffsets, pg.databytecounts, strict=True)):
                if pg.samplesperpixel > 1 and pg.planarconfig == 2:
                    k = k % (len(pg.dataoffsets) // pg.samplesperpixel)
                lin, col = divmod(k, colunas)
                linhas.append(
                    (
                        nivel,
                        lin,
                        col,
                        int(off),
                        int(n),
                        x0 + col * tw * px,
                        y0 - (lin + 1) * tl * py,
                        x0 + (col + 1) * tw * px,
                        y0 - lin * tl * py,
                    )
                )
    df = pd.DataFrame(linhas, columns=["nivel", "linha", "coluna", "offset", "bytes", "x0", "y0", "x1", "y1"])
    if nome:
        df.insert(0, "arquivo", nome)
    return df


def bytes_no_retangulo(ind: pd.DataFrame, bbox: tuple[float, float, float, float], nivel: int = 0) -> int:
    x0, y0, x1, y1 = bbox
    t = ind[(ind.nivel == nivel) & (ind.x1 > x0) & (ind.x0 < x1) & (ind.y1 > y0) & (ind.y0 < y1)]
    return int(t.bytes.sum())


def ler_janela(endereco: str, bbox: tuple[float, float, float, float], banda: int = 1):
    """Só a janela do retângulo (endereço http(s) vira /vsicurl/). Devolve (matriz, transform, crs)."""
    import rasterio
    from rasterio.windows import from_bounds

    caminho = f"/vsicurl/{endereco}" if str(endereco).startswith("http") else str(endereco)
    with rasterio.Env(**GDAL_REMOTO), rasterio.open(caminho) as src:
        w = from_bounds(*bbox, transform=src.transform).round_offsets().round_lengths()
        return src.read(banda, window=w), src.window_transform(w), src.crs


def salvar_indice(ind: pd.DataFrame, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(f".{os.getpid()}.tmp")
    ind.to_parquet(tmp, index=False)
    os.replace(tmp, destino)


SIDECARS = (".aux.xml", ".ovr", ".msk", ".tfw", ".xml", ".imd", ".rpb", ".rpc")


def abrir_com_cache(url: str, cache: CacheDisco, s: requests.Session | None = None, bloco: int = 1 << 20):
    """Abre o raster remoto no rasterio lendo pelos pedaços em disco (opener). Arquivos auxiliares que o GDAL procura
    ao lado (.aux.xml, .ovr...) respondem 'não existe' sem ir à rede."""
    import rasterio

    s = s or requests.Session()

    class _Abridor:
        def open(self, caminho, mode="rb", **_):
            if str(caminho) != url:
                raise FileNotFoundError(caminho)
            return ArquivoRemoto(url, s, bloco, cache)

        def isfile(self, caminho):
            return str(caminho) == url

        def isdir(self, caminho):
            return False

        def ls(self, caminho):
            return []

        def mtime(self, caminho):
            return 0

        def size(self, caminho):
            return ArquivoRemoto(url, s, bloco, cache).tamanho if str(caminho) == url else 0

    return rasterio.open(url, opener=_Abridor())
