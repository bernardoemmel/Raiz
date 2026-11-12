"""Leitura integral de contêineres públicos, sem campos livres ou bytes ignorados."""

from __future__ import annotations

import io
import tarfile
import tempfile
import zlib
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def abrir_tar_seguro(origem: bytes | Path):
    """Confere TAR/gzip inteiro sem outra cópia integral descompactada em memória.

    Arquivos são lidos em blocos; a descompressão limitada vai para um temporário
    apagado ao sair. O chamador ainda valida os nomes e o conteúdo de cada membro.
    """
    bloco = 64 * 1024
    with (
        io.BytesIO(origem) if isinstance(origem, bytes) else origem.open("rb") as comprimido,
        tempfile.TemporaryFile() as bruto,
    ):
        gzip = zlib.decompressobj(16 + zlib.MAX_WBITS)
        primeiro = True
        while entrada := comprimido.read(bloco):
            if primeiro:
                if len(entrada) < 10 or entrada[:2] != b"\x1f\x8b" or entrada[3] & 0x1C:
                    raise ValueError("cabeçalho gzip fora do contrato")
                primeiro = False
            while entrada:
                bruto.write(gzip.decompress(entrada, bloco))
                if gzip.eof:
                    if gzip.unused_data or comprimido.read(1):
                        raise ValueError("conteúdo adicional depois do gzip")
                    break
                entrada = gzip.unconsumed_tail
            if gzip.eof:
                break
        if not gzip.eof:
            raise ValueError("gzip incompleto")
        tamanho = bruto.tell()
        bruto.seek(0)
        with tarfile.open(fileobj=bruto, mode="r:") as tar:
            yield tar
            if tar.pax_headers:
                raise ValueError("metadados TAR adicionais")
            fim = 0
            for membro in tar.getmembers():
                # Os produtores usam USTAR simples. Reconstituir o cabeçalho
                # detecta também texto ignorado depois de um byte NUL.
                if (
                    membro.offset_data != membro.offset + 512
                    or membro.linkname
                    or membro.uname
                    or membro.gname
                    or membro.pax_headers
                ):
                    raise ValueError("metadados TAR adicionais")
                bruto.seek(membro.offset)
                if bruto.read(512) != membro.tobuf(format=tarfile.USTAR_FORMAT):
                    raise ValueError("cabeçalho TAR fora do contrato")
                bruto.seek(membro.offset_data + membro.size)
                tamanho_padding = -membro.size % 512
                padding = bruto.read(tamanho_padding)
                if len(padding) != tamanho_padding or any(padding):
                    raise ValueError("padding TAR fora do contrato")
                fim = membro.offset_data + membro.size + tamanho_padding
            if tamanho - fim < 1024 or (tamanho - fim) % 512:
                raise ValueError("terminador TAR incompleto")
            bruto.seek(fim)
            while cauda := bruto.read(bloco):
                if any(cauda):
                    raise ValueError("conteúdo adicional depois do TAR")
