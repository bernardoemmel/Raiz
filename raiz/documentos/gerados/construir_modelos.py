"""Monta os modelos .docx (com campos Jinja do docxtpl) em gerados/modelos/. Rode de novo depois de mudar o texto:

    python -m raiz.documentos modelos

Os .docx gerados ficam no git (são pequenos) e também podem ser editados no Word, desde que os campos {{ ... }} e as
linhas {%tr ... %} e {%p ... %} continuem inteiros.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

PASTA = Path(__file__).with_name("modelos")
VERDE = RGBColor(0x1F, 0x5C, 0x3A)
CINZA = RGBColor(0x5F, 0x63, 0x68)
FONTE = "Arial"


def _documento(paisagem: bool = False) -> Document:
    d = Document()
    s = d.sections[0]
    if paisagem:
        from docx.enum.section import WD_ORIENT

        s.orientation = WD_ORIENT.LANDSCAPE
        s.page_width, s.page_height = s.page_height, s.page_width
    s.top_margin = s.bottom_margin = Cm(1.8)
    s.left_margin = s.right_margin = Cm(2.0)
    st = d.styles["Normal"]
    st.font.name = FONTE
    st.font.size = Pt(11)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), FONTE)
    st.paragraph_format.space_after = Pt(4)
    st.paragraph_format.line_spacing = 1.15
    return d


def _p(
    d,
    *partes,
    tam: float = 11,
    cor=None,
    depois: float = 4,
    antes: float = 0,
    centro: bool = False,
    italico: bool = False,
):
    """Parágrafo com partes (texto, negrito?). Cada campo Jinja fica inteiro num pedaço só."""
    p = d.add_paragraph()
    p.paragraph_format.space_after = Pt(depois)
    p.paragraph_format.space_before = Pt(antes)
    if centro:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for parte in partes:
        texto, negrito = (parte, False) if isinstance(parte, str) else parte
        r = p.add_run(texto)
        r.bold = negrito
        r.italic = italico
        r.font.size = Pt(tam)
        r.font.name = FONTE
        if cor is not None:
            r.font.color.rgb = cor
    return p


def _titulo(d, texto: str, tam: float = 20, antes: float = 0):
    return _p(d, (texto, True), tam=tam, cor=VERDE, depois=6, antes=antes)


def _secao(d, texto: str):
    return _p(d, (texto, True), tam=13, cor=VERDE, depois=3, antes=8)


def _topo(d, texto: str):
    return _p(d, texto, tam=8.5, cor=CINZA, depois=8)


def _tag(d, texto: str):
    """Parágrafo só com a marca de controle ({%p ... %}); o docxtpl remove o parágrafo inteiro."""
    return _p(d, texto, tam=2, depois=0)


def _sombrear(celula, cor_hex: str):
    tc = celula._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear")
    sh.set(qn("w:color"), "auto")
    sh.set(qn("w:fill"), cor_hex)
    tc.append(sh)


def _tabela(d, cabecalho: list[str], campos: list[str], laco: str, larguras: list[float], tam: float = 10):
    """Tabela com cabeçalho e uma linha por item de `laco` (ex.: "l in linhas")."""
    t = d.add_table(rows=4, cols=len(cabecalho))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    for i, w in enumerate(larguras):
        t.columns[i].width = Cm(w)
        for row in t.rows:
            row.cells[i].width = Cm(w)
    for i, h in enumerate(cabecalho):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(h)
        r.bold, r.font.size, r.font.name = True, Pt(tam), FONTE
        r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        _sombrear(c, "1F5C3A")
    t.rows[1].cells[0].paragraphs[0].add_run(f"{{%tr for {laco} %}}")
    for i, campo in enumerate(campos):
        par = t.rows[2].cells[i].paragraphs[0]
        r = par.add_run(campo)
        r.font.size, r.font.name = Pt(tam), FONTE
    t.rows[3].cells[0].paragraphs[0].add_run("{%tr endfor %}")
    _p(d, "", tam=4, depois=2)
    return t


def _lista(d, laco: str, item: str, marcador: str = "•  ", tam: float = 11):
    _tag(d, f"{{%p for {laco} %}}")
    p = _p(d, marcador, item, tam=tam, depois=2)
    p.paragraph_format.left_indent = Cm(0.5)
    p.paragraph_format.first_line_indent = Cm(-0.5)
    _tag(d, "{%p endfor %}")


# --- folha do dono (3 páginas) ------------------------------------------------------------------------------------


def folha_dono() -> Document:
    d = _documento()
    # página 1: o que a Raíz viu
    _topo(d, "RAÍZ  ·  Folha do imóvel  ·  {{ data }}")
    _titulo(d, "Sua terra em {{ municipio }}")
    _p(
        d,
        "Imóvel do CAR ",
        ("{{ cod_imovel }}", True),
        ". Esta folha mostra o que dados públicos dizem sobre ele. {{ frase_visita }}",
    )
    _secao(d, "Como está a sua terra hoje")
    _tabela(
        d,
        ["", "Hectares", "O que quer dizer"],
        ["{{ l.rotulo }}", "{{ l.valor }}", "{{ l.explica }}"],
        "l in numeros",
        [4.5, 2.6, 9.9],
        tam=10,
    )
    _secao(d, "O que pode render, se a mata voltar")
    _p(d, "{{ texto_carbono }}")
    _p(d, "{{ texto_receita }}")
    _p(d, "Como fizemos a conta: {{ faixas_regra }} (versão {{ faixas_versao }}).", tam=9, cor=CINZA)
    _p(
        d,
        ("Isto é uma estimativa feita de longe, por satélite e cadastro. ", True),
        "O valor certo só sai depois da visita e do contrato. Ninguém pode prometer valor antes disso.",
        antes=6,
    )
    d.add_page_break()

    # página 2: situação da terra
    _topo(d, "RAÍZ  ·  Folha do imóvel  ·  {{ cod_imovel }}")
    _titulo(d, "A situação da sua terra")
    _p(d, ("{{ titulo_rotulo }}", True), tam=12.5, depois=2)
    _p(d, "{{ titulo_texto }}")
    _secao(d, "Pontos de atenção")
    _tag(d, "{%p if atencoes %}")
    _lista(d, "a in atencoes", "{{ a }}")
    _tag(d, "{%p else %}")
    _p(d, "Não achamos embargo, desmatamento recente nem área protegida sobre o imóvel.")
    _tag(d, "{%p endif %}")
    _secao(d, "Documentos que vamos pedir mais adiante")
    _lista(d, "doc in documentos", "{{ doc }}", marcador="☐  ")
    _p(
        d,
        ("Não mande documento pessoal por mensagem agora. ", True),
        "Quando chegar a hora, a gente combina um jeito seguro de entregar.",
        antes=6,
    )
    _secao(d, "De onde vêm estes números")
    _p(d, "{{ fontes }}. Dados de {{ data_dados }}.", tam=10)
    d.add_page_break()

    # página 3: próximos passos e direitos
    _topo(d, "RAÍZ  ·  Folha do imóvel  ·  {{ cod_imovel }}")
    _titulo(d, "Próximos passos")
    _tag(d, "{%p for s in passos %}")
    _p(d, ("{{ s.n }}. {{ s.titulo }}. ", True), "{{ s.texto }}", depois=3)
    _tag(d, "{%p endfor %}")
    _secao(d, "Você decide")
    _p(
        d,
        "Conversar com a Raíz não obriga a nada. Você pode dizer não a qualquer momento antes de assinar. "
        "Se quiser, mostre esta folha a alguém de confiança, ao sindicato ou à assistência técnica.",
    )
    _secao(d, "Seus dados")
    _p(
        d,
        "Usamos dados públicos do imóvel (CAR, satélite, INCRA). Não guardamos seu nome nem seu CPF nos nossos "
        "arquivos de análise. Você pode pedir para ver ou apagar o que temos sobre você (Lei Geral de Proteção de "
        "Dados).",
    )
    _secao(d, "Fale com a gente")
    _p(d, "{{ contato }}")
    _secao(d, "Palavras desta folha")
    _tag(d, "{%p for g in glossario %}")
    _p(d, ("{{ g.termo }}: ", True), "{{ g.texto }}", tam=10, depois=2)
    _tag(d, "{%p endfor %}")
    _p(d, "Raíz · versão {{ versao }}", tam=8, cor=CINZA, antes=8)
    return d


# --- relatório do lote ----------------------------------------------------------------------------------------------


def relatorio_lote() -> Document:
    d = _documento(paisagem=True)
    _topo(d, "RAÍZ  ·  Relatório do lote  ·  {{ data }}")
    _titulo(d, "Lote {{ lote_nome }}")
    _p(d, "{{ n_imoveis }} imóveis em {{ municipios }}. {{ frase_lote }}")
    _secao(d, "Resumo")
    _tabela(d, ["", "Valor"], ["{{ r.rotulo }}", "{{ r.valor }}"], "r in resumo", [9, 6])
    _secao(d, "Carbono e receita por ano: faixa P10 a P90")
    _tabela(
        d,
        ["Medida", "P10", "P50", "P90"],
        ["{{ f.medida }}", "{{ f.p10 }}", "{{ f.p50 }}", "{{ f.p90 }}"],
        "f in faixas_lote",
        [10, 4, 4, 4],
    )
    _p(d, "{{ texto_faixas }}", tam=10)
    _secao(d, "Imóveis do lote")
    _tabela(
        d,
        [
            "Imóvel (CAR)",
            "Município",
            "Porte",
            "Área ha",
            "Restaurar ha",
            "tCO₂/ano P10 · P50 · P90",
            "Título",
            "Terra",
        ],
        [
            "{{ i.cod }}",
            "{{ i.municipio }}",
            "{{ i.porte }}",
            "{{ i.ha }}",
            "{{ i.restaurar }}",
            "{{ i.carbono }}",
            "{{ i.titulo }}",
            "{{ i.terra }}",
        ],
        "i in imoveis",
        [6.2, 3.2, 1.8, 1.8, 2.0, 3.8, 2.6, 3.0],
        tam=8,
    )
    _secao(d, "Título e riscos")
    _tag(d, "{%p if riscos %}")
    _lista(d, "r in riscos", "{{ r }}", tam=10)
    _tag(d, "{%p else %}")
    _p(d, "Nenhum imóvel do lote com matrícula divergente, cancelada ou com ônus grave nas certidões lidas.", tam=10)
    _tag(d, "{%p endif %}")
    _secao(d, "Regra e versões")
    _p(d, ("Faixas por imóvel: ", True), "{{ faixas_regra }}", tam=9.5)
    _p(d, ("Faixa do lote: ", True), "{{ metodo_carteira }}", tam=9.5)
    _p(d, ("Versões: ", True), "{{ versoes }}", tam=9.5)
    _p(d, "Só dados públicos e o código do CAR: nenhum nome ou CPF neste relatório.", tam=8.5, cor=CINZA, antes=6)
    return d


# --- checklist do edital ------------------------------------------------------------------------------------------


def checklist_edital() -> Document:
    d = _documento()
    _topo(d, "RAÍZ  ·  Checklist do edital  ·  {{ data }}")
    _titulo(d, "{{ titulo }}", tam=17)
    _p(d, "{{ orgao }} · {{ modalidade }}", cor=CINZA)
    _p(d, ("Objeto: ", True), "{{ objeto }}")
    _p(d, ("Edital: ", True), "{{ fonte }}", tam=9.5)
    _secao(d, "Prazos")
    _tabela(
        d,
        ["Quando", "O quê", "Faltam"],
        ["{{ p.data }}", "{{ p.evento }}", "{{ p.faltam }}"],
        "p in prazos",
        [3.2, 10.6, 3.2],
    )
    _secao(d, "Requisitos")
    _p(d, "{{ resumo_requisitos }}", tam=10)
    _tabela(
        d,
        ["", "Grupo", "Requisito", "No lote", "No edital"],
        ["{{ r.marca }}", "{{ r.grupo }}", "{{ r.descricao }}", "{{ r.situacao }}", "{{ r.referencia }}"],
        "r in requisitos",
        [0.8, 2.6, 7.8, 3.6, 2.2],
        tam=8.5,
    )
    _tag(d, "{%p if imoveis %}")
    _secao(d, "Imóveis do lote")
    _tabela(
        d,
        ["Imóvel (CAR)", "Atende", "Falta", "Conferir", "O que falta"],
        ["{{ i.cod }}", "{{ i.atende }}", "{{ i.falta }}", "{{ i.conferir }}", "{{ i.faltas }}"],
        "i in imoveis",
        [5.6, 1.6, 1.6, 1.8, 6.4],
        tam=8.5,
    )
    _tag(d, "{%p endif %}")
    _tag(d, "{%p if observacoes %}")
    _secao(d, "Observações")
    _lista(d, "o in observacoes", "{{ o }}", tam=10)
    _tag(d, "{%p endif %}")
    _p(
        d,
        "Leitura do edital por {{ modelo }} em {{ lido_em }} (versão {{ versao }}); critérios avaliados por código, "
        "com os dados do motor. Confira sempre no edital original.",
        tam=8.5,
        cor=CINZA,
        antes=8,
    )
    return d


MODELOS = {
    "folha_dono.docx": folha_dono,
    "relatorio_lote.docx": relatorio_lote,
    "checklist_edital.docx": checklist_edital,
}


def construir(pasta: Path = PASTA) -> list[Path]:
    pasta.mkdir(parents=True, exist_ok=True)
    out = []
    for nome, fazer in MODELOS.items():
        d = fazer()
        cp = d.core_properties
        cp.author, cp.title, cp.comments = "Raíz", nome.removesuffix(".docx"), "modelo docxtpl"
        caminho = pasta / nome
        d.save(caminho)
        out.append(caminho)
    return out


if __name__ == "__main__":
    for p in construir():
        print(p)
