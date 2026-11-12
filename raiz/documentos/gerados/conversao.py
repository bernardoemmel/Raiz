"""Renderização dos modelos docxtpl e conversão para PDF (LibreOffice no servidor, se instalado)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from docxtpl import DocxTemplate

from raiz.documentos.config import pasta_dados

MODELOS = Path(__file__).with_name("modelos")


def renderizar(modelo: str, contexto: dict, saida: Path) -> Path:
    tpl = DocxTemplate(MODELOS / modelo)
    tpl.render(contexto, autoescape=True)
    saida.parent.mkdir(parents=True, exist_ok=True)
    tpl.save(saida)
    return saida


def pasta_gerados() -> Path:
    p = pasta_dados() / "gerados"
    p.mkdir(parents=True, exist_ok=True)
    return p


def libreoffice() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def para_pdf(docx: Path, pasta: Path | None = None, timeout: int = 180) -> Path:
    """Converte com o LibreOffice (MPL-2.0, roda como programa à parte). Levanta RuntimeError se não houver."""
    exe = libreoffice()
    if not exe:
        raise RuntimeError("LibreOffice não instalado: o .docx foi gerado, mas não o PDF")
    pasta = pasta or docx.parent
    with tempfile.TemporaryDirectory() as perfil:  # perfil próprio: não briga com outro LibreOffice aberto
        subprocess.run(
            [
                exe,
                f"-env:UserInstallation=file://{perfil}",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(pasta),
                str(docx),
            ],
            check=True,
            capture_output=True,
            timeout=timeout,
        )
    pdf = pasta / (docx.stem + ".pdf")
    if not pdf.exists():
        raise RuntimeError("o LibreOffice não gerou o PDF")
    return pdf


def paginas(pdf: Path) -> int:
    from pypdf import PdfReader

    return len(PdfReader(str(pdf)).pages)
