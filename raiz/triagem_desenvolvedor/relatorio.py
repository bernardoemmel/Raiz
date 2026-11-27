"""Ranking em CSV e em PDF (reportlab). O PDF mostra, por fazenda, a posição, a nota, a faixa, os números principais e o
motivo da nota; no fim, a regra e as premissas provisórias. Todo texto passa pela máscara de CPF e CNPJ."""

from __future__ import annotations

import csv
import io
from xml.sax.saxutils import escape

from raiz.agentes.textos import num
from raiz.protecao.privacidade import mascarar
from raiz.triagem_desenvolvedor import COLUNAS, resumo
from raiz.triagem_desenvolvedor import nota as N

NOMES_FAIXA = {
    "recomendada": "recomendada",
    "com_ressalvas": "com ressalvas",
    "nao_segue": "não segue (trava)",
    "sem_dados": "sem dados do valor",
    "nao_encontrada": "não encontrada",
}


def csv_bytes(linhas: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUNAS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for x in linhas:
        w.writerow({k: ("" if x.get(k) is None else mascarar(str(x[k]))) for k in COLUNAS})
    return buf.getvalue().encode("utf-8")


def _n(v, casas=1) -> str:
    return "–" if v is None else num(v, casas)


def como_a_nota_sai(r: dict) -> str:
    f, w, tr = r["faixas"], r["pesos"], r["travas"]
    c, t, k = f["custo_credito_usd"], f["tir_pct"], f["credito_tco2_ha"]
    return (
        f"Como a nota sai: custo por crédito {int(w['custo'] * 100)}% (de US$ {num(c['melhor'], 0)} a "
        f"US$ {num(c['pior'], 0)}), TIR {int(w['tir'] * 100)}% (de {num(t['pior'], 0)}% a {num(t['melhor'], 0)}%), "
        f"crédito líquido P50 por ha {int(w['credito'] * 100)}% (de {num(k['pior'], 0)} a "
        f"{num(k['melhor'], 0)} t/ha) e "
        f"terra {int(w['terra'] * 100)}% (risco baixo, médio ou alto). Embargo, terra indígena, UC de proteção "
        f"integral, desmatamento ou alerta recente, projeto já existente e caminho que não origina travam a nota em "
        f"{tr['nota_max']}; a fazenda continua na lista, com o motivo. Fazenda pequena nunca é descartada. "
        "Sem nome, CPF ou contato do dono."
    )


def pdf_bytes(linhas: list[dict], titulo: str = "Triagem de fazendas para restauração") -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    estilos = getSampleStyleSheet()
    p = ParagraphStyle("p", parent=estilos["BodyText"], fontSize=7, leading=8.5)
    ph = ParagraphStyle("ph", parent=p, fontName="Helvetica-Bold", textColor=colors.white)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=10 * mm, rightMargin=10 * mm, topMargin=12 * mm,
                            bottomMargin=12 * mm, title=titulo)  # fmt: skip
    r = N.regra()
    res = resumo(linhas)
    versao = linhas[0]["regra_versao"] if linhas else r["versao_completa"]
    corpo = [
        Paragraph(escape(titulo), estilos["Title"]),
        Paragraph(
            escape(
                f"{res['total']} fazendas: {res['recomendada']} recomendadas, {res['com_ressalvas']} com ressalvas, "
                f"{res['nao_segue']} travadas, {res['sem_dados']} sem dados do valor e {res['nao_encontrada']} não "
                f"encontradas. Regra {versao}. Nota de 0 a 100 (premissas provisórias, a calibrar)."
            ),
            p,
        ),
        Spacer(1, 4 * mm),
    ]
    cab = ["#", "Fazenda (CAR)", "Nota", "Faixa", "ha", "Crédito P50 t/ha", "US$/crédito", "TIR %", "Terra", "Motivo"]
    dados = [[Paragraph(c, ph) for c in cab]]
    for x in linhas:
        terra = " / ".join(t for t in (x.get("caminho_terra"), x.get("risco_terra")) if t) or "–"
        dados.append([
            Paragraph(str(x["posicao"]), p),
            Paragraph(escape(mascarar(x["cod_imovel"])), p),
            Paragraph(_n(x.get("nota")), p),
            Paragraph(NOMES_FAIXA[x["faixa"]], p),
            Paragraph(_n(x.get("ha"), 1), p),
            Paragraph(_n(x.get("credito_p50_tco2_ha"), 0), p),
            Paragraph(_n(x.get("custo_credito_usd"), 2), p),
            Paragraph(_n(x.get("tir_pct"), 1), p),
            Paragraph(escape(terra.replace("_", " ")), p),
            Paragraph(escape(mascarar(x.get("motivo") or "")), p),
        ])  # fmt: skip
    t = Table(dados, repeatRows=1, colWidths=[8 * mm, 52 * mm, 11 * mm, 22 * mm, 13 * mm, 16 * mm, 15 * mm, 11 * mm,
                                              30 * mm, 99 * mm])  # fmt: skip
    verde, claro, borda = colors.HexColor("#1D6B44"), colors.HexColor("#F1F5F2"), colors.HexColor("#C9D3CC")
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), verde),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, claro]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.2, borda),
            ]
        )
    )
    corpo += [t, Spacer(1, 4 * mm)]
    corpo.append(Paragraph(escape(como_a_nota_sai(r)), p))
    doc.build(corpo)
    return buf.getvalue()


def gravar(linhas: list[dict], pasta, nome: str = "triagem") -> dict:
    from pathlib import Path

    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / f"{nome}.csv").write_bytes(csv_bytes(linhas))
    (pasta / f"{nome}.pdf").write_bytes(pdf_bytes(linhas))
    return {"csv": pasta / f"{nome}.csv", "pdf": pasta / f"{nome}.pdf"}
