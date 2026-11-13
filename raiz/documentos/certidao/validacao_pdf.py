"""Validação de PDF privado em processo limitado; saída apenas com campos fechados."""

import io
import json
import sys

from pypdf import PdfReader


class ErroEntrada(ValueError):
    def __init__(self, status, codigo):
        super().__init__(codigo)


MAX_BYTES = 20 * 1024 * 1024
MAX_PAGINAS = 100


def validar_pdf(pdf: bytes) -> int:
    if len(pdf) > MAX_BYTES:
        raise ErroEntrada(413, "pdf_acima_de_20_mb")
    if not pdf.startswith(b"%PDF-"):
        raise ErroEntrada(422, "arquivo_nao_e_pdf")
    try:
        p = PdfReader(io.BytesIO(pdf), strict=True)
        if p.is_encrypted:
            raise ErroEntrada(422, "pdf_protegido_por_senha")
        paginas = len(p.pages)
        if not 1 <= paginas <= MAX_PAGINAS:
            raise ErroEntrada(422, "pdf_deve_ter_1_a_100_paginas")
        raiz = p.trailer["/Root"]
        if any(k in raiz for k in ("/OpenAction", "/AA")) or any(
            k in raiz.get("/Names", {}) for k in ("/JavaScript", "/EmbeddedFiles")
        ):
            raise ErroEntrada(422, "pdf_com_conteudo_ativo")
        for pagina in p.pages:
            if "/AA" in pagina:
                raise ErroEntrada(422, "pdf_com_conteudo_ativo")
            for anotacao in pagina.get("/Annots", []):
                a = anotacao.get_object()
                if "/AA" in a or "/A" in a or a.get("/Subtype") == "/FileAttachment":
                    raise ErroEntrada(422, "pdf_com_conteudo_ativo")
        return paginas
    except ErroEntrada:
        raise
    except Exception as exc:  # o parser pode incluir trechos do PDF na mensagem
        raise ErroEntrada(422, "pdf_invalido") from exc


if __name__ == "__main__":
    try:
        paginas = validar_pdf(sys.stdin.buffer.read(MAX_BYTES + 1))
        print(json.dumps({"paginas": paginas}))
    except ErroEntrada as exc:
        print(json.dumps({"erro": str(exc)}))
    except Exception:  # noqa: BLE001 - nenhuma mensagem do documento sai do worker
        print(json.dumps({"erro": "pdf_invalido"}))
