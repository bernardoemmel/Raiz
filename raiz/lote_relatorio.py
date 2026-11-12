"""Relatório "lote pronto para proposta" (para o desenvolvedor) e folha de 3 páginas para o dono, em HTML para imprimir
em A4.

Sem nome, CPF ou CNPJ: o dono aparece pelo código do CAR. Faixas sempre em P10 a P90. Paleta e fontes do guia de
design da Raíz (sem rosa, sem barra colorida na lateral, sem sombra). Unificado com a branch claude/premissas-rodada11.
"""

from __future__ import annotations

import html
import json
import math
from pathlib import Path

import numpy as np

from raiz import restauracao as R

CSS = """
:root{--papel:#FAFAF7;--superficie:#FFFFFF;--tinta:#15231B;--pedra:#555D56;--nevoa:#E7EAE4;--mata:#1D6B44;
--mata-texto:#16543A;--terra:#A8741A;--terra-texto:#7E5510;--pendencia:#E3A21A;--nao:#C9C4BA}
@page{size:A4;margin:16mm 14mm}
*{box-sizing:border-box}
body{margin:0;background:var(--papel);color:var(--tinta);font:10.5pt/1.45 "Atkinson Hyperlegible Next",
"Atkinson Hyperlegible",system-ui,sans-serif}
h1,h2,h3{font-family:"Familjen Grotesk",system-ui,sans-serif;line-height:1.2;margin:0 0 6px}
h1{font-size:20pt}h2{font-size:13.5pt;margin-top:18px}h3{font-size:11pt;margin-top:12px}
.pagina{page-break-after:always;padding:4px 0;max-width:780px;margin:0 auto}.pagina:last-child{page-break-after:auto}
.sub{color:var(--pedra);margin-bottom:10px}
.numeros{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:10px 0}
@media (max-width:640px){.numeros{grid-template-columns:repeat(2,1fr)}}
.numero{background:var(--superficie);border:1px solid var(--nevoa);border-radius:6px;padding:8px}
.numero b{display:block;font-size:14pt;font-family:"Familjen Grotesk",system-ui,sans-serif}
.numero span{color:var(--pedra);font-size:9pt}
table{width:100%;border-collapse:collapse;margin:6px 0 10px;font-size:9pt;background:var(--superficie)}
th{text-align:left;font-weight:700;border-bottom:1.5px solid var(--tinta);padding:4px 5px}
td{border-bottom:1px solid var(--nevoa);padding:4px 5px;vertical-align:top}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.cod{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:8pt;word-break:break-all}
.ok{color:var(--mata-texto);font-weight:700}.falha{color:#9E3F0E;font-weight:700}
.pendente,.a_conferir{color:var(--terra-texto);font-weight:700}
.aviso{background:var(--superficie);border:1px solid var(--nevoa);border-radius:6px;padding:8px;color:var(--pedra);
font-size:9pt;margin-top:10px}
.pequeno{font-size:8.5pt;color:var(--pedra)}
.alerta{background:var(--superficie);border:1.5px solid var(--terra);border-radius:6px;padding:8px;
color:var(--terra-texto);font-weight:700}
.bom{background:var(--superficie);border:1.5px solid var(--mata);border-radius:6px;padding:8px;color:var(--mata-texto);
font-weight:700}
"""
FONTES = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Familjen+Grotesk:wght@500;700&'
          'family=Atkinson+Hyperlegible+Next:wght@400;700&family=IBM+Plex+Mono&display=swap">')  # fmt: skip
SITUACAO = {"ok": "ok", "falha": "não cumpre", "pendente": "pendente", "a_conferir": "a conferir"}
GRAVIDADE = {"bloqueia": "bloqueia", "alta": "alta", "media": "média", "baixa": "baixa"}
NOMES_CAMINHO = {
    "matricula_conferida": "matrícula com certidão conferida",
    "matricula_a_conferir": "matrícula a conferir (certidão a pedir)",
    "concessao": "terra pública sob concessão",
    "posse_em_titulacao": "posse em titulação",
    "assentamento": "assentamento",
}
NOMES_MODO = {"regeneracao_assistida": "regeneração", "semeadura_direta": "semeadura", "plantio_total": "plantio"}
MAX_LINHAS = 60  # fazendas por papel no relatório; todas vão para o csv
AVISO = ("Estimativa da Raíz a partir de dados públicos (CAR, SIGEF, MapBiomas, YbYrá, Censo Agro) e das premissas da "
         "rodada 11, cada uma com fonte; não é laudo nem oferta firme. Os números mudam com a versão das premissas, "
         "que fica gravada em cada lote.")  # fmt: skip


def _e(x) -> str:
    return html.escape("" if x is None else str(x))


def _tem(x) -> bool:
    if x is None:
        return False
    if isinstance(x, float):
        return math.isfinite(x)
    return str(x).strip().lower() not in ("", "nan", "none")


def _n(x, nd: int = 0) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "sem dado"
    s = f"{float(x):,.{nd}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _pl(n, um: str, varios: str) -> str:
    return f"{_n(n)} {um if round(float(n)) == 1 else varios}"


def _pct(x, nd: int = 1) -> str:
    return "sem TIR" if x is None else f"{_n(x, nd)}%"


def _usd(x, nd: int = 2) -> str:
    return "acima de US$ 1.000" if x is None else f"US$ {_n(x, nd)}"


def _pagina(titulo: str, corpo: str) -> str:
    return (f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>{_e(titulo)}</title>{FONTES}<style>{CSS}</style>'
            f"</head><body>{corpo}</body></html>")  # fmt: skip


def _eixo(v: float) -> str:
    if v >= 1e6:
        return f"{v / 1e6:.1f}".replace(".", ",") + " mi"
    return f"{_n(v / 1000)} mil"


def leque_svg(credito_contrato_p50: float, volume: float, c: dict, r: dict, largura: int = 640,
              altura: int = 230) -> str:  # fmt: skip
    """Créditos acumulados do lote ano a ano em leque (P10 a P90) contra as entregas exigidas no Anexo IV."""
    forma = R.forma_curva(r)
    T = int(c["prazo_anos"])
    ac = np.concatenate([[0.0], np.cumsum(forma)])[: T + 1]
    ac = ac / max(ac[-1], 1e-12) * credito_contrato_p50
    cc = r["captura_curva"]["incerteza_captura"]
    q10, q90 = float(cc["p10"]), float(cc["p90"])
    topo = max(ac[-1] * q90, volume) * 1.08
    x0, y0, w, h = 46, 10, largura - 60, altura - 34

    def X(a):
        return x0 + w * a / T

    def Y(v):
        return y0 + h - h * v / topo

    def linha(f):
        return " ".join(f"{X(a):.1f},{Y(ac[a] * f):.1f}" for a in range(T + 1))

    faixa = linha(q90) + " " + " ".join(f"{X(a):.1f},{Y(ac[a] * q10):.1f}" for a in range(T, -1, -1))
    marcos = ""
    n = len(c["entregas_anos"])
    for i, (a, pct) in enumerate(zip(c["entregas_anos"], c["marcos_pct"], strict=True)):
        tol = float(c.get("tolerancia_ultimo_marco") or 0.0) if i == n - 1 else float(c["tolerancia_marco"])
        alvo = volume * float(pct) / 100
        lim = alvo * (1 - tol)
        marcos += (f'<line x1="{X(a) - 6:.1f}" x2="{X(a) + 6:.1f}" y1="{Y(alvo):.1f}" y2="{Y(alvo):.1f}" '
                   f'stroke="#15231B" stroke-width="2"/><line x1="{X(a):.1f}" x2="{X(a):.1f}" y1="{Y(alvo):.1f}" '
                   f'y2="{Y(lim):.1f}" stroke="#15231B" stroke-width="1" stroke-dasharray="2 2"/>'
                   f'<text x="{X(a):.1f}" y="{altura - 6}" font-size="9" text-anchor="middle" fill="#555D56">ano {a}'
                   "</text>")  # fmt: skip
    eixo = "".join(f'<text x="{x0 - 6}" y="{Y(v) + 3:.1f}" font-size="9" text-anchor="end" fill="#555D56">'
                   f"{_eixo(v)}</text>" for v in np.linspace(0, topo, 4)[1:])  # fmt: skip
    return (f'<svg viewBox="0 0 {largura} {altura}" width="100%" role="img" aria-label="Créditos acumulados do lote '
            f'em faixa P10 a P90 contra as entregas do contrato">'
            f'<line x1="{x0}" x2="{x0 + w}" y1="{y0 + h}" y2="{y0 + h}" stroke="#E7EAE4"/>{eixo}'
            f'<polygon points="{faixa}" fill="#1D6B44" fill-opacity="0.18"/>'
            f'<polyline points="{linha(1.0)}" fill="none" stroke="#1D6B44" stroke-width="2.5"/>'
            f"{marcos}</svg>")  # fmt: skip


def _bloco_preco(res: dict) -> str:
    """Preço do contrato e o preço mínimo por crédito para a TIR de 12% e de 15% (item 2a da revisão)."""
    eco = res.get("economia") or {}
    pm = eco.get("preco_minimo_usd") or {}
    fx = res["cambio_brl_usd"]
    linhas = [("Preço do contrato (ProFloresta+)", res["preco_contrato_usd"], eco.get("tir_alavancada_pct"),
               eco.get("tir_projeto_pct")),
              ("Preço de equilíbrio (TIR do projeto = WACC de " + _n(100 * res["taxa_desconto"], 1) + "%)",
               eco.get("preco_equilibrio_usd"), None, None)]  # fmt: skip
    for alvo in ("12", "15"):
        x = pm.get(alvo) or {}
        linhas.append((f"Mínimo para TIR de {alvo}% com Fundo Clima", x.get("alavancada"), float(alvo), None))
        linhas.append((f"Mínimo para TIR de {alvo}% sem dívida (projeto)", x.get("projeto"), None, float(alvo)))
    corpo = ['<h2>Preço por crédito e retorno do lote</h2><table><tr><th></th><th class="n">US$ por crédito</th>'
             '<th class="n">R$ por crédito</th><th class="n">TIR com Fundo Clima</th><th class="n">TIR do projeto</th>'
             "</tr>"]  # fmt: skip
    for nome, preco, ta, tp in linhas:
        corpo.append(f'<tr><td>{_e(nome)}</td><td class="n">{_usd(preco)}</td><td class="n">'
                     f'{"" if preco is None else "R$ " + _n(preco * fx, 2)}</td><td class="n">'
                     f'{"" if ta is None else _pct(ta)}</td><td class="n">{"" if tp is None else _pct(tp)}</td>'
                     "</tr>")  # fmt: skip
    corpo.append("</table>")
    corpo.append(f'<p class="pequeno">Fluxo do lote inteiro (titulares e reserva) no caminho do P50: a soma dos fluxos '
                 f"das fazendas, a dívida do Fundo Clima dimensionada no caixa do lote pelo ICSD "
                 f'({_n(100 * (eco.get("divida_fracao") or 0))}% do investimento), a multa esperada dos marcos e o '
                 f'crédito além do contrato ({_n(eco.get("excesso_creditos"))} créditos) vendido ao preço depois do '
                 f"contrato. Câmbio de R$ {_n(fx, 4)}. Pico de capital próprio: R$ "
                 f'{_n(eco.get("pico_capital_rs"))}.</p>')  # fmt: skip
    return "".join(corpo)


ORDEM_REGULARIZACAO = ("em_titulacao", "pronta_para_pedir", "falta_georreferenciamento", "pendente", "impedida",
                       "sem_calculo")  # fmt: skip
NOMES_REGULARIZACAO = {
    "em_titulacao": "Em titulação no SIGEF",
    "pronta_para_pedir": "Pronta para pedir o título",
    "falta_georreferenciamento": "Só falta o georreferenciamento",
    "pendente": "Com pendência (embargo, desmatamento recente, CAR, ocupação sem prova)",
    "impedida": "Não se regulariza (sobreposição)",
    "sem_calculo": "Ainda sem cálculo",
}


def _bloco_faixa(res: dict) -> str:
    """Faixa do lote lado a lado (soma e carteira), os campos da Portaria MME 102/2016 e as parcelas de campo."""
    fl, mm, pc = res.get("faixa"), res.get("mme102"), res.get("parcelas") or {}
    if not fl:
        return ""
    corpo = ['<h2>Faixa do lote (Portaria MME 102/2016)</h2><table><tr><th>Créditos até o ano 25</th>'
             '<th class="n">P10</th><th class="n">P50</th><th class="n">P90</th></tr>']  # fmt: skip
    for nome, x in (
        ("Soma das fazendas (todas errando juntas)", fl["soma"]),
        (f"Carteira ({_n(100 * fl['fracao_comum'])}% do erro comum às fazendas)", fl["carteira"]),
    ):
        corpo.append(
            f'<tr><td>{_e(nome)}</td><td class="n">{_n(x["p10"])}</td><td class="n">{_n(x["p50"])}</td>'
            f'<td class="n">{_n(x["p90"])}</td></tr>'
        )
    corpo.append("</table>")
    corpo.append(
        f"<p>P50: {_n(mm['p50'])} créditos. P90 de excedência (o que o lote passa com 90% de chance): "
        f"{_n(mm['p90_excedencia'])} na carteira e {_n(mm['p90_excedencia_soma'])} na soma. Incerteza padrão: "
        f"{_n(mm['incerteza_padrao'])} créditos ({_n(mm['incerteza_padrao_pct'], 1)}% do P50). Revisor "
        "independente: pendente. A reserva do lote é dimensionada pela soma, a mais prudente.</p>"
    )
    if pc.get("total"):
        estratos = ", ".join(f"{_n(v)} em {NOMES_MODO.get(k, k)}" for k, v in pc["por_metodo"].items())
        corpo.append(
            f"<p>Parcelas de campo para medir o lote: {_n(pc['total'])} ({estratos}), de "
            f"{_n(pc['area_parcela_ha'], 1)} ha cada, para {_n(100 * pc['confianca'])}% de confiança e "
            f"{_n(100 * pc['erro_admissivel'])}% de erro (AR-TOOL03 do MDL, mínimo de 30 no lote).</p>"
        )
    return "".join(corpo)


def tornado_svg(sens: list[dict], largura: int = 640) -> str:
    """Barras horizontais da TIR do lote com cada entrada no P10 e no P90 (as outras no P50)."""
    linhas = [x for x in sens if x.get("tir_baixo") is not None and x.get("tir_alto") is not None]
    if not linhas:
        return ""
    base = linhas[0]["tir_base"] or 0.0
    vals = [v for x in linhas for v in (x["tir_baixo"], x["tir_alto"])] + [base]
    lo, hi = min(vals) - 1, max(vals) + 1
    x0, w, h = 230, largura - 250, 26
    altura = h * len(linhas) + 24

    def X(v):
        return x0 + w * (v - lo) / (hi - lo)

    partes = [f'<svg viewBox="0 0 {largura} {altura}" width="100%" role="img" aria-label="TIR do lote com cada '
              'entrada no P10 e no P90">']  # fmt: skip
    for i, x in enumerate(linhas):
        y = 6 + i * h
        a, b = sorted((x["tir_baixo"], x["tir_alto"]))
        partes.append(f'<text x="{x0 - 8}" y="{y + 14}" font-size="10" text-anchor="end" fill="#15231B">'
                      f'{_e(x["nome"])}</text><rect x="{X(a):.1f}" y="{y + 3}" width="{max(X(b) - X(a), 1):.1f}" '
                      f'height="{h - 10}" fill="#1D6B44" fill-opacity="0.35"/><text x="{X(a) - 4:.1f}" y="{y + 14}" '
                      f'font-size="9" text-anchor="end" fill="#555D56">{_n(a, 1)}%</text><text x="{X(b) + 4:.1f}" '
                      f'y="{y + 14}" font-size="9" fill="#555D56">{_n(b, 1)}%</text>')  # fmt: skip
    partes.append(f'<line x1="{X(base):.1f}" x2="{X(base):.1f}" y1="2" y2="{altura - 18}" stroke="#15231B" '
                  f'stroke-width="1.5"/><text x="{X(base):.1f}" y="{altura - 4}" font-size="9" text-anchor="middle" '
                  f'fill="#555D56">TIR no P50: {_n(base, 1)}%</text></svg>')  # fmt: skip
    return "".join(partes)


def _bloco_sensibilidade(res: dict) -> str:
    sens = res.get("sensibilidade") or []
    if not sens:
        return ""
    corpo = ["<h2>O que mais mexe na TIR do lote</h2>", tornado_svg(sens),
             '<table><tr><th>Entrada</th><th class="n">P10</th><th class="n">P90</th><th class="n">TIR no P10</th>'
             '<th class="n">TIR no P90</th></tr>']  # fmt: skip
    for x in sens:

        def v(z):
            return _e(z.upper()) if isinstance(z, str) else _n(z, 2)

        corpo.append(
            f'<tr><td>{_e(x["nome"])}</td><td class="n">{v(x["baixo"])}</td><td class="n">{v(x["alto"])}'
            f'</td><td class="n">{_pct(x["tir_baixo"])}</td><td class="n">{_pct(x["tir_alto"])}</td></tr>'
        )
    corpo.append('</table><p class="pequeno">TIR com Fundo Clima do lote inteiro, refeita fazenda a fazenda com cada '
                 "entrada no P10 e no P90 e as outras no P50.</p>")  # fmt: skip
    return "".join(corpo)


def _bloco_destrava(res: dict) -> str:
    """Quadro "o que destrava o lote" (item 2b): regeneração em posse em titulação e assentamento e o cenário com a
    terra destravada."""
    esp = res["em_espera"]
    td = res.get("terra_destravada")
    corpo = ['<h2>O que destrava o lote</h2><p>Fazendas que não entram hoje porque a terra ainda não está pronta '
             'para um '
             "contrato de 40 anos: posse em titulação (falta o título) e assentamento (depende do aval do INCRA). "
             "Viram título ou parceria e entram no lote.</p>"
             '<table><tr><th>Terra</th><th class="n">Fazendas</th><th class="n">ha para restaurar</th>'
             '<th class="n">ha de regeneração</th><th class="n">Créditos até o ano 25</th>'
             '<th class="n">da regeneração</th></tr>']  # fmt: skip
    for cam, x in esp["por_caminho"].items():
        corpo.append(
            f'<tr><td>{_e(NOMES_CAMINHO.get(cam, cam))}</td><td class="n">{_n(x["fazendas"])}</td>'
            f'<td class="n">{_n(x["ha"])}</td><td class="n">{_n(x["ha_regeneracao"])}</td>'
            f'<td class="n">{_n(x["creditos"])}</td><td class="n">{_n(x["creditos_regeneracao"])}</td></tr>'
        )
    corpo.append("</table>")
    pr = esp.get("por_regularizacao") or {}
    if pr:  # quão perto do título está a terra em espera (raiz/titulo/regularizacao.py)
        corpo.append("<p>Quão perto do título está a terra em espera (o que falta, pelo que se vê em satélite e "
                     "cadastro):</p>"
                     '<table><tr><th>Situação</th><th class="n">Fazendas</th><th class="n">ha para restaurar</th>'
                     '<th class="n">Créditos até o ano 25</th></tr>')  # fmt: skip
        for cl in ORDEM_REGULARIZACAO:
            if cl in pr:
                x = pr[cl]
                nome = _e(NOMES_REGULARIZACAO.get(cl, cl))
                corpo.append(
                    f'<tr><td>{nome}</td><td class="n">{_n(x["fazendas"])}</td>'
                    f'<td class="n">{_n(x["ha"])}</td><td class="n">{_n(x["creditos"])}</td></tr>'
                )
        corpo.append("</table>")
    if td:
        eco0, eco1 = res.get("economia") or {}, td.get("economia") or {}
        pm0 = (eco0.get("preco_minimo_usd") or {}).get("12") or {}
        pm1 = (eco1.get("preco_minimo_usd") or {}).get("12") or {}
        cr0 = res.get("cronograma_lote") or {}
        cr1 = td.get("cronograma_lote") or {}
        corpo.append('<table><tr><th></th><th class="n">Hoje (terra pronta)</th><th class="n">Terra destravada</th>'
                     "</tr>")  # fmt: skip
        for nome, a, b in (
            ("Fecha 1 milhão com reserva", "sim" if res["fecha_com_reserva"] else "não",
             "sim" if td["fecha_com_reserva"] else "não"),
            ("Fazendas no lote (titulares e reserva)", _n(res["titulares"] + res["reservas"]),
             _n(td["titulares"] + td["reservas"])),
            ("ha no lote", _n(res["ha_lote"]), _n(td["ha_lote"])),
            ("Custo médio por crédito", _usd(res["custo_credito_usd_medio"]), _usd(td["custo_credito_usd_medio"])),
            ("Preço de equilíbrio do lote", _usd(eco0.get("preco_equilibrio_usd")),
             _usd(eco1.get("preco_equilibrio_usd"))),
            ("TIR com Fundo Clima a US$ " + _n(res["preco_contrato_usd"]), _pct(eco0.get("tir_alavancada_pct")),
             _pct(eco1.get("tir_alavancada_pct"))),
            ("TIR do projeto", _pct(eco0.get("tir_projeto_pct")),
             _pct(eco1.get("tir_projeto_pct"))),
            ("Preço mínimo para TIR de 12% com Fundo Clima", _usd(pm0.get("alavancada")), _usd(pm1.get("alavancada"))),
            ("Chance de cumprir todos os marcos", f'{cr0.get("chance_todos", 0):.0%}',
             f'{cr1.get("chance_todos", 0):.0%}'),
        ):  # fmt: skip
            corpo.append(f'<tr><td>{_e(nome)}</td><td class="n">{a}</td><td class="n">{b}</td></tr>')
        corpo.append(
            f'</table><p class="pequeno">Terra destravada: as {_n(esp["fazendas"])} fazendas em espera '
            "contadas como se o título saísse ou a parceria com o INCRA fosse assinada, e o lote montado de "
            f"novo pelo mesmo otimizador; ele usaria {_n(td['fazendas_destravadas_no_lote'])} delas.</p>"
        )
    return "".join(corpo)


def _bloco_certidoes(res: dict) -> str:
    """Matrícula com certidão conferida contra a conferir e quantas certidões pedir para os 5% (item 2c)."""
    ce = res["certidoes"]
    corpo = ['<h2>Terra do lote: matrícula e certidões</h2><table><tr><th>Terra</th><th class="n">Fazendas</th>'
             '<th class="n">ha</th></tr>']  # fmt: skip
    for cam in ("matricula_conferida", "matricula_a_conferir", "concessao"):
        x = ce["por_caminho"][cam]
        corpo.append(
            f'<tr><td>{_e(NOMES_CAMINHO[cam])}</td><td class="n">{_n(x["fazendas"])}</td>'
            f'<td class="n">{_n(x["ha"])}</td></tr>'
        )
    corpo.append("</table>")
    exig = (
        f"A assinatura pede {ce['fracao_exigida']:.0%} da área do lote homologada: {_n(ce['ha_exigidos'])} ha de "
        f"{_n(ce['ha_lote'])} ha. Hoje: {_n(ce['ha_homologados'])} ha (certidão conferida ou concessão)."
    )
    if ce["falta_ha"] <= 0:
        corpo.append(f'<p class="bom">{exig} Já cumpre; falta o aceite assinado.</p>')
    elif ce["cumpre_com_pedidos"]:
        cert = _pl(ce["certidoes_a_pedir"], "certidão", "certidões")
        faz = _pl(ce["fazendas_a_pedir"], "fazenda", "fazendas")
        corpo.append(f'<p class="alerta">{exig} Pedir {cert} de matrícula de {faz} com matrícula a conferir '
                     f'({_n(ce["ha_cobertos"])} ha): as de mais área por certidão primeiro. Estão marcadas em '
                     "pedir_certidao no csv do lote.</p>")  # fmt: skip
    else:
        corpo.append(
            f'<p class="alerta">{exig} Nem todas as matrículas a conferir do lote somam o que falta: '
            f"faltariam {_n(ce['falta_ha'] - ce['ha_cobertos'])} ha.</p>"
        )
    corpo.append(
        f'<p class="pequeno">{_n(ce["matriculas_conhecidas"])} matrículas a conferir já têm cartório e número '
        f"no SIGEF (certidoes_&lt;mun&gt;.csv); {_n(ce['a_conferir_sem_matricula_sigef'])} fazendas com "
        "matrícula a conferir não têm o número no SIGEF e contam uma certidão a localizar.</p>"
    )
    return "".join(corpo)


def relatorio_lote(lote: dict, c: dict | None = None, r: dict | None = None) -> str:
    """HTML do relatório "lote pronto para proposta", para o desenvolvedor."""
    r = r or R.regra()
    res = lote["resumo"]
    c = c or R.cenario(res["cenario"], r)
    t = lote["tabela"]
    cron = res.get("cronograma_lote") or {"marcos": []}
    fx = res.get("creditos_lote_faixa") or {"p10": 0, "p50": 0, "p90": 0}
    mun = res["municipios"]
    eco = res.get("economia") or {}
    corpo = [
        f'<div class="pagina"><h1>Lote potencial para proposta: {_e(res["uf"])}</h1>'
        f'<div class="sub">ProFloresta+ e registro Verra VM0047. {_n(res["volume_creditos"])} créditos. Cenário '
        f"{_e(res['cenario'])}, premissas {_e(res['versao_premissas'])}, otimizador "
        f"{_e(res['versao_otimizador'])}, {_e(res['data'])}.</div>"
        f"<p>Municípios: {_n(mun['lidos'])} de {_n(mun['no_estado'])} do estado entraram no cálculo "
        f"({_n(mun['com_fazenda_elegivel'])} com fazenda de terra pronta; {_n(mun['no_lote'])} com fazenda no "
        f"lote). Oferta: {_n(res['oferta']['fazendas'])} fazendas com área para restaurar "
        f"({_n(res['oferta']['ha'])} ha); {_n(res['oferta']['fazendas_terra_pronta'])} com a terra pronta.</p>"
    ]
    comercializacao = res.get("comercializacao") or {}
    corpo.append(f'<p class="alerta">{_e(comercializacao.get("aviso", "Estimativa sujeita a diligência."))}</p>')
    corpo.append(f"<p>Opção: {_e(res.get('opcao_texto', 'mais barata'))}. Alternativas não se somam.</p>")
    pendencias = res.get("o_que_destrava") or []
    if pendencias:
        corpo.append(
            "<h2>O que destrava: terra e salvaguardas</h2><p>Potencial condicionado; uma fazenda pode ter "
            "várias pendências, por isso as linhas não se somam.</p><table><tr><th>Pendência</th>"
            "<th>Fazendas</th><th>Hectares</th><th>P10</th><th>P50</th><th>P90</th></tr>"
        )
        for item in pendencias:
            cr = item["creditos"]
            corpo.append(
                f"<tr><td>{_e(item['pendencia'])}</td><td>{_n(item['fazendas'])}</td>"
                f"<td>{_n(item['ha'])}</td><td>{_n(cr['p10'])}</td><td>{_n(cr['p50'])}</td>"
                f"<td>{_n(cr['p90'])}</td></tr>"
            )
        corpo.append("</table>")
    corpo.append(
        '<div class="numeros">'
        f'<div class="numero"><b>{_n(res["ha_lote"])} ha</b><span>{res["titulares"]} titulares e {res["reservas"]} de '
        f'reserva ({res["pequenas"]} pequenas)</span></div>'
        f'<div class="numero"><b>{_n(fx["p50"])}</b><span>créditos até o ano 25 (P10 {_n(fx["p10"])}, P90 '
        f'{_n(fx["p90"])})</span></div>'
        f'<div class="numero"><b>{_usd(res["custo_credito_usd_medio"])}</b><span>custo médio por crédito</span></div>'
        f'<div class="numero"><b>{_pct(eco.get("tir_alavancada_pct"))}</b><span>TIR do lote com Fundo Clima a '
        f'US$ {_n(res["preco_contrato_usd"])}</span></div></div>'
    )  # fmt: skip
    hm = res.get("ha_por_metodo") or {}
    corpo.append(
        f"<p>Regeneração assistida: {_n(hm.get('regeneracao_assistida'))} ha; semeadura direta: "
        f"{_n(hm.get('semeadura_direta'))} ha; plantio total: {_n(hm.get('plantio_total'))} ha. Áreas de "
        f"mitigação do vazamento: {res['mitigacao']} vizinhas. Em espera até a terra destravar: "
        f"{_n(res['em_espera']['fazendas'])} fazendas ({_n(res['em_espera']['ha'])} ha).</p>"
    )
    if res["o_que_falta"]:
        corpo.append(
            '<div class="alerta"><p>O que falta para fechar com reserva:</p><ul>'
            + "".join(f"<li>{_e(x)}</li>" for x in res["o_que_falta"])
            + "</ul></div>"
        )
    else:
        corpo.append(
            f'<p class="bom">Fecha {_n(res["volume_creditos"])} créditos com reserva: '
            f"{res['chance_alvo']:.0%} de chance de cumprir todos os marcos.</p>"
        )
    ab = res.get("abaixo_equilibrio") or {}
    if ab.get("aviso"):
        corpo.append(f'<p class="alerta">{_e(ab["aviso"])}</p>')
    corpo.append("<h2>Créditos acumulados contra o contrato</h2>")
    corpo.append(leque_svg(res["creditos_lote"], res["volume_creditos"], c, r))
    corpo.append('<p class="pequeno">Linha: P50 do lote com a reserva. Faixa: P10 a P90 (o erro da captura é comum ao '
                 "lote inteiro, não se cancela entre fazendas). Traços: acumulado exigido em cada marco; o pontilhado "
                 "vai até o limite com a tolerância (25% nos intermediários, nenhuma no último).</p>")  # fmt: skip
    corpo.append('<h2>Marcos do Anexo IV</h2><table><tr><th>Ano</th><th class="n">Exigido</th><th class="n">Limite com '
                 'tolerância</th><th class="n">P50 do lote</th><th class="n">Chance de cumprir</th><th class="n">'
                 "Multa esperada</th></tr>")  # fmt: skip
    for m in cron["marcos"]:
        corpo.append(f'<tr><td>{m["ano"]}</td><td class="n">{_n(m["acumulado_exigido"])}</td><td class="n">'
                     f'{_n(m["limiar"])}</td><td class="n">{_n(m["acumulado_p50"])}</td><td class="n">'
                     f'{m["chance"]:.0%}</td><td class="n">R$ {_n(m["multa_esperada_rs"])}</td></tr>')  # fmt: skip
    corpo.append("</table>")
    if cron.get("marcos"):
        corpo.append(f'<p>Chance de cumprir todos os marcos: {cron["chance_todos"]:.0%}. Chance de rescisão (multas '
                     "acima de 20% do contrato ou marco atrasado mais de 180 dias): "
                     f'{cron["chance_rescisao"]:.0%}.</p>')  # fmt: skip
    corpo.append(_bloco_preco(res))
    corpo.append("</div>")
    corpo.append(f'<div class="pagina">{_bloco_faixa(res)}{_bloco_sensibilidade(res)}</div>')
    corpo.append(f'<div class="pagina">{_bloco_destrava(res)}{_bloco_certidoes(res)}</div>')
    corpo.append('<div class="pagina"><h2>Checklist do edital</h2><table><tr><th>Bloco</th><th>Item</th><th>Gravidade'
                 "</th><th>Situação</th><th>Detalhe</th></tr>")  # fmt: skip
    for it in res["checklist"]:
        corpo.append(f'<tr><td>{_e(it["bloco"])}</td><td>{_e(it["item"])}</td><td>{GRAVIDADE[it["gravidade"]]}</td>'
                     f'<td class="{it["situacao"]}">{SITUACAO[it["situacao"]]}</td>'
                     f'<td>{_e(it["detalhe"])}</td></tr>')  # fmt: skip
    corpo.append("</table></div>")
    corpo.append('<div class="pagina"><h2>Fazendas do lote</h2><table><tr><th>Papel</th><th>Código do CAR</th>'
                 '<th>Método</th><th class="n">ha</th><th class="n">Créditos até o ano 25</th><th class="n">US$ por '
                 'crédito</th><th class="n">Equilíbrio</th><th>Terra</th></tr>')  # fmt: skip
    resto = []
    for papel in ("titular", "reserva", "mitigacao", "em_espera"):
        x = t[t.papel == papel]
        if papel == "em_espera":
            x = x.sort_values("preco_equilibrio_usd")
        if len(x) > MAX_LINHAS:
            resto.append(f"{_n(len(x) - MAX_LINHAS)} de {_e(papel.replace('_', ' '))}")
            x = x.head(MAX_LINHAS)
        for li in x.to_dict("records"):
            eq = li.get("preco_equilibrio_usd")
            corpo.append(
                f'<tr><td>{_e(papel.replace("_", " "))}</td><td class="cod">{_e(li.get("cod_imovel"))}</td>'
                f'<td>{_e(NOMES_MODO.get(li.get("modo"), li.get("modo") or ""))}</td>'
                f'<td class="n">{_n(li.get("area_ha"), 1) if _tem(li.get("area_ha")) else ""}</td>'
                f'<td class="n">{_n(li.get("credito_p50")) if _tem(li.get("credito_p50")) else ""}</td>'
                f'<td class="n">{_n(li.get("custo_credito_usd"), 2) if _tem(li.get("custo_credito_usd")) else ""}</td>'
                f'<td class="n">{_usd(eq) if _tem(eq) else ""}</td>'
                f'<td>{_e(NOMES_CAMINHO.get(li.get("caminho"), li.get("caminho") or ""))}</td></tr>'
            )  # fmt: skip
    corpo.append("</table>")
    if resto:
        corpo.append(f'<p class="pequeno">Não mostradas aqui: {", ".join(resto)}; a lista inteira está em '
                     f'lote_{_e(res["uf"])}.csv.</p>')  # fmt: skip
    corpo.append(f'<div class="aviso">{AVISO} Premissas e fontes: raiz/regras/padroes/restauracao.yaml '
                 f'({_e(res["versao_premissas"])}); checklist: edital_profloresta.yaml ({_e(res["versao_edital"])}).'
                 "</div></div>")  # fmt: skip
    return _pagina(f"Lote {res['uf']}", "".join(corpo))


# --- folha do dono ------------------------------------------------------------------------------------------------


def numeros_dono(linha: dict, c: dict, r: dict) -> dict:
    """O que o dono recebe por ha e por ano (P10/P50/P90), o total em 40 anos e as comparações: o aluguel do Censo e a
    renda do gado na mesma área."""
    area = float(R._num(linha, "restauracao_area_ha") or 0.0)
    H = int(c["horizonte_anos"])
    piso = float(c["piso_dono_rs_ha_ano"])
    pag50 = R._num(linha, "dono_rs_ha_ano")
    pag50 = float(pag50) if pag50 is not None else piso
    cc = r["captura_curva"]["incerteza_captura"]
    fat = (float(cc["p10"]), 1.0, float(cc["p90"]))
    por_ha = [piso + max(pag50 - piso, 0.0) * f for f in fat]
    alug, fonte_alug = R.arrendamento_censo(linha, c, r)
    pec = R.renda_pecuaria(linha, r)
    return {
        "area_ha": area, "anos": H, "piso": piso,
        "parte": float(c["participacao_dono"]),
        "por_ha_ano": por_ha, "por_ano": [x * area for x in por_ha], "total_40_anos": [x * area * H for x in por_ha],
        "por_ha_40_anos": [x * H for x in por_ha], "aluguel_rs_ha_ano": alug, "aluguel_fonte": fonte_alug,
        "pecuaria": pec,
    }  # fmt: skip


def folha_dono(linha: dict, c: dict | None = None, r: dict | None = None) -> str:
    """Folha de 3 páginas para o dono entender a proposta: o que recebe, como compara com o aluguel e com o gado, o que
    muda e como sai. Todo contato, dúvida e assinatura passam pela Raíz. Sem nome."""
    r = r or R.regra()
    c = c or R.cenario(r=r)
    cod = linha.get("cod_imovel")
    x = numeros_dono(linha, c, r)
    area, H = x["area_ha"], x["anos"]
    modo = linha.get("modo_restauracao")
    nome_modo = {"regeneracao_assistida": "regeneração assistida: a mata volta sozinha, com cerca, aceiro e controle "
                                          "do capim; e plantio onde ela não volta",
                 "semeadura_direta": "semeadura direta: sementes de árvores nativas lançadas no pasto preparado",
                 "plantio_total": "plantio de mudas de árvores nativas"}.get(modo, "restauração")  # fmt: skip
    pg1 = (
        f'<div class="pagina"><h1>Proposta para a sua fazenda</h1><div class="sub">Imóvel do CAR <span class="cod">'
        f"{_e(cod)}</span>. Estimativa da Raíz, não é contrato.</div>"
        '<p class="bom">Todo o contato passa pela Raíz: as dúvidas, a negociação e a assinatura. A empresa que '
        "restaura não liga direto para você; a Raíz fala com você pelo WhatsApp oficial, por carta ou com um "
        "parceiro local credenciado, explica cada ponto e colhe a assinatura só quando você quiser.</p>"
        f"<h2>O que propomos</h2><p>Restaurar {_n(area, 1)} hectares de pasto que ficam fora da reserva legal e da "
        f"beira de rio, com {nome_modo}. O contrato dura {H} anos. A empresa que restaura paga a obra, cuida da "
        "área e vende os créditos de carbono que as árvores guardam.</p>"
        "<h2>O que você recebe</h2>"
        f"<p>Todo ano, um valor fixo de R$ {_n(x['piso'])} por hectare, e mais {x['parte']:.0%} do que a venda dos "
        "créditos da sua área render. Os créditos são vendidos de tempos em tempos, então essa parte chega em parcelas "
        "maiores, a primeira perto do sétimo ano.</p>"
        f'<div class="numeros"><div class="numero"><b>R$ {_n(x["total_40_anos"][1])}</b><span>no total, em {H} anos '
        f'(de R$ {_n(x["total_40_anos"][0])} a R$ {_n(x["total_40_anos"][2])})</span></div>'
        f'<div class="numero"><b>R$ {_n(x["por_ano"][1])}</b><span>por ano, em média, na área toda</span></div>'
        f'<div class="numero"><b>R$ {_n(x["por_ha_ano"][1])}</b><span>por hectare e ano, em média</span></div>'
        f'<div class="numero"><b>R$ {_n(x["por_ano"][0])} a {_n(x["por_ano"][2])}</b><span>por ano se a floresta '
        "crescer menos ou mais que o previsto</span></div></div>"
    )  # fmt: skip
    comp = ['<h2>Comparando com o que a área rende hoje</h2><table><tr><th></th><th class="n">R$ por ha e ano</th>'
            f'<th class="n">Em {H} anos, na área toda</th></tr>',
            f'<tr><td>Esta proposta (média)</td><td class="n">{_n(x["por_ha_ano"][1])}</td>'
            f'<td class="n">{_n(x["total_40_anos"][1])}</td></tr>']  # fmt: skip
    pec = x["pecuaria"]
    if pec:
        comp.append(f'<tr><td>Gado na mesma área: venda de bois (receita bruta, sem tirar custos)</td><td class="n">'
                    f'{_n(pec["receita_bruta_rs_ha_ano"])}</td><td class="n">'
                    f'{_n(pec["receita_bruta_rs_ha_ano"] * area * H)}</td></tr>'
                    f'<tr><td>Gado na mesma área: o que sobra depois dos custos (margem de referência de '
                    f'{_n(100 * pec["margem_referencia"], 1)}%)</td><td class="n">'
                    f'{_n(pec["sobra_referencia_rs_ha_ano"])}</td><td class="n">'
                    f'{_n(pec["sobra_referencia_rs_ha_ano"] * area * H)}</td></tr>')  # fmt: skip
    if x["aluguel_rs_ha_ano"] is not None:
        onde = {"municipio": "no seu município", "uf": "no seu estado", "brasil": "no Brasil"}.get(
            str(x["aluguel_fonte"]), "na região"
        )
        comp.append(
            f'<tr><td>Arrendar a terra ({_e(onde)})</td><td class="n">{_n(x["aluguel_rs_ha_ano"])}</td>'
            f'<td class="n">{_n(x["aluguel_rs_ha_ano"] * area * H)}</td></tr>'
        )
    comp.append("</table>")
    nota = []
    if pec:
        nota.append(f"O gado: venda de bovinos por hectare de pasto no seu município no Censo Agropecuário de 2017, "
                    f"corrigida pela inflação (IPCA) até {_e(pec['ipca_ate'])}; a sobra usa a margem de referência da "
                    "CNA (Campo Futuro, recria e engorda no Pará). Cada fazenda é diferente: compare com as suas "
                    "contas.")  # fmt: skip
    if x["aluguel_rs_ha_ano"] is not None:
        nota.append(
            "O arrendamento: o que se pagava por hectare de terra arrendada no Censo Agropecuário de 2017. Um "
            "aluguel fixo também é possível, mas não acompanha o resultado da floresta."
        )
    pg1 += "".join(comp) + (f'<p class="pequeno">{" ".join(nota)}</p>' if nota else "") + "</div>"
    cab = R._num(linha, "cabecas_deslocadas")
    viz = linha.get("vazamento_mitigacao_imovel")
    viz = viz if _tem(viz) and str(linha.get("vazamento_motivo")) == "mitigacao_vizinha" else None
    cab = cab if cab is not None and cab > 0 else None
    pg2 = (
        '<div class="pagina"><h2>O que muda na fazenda</h2><ul>'
        "<li>A área da proposta sai do pasto. O gado não pode voltar para ela durante o contrato.</li>"
        + ((f"<li>Saem cerca de {_n(cab)} cabeças dessa área."
            + (f' Uma fazenda vizinha (CAR <span class="cod">{_e(viz)}</span>) pode receber esse gado num pasto '
               "melhor cuidado, e isso conta a favor do projeto.</li>" if viz else "</li>")) if cab else "")
        + "<li>A empresa coloca cerca e aceiro, controla o capim e combate o fogo.</li>"
        "<li>Técnicos vão medir as árvores de tempos em tempos.</li></ul>"
        "<h2>O que você assina</h2><ul>"
        f"<li>Cede à empresa o direito ao carbono da área por {H} anos, sem poder voltar atrás. É o que o "
        "comprador exige.</li>"
        "<li>O contrato é registrado na matrícula do imóvel, no cartório.</li>"
        "<li>A terra continua sua. O contrato vale também para quem comprar ou herdar a fazenda.</li>"
        "<li>A assinatura é feita com a Raíz, que confere o documento com você antes.</li></ul></div>"
    )  # fmt: skip
    f1 = float(c["fase1_rs_ha_ano"])
    pg3 = (
        '<div class="pagina"><h2>Como começa</h2>'
        f"<p>Em duas fases. Primeiro, uma opção: a empresa paga R$ {_n(f1 / 12, 2)} por hectare ao mês "
        f"(cerca de R$ {_n(f1 * area)} no ano) enquanto disputa o leilão de compra de créditos. Se ganhar, a opção "
        "vira o contrato firme. Se perder, cada um segue o seu caminho e o que foi pago fica com você.</p>"
        "<h2>Riscos que você precisa saber</h2><ul>"
        "<li>Os valores são estimativas. Se a floresta crescer menos, a parte dos créditos é menor; o valor fixo "
        "por hectare continua.</li>"
        f"<li>Sair antes dos {H} anos tem custo: o projeto perde os créditos já emitidos da área, e o contrato "
        "vai dizer a multa.</li>"
        "<li>Leia o contrato com calma e, se puder, com um advogado ou o sindicato rural. Qualquer dúvida, fale com a "
        "Raíz: é ela que responde e acompanha você do primeiro contato à assinatura.</li></ul>"
        f'<div class="aviso">{AVISO} Premissas {_e(r["versao_completa"])}.</div></div>'
    )  # fmt: skip
    return _pagina(f"Proposta {cod}", pg1 + pg2 + pg3)


# --- gravar -------------------------------------------------------------------------------------------------------


def gravar_lote(lote: dict, pasta: str | Path, c: dict | None = None, r: dict | None = None,
                folhas: bool = True) -> dict[str, str]:  # fmt: skip
    """Grava lote_<UF>.csv (todas as fazendas com o papel), lote_<UF>.json (resumo, marcos e checklist),
    relatorio_lote_<UF>.html e a folha de cada dono das titulares e reservas."""
    from raiz import lote as L

    r = r or R.regra()
    c = c or R.cenario(lote["resumo"]["cenario"], r)
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    uf = lote["resumo"]["uf"] or "UF"
    out = {"csv": str(pasta / f"lote_{uf}.csv"), "json": str(pasta / f"lote_{uf}.json"),
           "relatorio": str(pasta / f"relatorio_lote_{uf}.html")}  # fmt: skip
    lote["tabela"].to_csv(out["csv"], index=False)
    Path(out["json"]).write_text(json.dumps(L.json_seguro(lote["resumo"]), ensure_ascii=False, indent=1),
                                 encoding="utf-8")  # fmt: skip
    Path(out["relatorio"]).write_text(relatorio_lote(lote, c, r), encoding="utf-8")
    from raiz import restauracao_ecologia as E
    from raiz.regras import salvaguardas_lote as S

    out["decisoes"] = str(pasta / f"decisoes_{uf}.jsonl")
    S.gravar_decisoes(out["decisoes"], lote.get("decisoes", []))
    t = lote["tabela"]
    cods = list(t[t.papel.isin(["titular", "reserva"])].cod_imovel.astype(str))
    ecologia = E.tabela(lote["linhas"].completas(cods).values(), r["versao_completa"])
    out["ecologia"] = str(pasta / f"ecologia_{uf}.json")
    Path(out["ecologia"]).write_text(
        json.dumps(L.json_seguro(ecologia), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    n = 0
    if folhas:
        t = lote["tabela"]
        cods = list(t[t.papel.isin(["titular", "reserva"])].cod_imovel.astype(str))
        donos = pasta / "folhas_dono"
        donos.mkdir(exist_ok=True)
        for cod, li in lote["linhas"].completas(cods).items():
            (donos / f"folha_dono_{cod}.html").write_text(folha_dono(li, c, r), encoding="utf-8")
            n += 1
    out["folhas_dono"] = str(n)
    return out
