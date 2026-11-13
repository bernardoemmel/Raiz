"""OCR opt-in de PDFs públicos: processos limitados, dados só em stdin/stdout e RAM.

Poppler é executado como ferramenta do servidor; não integra o produto distribuído.
O resultado é texto ainda não conferido, nunca gabarito ou confiança calibrada.
"""

from __future__ import annotations

import shutil
import subprocess
import time

from raiz.calendario.processo_limitado import executar


class FalhaOCR(Exception):
    pass


def _executar(args: list[str], entrada: bytes | None, timeout: float, limite: int) -> bytes:
    try:
        return executar(args, entrada, timeout, limite)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise FalhaOCR("OCR indisponível ou acima do tempo permitido") from None


def extrair(conteudo: bytes, paginas: list[int]) -> dict[int, str]:
    """Recebe números de página base 1. Não corrige caracteres de CAR/matrícula."""
    if not paginas:
        return {}
    if len(paginas) > 12 or any(p < 1 or p > 250 for p in paginas):
        raise FalhaOCR("PDF escaneado excede o limite de 12 páginas de OCR")
    poppler, tesseract = shutil.which("pdftoppm"), shutil.which("tesseract")
    if not poppler or not tesseract:
        raise FalhaOCR("OCR requer Poppler e Tesseract no servidor")
    disponiveis = _executar([tesseract, "--list-langs"], None, 5, 20000).decode(errors="replace").splitlines()
    idiomas = "+".join(i for i in ("por", "eng") if i in disponiveis)
    if not idiomas:
        raise FalhaOCR("OCR requer o idioma português ou inglês no servidor")
    inicio, resultado = time.monotonic(), {}
    for pagina in paginas:
        restante = 180 - (time.monotonic() - inicio)
        if restante <= 0:
            raise FalhaOCR("OCR excedeu o tempo total do documento")
        imagem = _executar(
            [
                poppler,
                "-f",
                str(pagina),
                "-l",
                str(pagina),
                "-r",
                "150",
                "-scale-to",
                "2500",
                "-singlefile",
                "-png",
                "-",
            ],
            conteudo,
            min(30, restante),
            32 * 1024 * 1024,
        )
        restante = 180 - (time.monotonic() - inicio)
        if restante <= 0:
            raise FalhaOCR("OCR excedeu o tempo total do documento")
        texto = _executar(
            [tesseract, "stdin", "stdout", "-l", idiomas, "--psm", "3"],
            imagem,
            min(30, restante),
            2 * 1024 * 1024,
        )
        resultado[pagina] = texto.decode("utf-8", errors="replace")
    return resultado
