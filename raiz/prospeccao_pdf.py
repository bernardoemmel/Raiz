"""PDF privado da ficha fechada, sem consulta externa nem textos livres do motor."""

from __future__ import annotations

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from raiz.prospeccao_contrato import ESQUEMA, MUDANCAS, filtrar_mudancas, projetar_ficha
from raiz.prospeccao_protecao import SENTINELA, MarcaExportacao, validar_marca

ROTULOS = {
    "versao": "Versão da ficha",
    "codigo_car": "Código do CAR",
    "cod_ibge": "Código IBGE",
    "uf": "Estado",
    "data_corte": "Data de corte da carga",
    "data_referencia": "Data de referência da fonte",
    "area_total": "Área total",
    "area_restauravel": "Área que pode voltar a ser mata",
    "caminho_terra": "Caminho da terra",
    "pendencias": "Pendências",
    "sobreposicoes": "Sobreposições",
    "serie_uso": "Uso ao longo dos anos",
    "credito": "Crédito líquido estimado",
    "tir": "TIR",
    "versao_modelo": "Versão do modelo",
    "regra_versao": "Versão da regra",
    "metodo": "Método",
    "imoveis": "Fazendas no agrupamento",
    "rotulo": "Descrição",
    "situacao": "Situação",
    "municipio": "Município",
    "agua": "Água",
    "p10": "P10",
    "p50": "P50",
    "p90": "P90",
}


def _valor(valor) -> str:
    if valor is None or isinstance(valor, (dict, list, tuple)):
        return "não disponível"
    if isinstance(valor, bool):
        return "sim" if valor else "não"
    return str(valor)


def linhas(ficha: dict) -> list[tuple[int, str, str | None]]:
    """Cada medida preserva valor, unidade, fonte, referência, corte e estimativa."""
    saida = []

    def fechado(valor, nivel):
        if isinstance(valor, dict):
            for chave, item in valor.items():
                rotulo = ROTULOS.get(chave, chave.replace("_", " ").capitalize())
                if isinstance(item, (dict, list)):
                    saida.append((nivel, rotulo, None))
                    fechado(item, nivel + 1)
                else:
                    saida.append((nivel, rotulo, _valor(item)))
        elif isinstance(valor, list):
            for indice, item in enumerate(valor, 1):
                saida.append((nivel, f"Registro {indice}", None))
                fechado(item, nivel + 1)
        else:
            saida.append((nivel, "Valor", _valor(valor)))

    def percorrer(dado, esquema, nivel=0):
        for chave, formato in esquema.items():
            rotulo = ROTULOS.get(chave, chave.replace("_", " ").capitalize())
            valor = dado.get(chave) if isinstance(dado, dict) else None
            if formato is MUDANCAS:
                saida.append((nivel, rotulo, None))
                fechado(filtrar_mudancas(valor), nivel + 1)
            elif isinstance(formato, dict):
                saida.append((nivel, rotulo, None))
                percorrer(valor, formato, nivel + 1)
            elif isinstance(formato, list):
                saida.append((nivel, rotulo, None))
                if isinstance(valor, list) and valor:
                    for n, item in enumerate(valor, 1):
                        saida.append((nivel + 1, f"Registro {n}", None))
                        percorrer(item, formato[0], nivel + 2)
                else:
                    saida.append((nivel + 1, "Registros", "não disponíveis"))
            else:
                saida.append((nivel, rotulo, _valor(valor)))

    percorrer(ficha, ESQUEMA)
    return saida


filtrar_ficha = projetar_ficha


def gerar_pdf(ficha: dict, *, marca: MarcaExportacao | None = None) -> bytes:
    validar_marca(marca)
    destino = io.BytesIO()
    estilos = getSampleStyleSheet()
    corpo = ParagraphStyle(
        "Ficha",
        parent=estilos["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        alignment=TA_LEFT,
        splitLongWords=True,
        spaceAfter=3,
    )
    documento = SimpleDocTemplate(
        destino,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="Raíz: ficha da fazenda",
        author="Raíz",
    )
    elementos = [
        Paragraph("Raíz: ficha da fazenda", estilos["Title"]),
        Paragraph(
            "Dados da terra. Valores ausentes não são zero. A data de corte da carga não substitui a data "
            "de referência da fonte. Crédito e TIR são estimativas, sem garantia de emissão ou retorno.",
            corpo,
        ),
        Spacer(1, 4 * mm),
        Paragraph(f"<b>{escape(SENTINELA)}</b><br/>{escape(marca.codigo)}", corpo),
        Spacer(1, 4 * mm),
    ]
    for nivel, rotulo, valor in linhas(ficha):
        if valor is None:
            estilo = estilos["Heading2"] if nivel == 0 else estilos["Heading3"]
            elementos.append(Paragraph(escape(rotulo), estilo))
        else:
            elementos.append(Paragraph(f"<b>{escape(rotulo)}:</b> {escape(valor)}", corpo))

    def pagina(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.Color(0.85, 0.85, 0.85))
        canvas.setFont("Helvetica", 13)
        canvas.translate(A4[0] / 2, A4[1] / 2)
        canvas.rotate(35)
        canvas.drawCentredString(0, 0, marca.codigo)
        canvas.restoreState()
        canvas.saveState()
        canvas.setFillColor(colors.black)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(18 * mm, 14 * mm, marca.codigo)
        canvas.drawString(18 * mm, 10 * mm, f"Raíz | Ficha privada | Página {doc.page}")
        canvas.restoreState()

    documento.build(elementos, onFirstPage=pagina, onLaterPages=pagina)
    return destino.getvalue()
