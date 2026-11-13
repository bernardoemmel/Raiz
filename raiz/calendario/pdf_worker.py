"""Extração PDF no processo limitado; nenhuma página ou exceção vai ao disco/log."""

import io
import json
import logging
import sys

from pypdf import PdfReader


def ler(conteudo: bytes) -> dict:
    logging.getLogger("pypdf").setLevel(logging.CRITICAL + 1)
    pdf = PdfReader(io.BytesIO(conteudo))
    if pdf.is_encrypted or len(pdf.pages) > 250:
        raise ValueError("PDF fora dos limites")
    paginas, escaneadas, tamanho, visual = [], [], 0, False
    for n, pagina in enumerate(pdf.pages, 1):
        texto = pagina.extract_text() or ""
        tamanho += len(texto.encode("utf-8"))
        if tamanho > 16 * 1024 * 1024:
            raise ValueError("texto PDF acima do limite")
        paginas.append(texto)
        # Consultar recursos evita decodificar cada imagem só para contá-la.
        recursos = pagina.get("/Resources", {})
        recursos = recursos.get_object() if hasattr(recursos, "get_object") else recursos
        visual = visual or not texto.strip() or bool(recursos.get("/XObject"))
        if len(texto.strip()) < 200 and recursos.get("/XObject"):
            escaneadas.append(n)
    return {"paginas": paginas, "escaneadas": escaneadas, "visual": visual}


if __name__ == "__main__":
    try:
        bruto = sys.stdin.buffer.read(64 * 1024 * 1024 + 1)
        if len(bruto) > 64 * 1024 * 1024:
            raise ValueError("PDF acima do limite")
        sys.stdout.write(json.dumps(ler(bruto), ensure_ascii=False))
    except Exception:  # noqa: BLE001 - saída fixa; PDF pode conter dados pessoais
        sys.exit(1)
