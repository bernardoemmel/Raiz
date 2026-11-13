"""OCR de uma página de teste desenhada em memória; não cria corpus de certidões."""

import io
import subprocess

import pytest
from PIL import Image, ImageDraw, ImageFont

from raiz.calendario import ocr_pdf


def test_ocr_real_sem_arquivos_temporarios(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    figura = Image.new("RGB", (1800, 600), "white")
    desenho = ImageDraw.Draw(figura)
    fonte = ImageFont.load_default(size=38)
    desenho.text((70, 70), "PAGINA ARTIFICIAL SOMENTE PARA TESTE\nMATRICULA: 98765", font=fonte, fill="black")
    buf = io.BytesIO()
    figura.save(buf, format="PDF", resolution=150)
    texto = ocr_pdf.extrair(buf.getvalue(), [1])[1]
    assert "98765" in texto and "TESTE" in texto
    assert list(tmp_path.iterdir()) == []


def test_ocr_recusa_limites_ausencia_e_tempo_sem_vazar_entrada(monkeypatch):
    with pytest.raises(ocr_pdf.FalhaOCR, match="12 páginas"):
        ocr_pdf.extrair(b"nao-deve-aparecer", list(range(1, 14)))
    monkeypatch.setattr(ocr_pdf.shutil, "which", lambda *_: None)
    with pytest.raises(ocr_pdf.FalhaOCR, match="Poppler e Tesseract"):
        ocr_pdf.extrair(b"nao-deve-aparecer", [1])

    def falhar(*args, **kwargs):
        raise subprocess.TimeoutExpired(args, 1, output=b"nao-deve-aparecer")

    monkeypatch.setattr(ocr_pdf.subprocess, "run", falhar)
    with pytest.raises(ocr_pdf.FalhaOCR) as erro:
        ocr_pdf._executar(["tesseract"], b"nao-deve-aparecer", 1, 200)
    assert "nao-deve-aparecer" not in str(erro.value)
