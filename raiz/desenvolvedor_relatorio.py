"""Relatório "lote pronto para proposta" e folha de 3 páginas para o dono, em HTML para imprimir em A4.

Sem nome, CPF ou CNPJ: o dono aparece pelo código do CAR. Faixas sempre em P10 a P90. Paleta e fontes do guia de
design da Raíz (sem rosa, sem barra colorida na lateral, sem sombra).
"""

from __future__ import annotations

import html
import math
from pathlib import Path

import numpy as np

from raiz import desenvolvedor as D

CSS = """
:root{--papel:#FAFAF7;--superficie:#FFFFFF;--tinta:#15231B;--pedra:#555D56;--nevoa:#E7EAE4;--mata:#1D6B44;
--mata-texto:#16543A;--terra:#A8741A;--terra-texto:#7E5510;--pendencia:#E3A21A;--nao:#C9C4BA}
@page{size:A4;margin:16mm 14mm}
*{box-sizing:border-box}
body{margin:0;background:var(--papel);color:var(--tinta);font:10.5pt/1.45 "Atkinson Hyperlegible Next",
"Atkinson Hyperlegible",system-ui,sans-serif}
h1,h2,h3{font-family:"Familjen Grotesk",system-ui,sans-serif;line-height:1.2;margin:0 0 6px}
h1{font-size:20pt}h2{font-size:13.5pt;margin-top:18px}h3{font-size:11pt;margin-top:12px}
.pagina{page-break-after:always;padding:4px 0}.pagina:last-child{page-break-after:auto}
.sub{color:var(--pedra);margin-bottom:10px}
.numeros{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:10px 0}
.numero{background:var(--superficie);border:1px solid var(--nevoa);border-radius:6px;padding:8px}
.numero b{display:block;font-size:14pt;font-family:"Familjen Grotesk",system-ui,sans-serif}
.numero span{color:var(--pedra);font-size:9pt}
table{width:100%;border-collapse:collapse;margin:6px 0 10px;font-size:9pt;background:var(--superficie)}
th{text-align:left;font-weight:700;border-bottom:1.5px solid var(--tinta);padding:4px 5px}
td{border-bottom:1px solid var(--nevoa);padding:4px 5px;vertical-align:top}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.cod{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:8pt}
.ok{color:var(--mata-texto);font-weight:700}.falha{color:#9E3F0E;font-weight:700}
.pendente,.a_conferir{color:var(--terra-texto);font-weight:700}
.aviso{background:var(--superficie);border:1px solid var(--nevoa);border-radius:6px;padding:8px;color:var(--pedra);
font-size:9pt;margin-top:10px}
.pequeno{font-size:8.5pt;color:var(--pedra)}
.alerta{background:var(--superficie);border:1.5px solid var(--terra);border-radius:6px;padding:8px;
color:var(--terra-texto);font-weight:700}
"""
FONTES = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Familjen+Grotesk:wght@500;700&'
          'family=Atkinson+Hyperlegible+Next:wght@400;700&family=IBM+Plex+Mono&display=swap">')  # fmt: skip
SITUACAO = {"ok": "ok", "falha": "não cumpre", "pendente": "pendente", "a_conferir": "a conferir"}
MAX_ESPERA = 25  # fazendas em espera mostradas no relatório; todas vão para o csv
GRAVIDADE = {"bloqueia": "bloqueia", "alta": "alta", "media": "média", "baixa": "baixa"}


def _e(x) -> str:
    return html.escape("" if x is None else str(x))


def _verdade(x) -> bool:
    return str(x).strip().lower() in ("true", "1", "sim", "1.0")


def _tem(x) -> bool:
    """Valor presente (não vazio, não NaN, não o texto "nan")."""
    if x is None:
        return False
    if isinstance(x, float):
        return math.isfinite(x)
    return str(x).strip().lower() not in ("", "nan", "none")


def _n(x, nd: int = 0) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "sem dado"
    s = f"{x:,.{nd}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _pagina(titulo: str, corpo: str) -> str:
    return (f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>{_e(titulo)}</title>{FONTES}<style>{CSS}</style>'
            f"</head><body>{corpo}</body></html>")  # fmt: skip


def _eixo(v: float) -> str:
    """Rótulo curto do eixo: 1,9 mi ou 623 mil."""
    if v >= 1e6:
        return f"{v / 1e6:.1f}".replace(".", ",") + " mi"
    return f"{_n(v / 1000)} mil"


def leque_svg(credito_40: float, p: dict, volume: float, largura: int = 640, altura: int = 230) -> str:
    """Créditos acumulados do lote ano a ano em leque (P10 a P90) contra as entregas exigidas no Anexo IV."""
    forma = D.forma_curva(p)
    prazo = int(p["contrato"]["prazo_anos"])
    ac = np.concatenate([[0.0], np.cumsum(forma)])[: prazo + 1] * credito_40
    fk = D.fatores_captura(p)
    q10, q90 = float(np.percentile(fk, 10)), float(np.percentile(fk, 90))
    topo = max(ac[-1] * q90, volume) * 1.08
    x0, y0, w, h = 46, 10, largura - 60, altura - 34

    def X(a):
        return x0 + w * a / prazo

    def Y(v):
        return y0 + h - h * v / topo

    def linha(f):
        return " ".join(f"{X(a):.1f},{Y(ac[a] * f):.1f}" for a in range(prazo + 1))

    faixa = linha(q90) + " " + " ".join(f"{X(a):.1f},{Y(ac[a] * q10):.1f}" for a in range(prazo, -1, -1))
    marcos = ""
    tol = float(p["contrato"]["tolerancia_intermediaria"])
    for i, m in enumerate(p["contrato"]["marcos"]):
        alvo = volume * float(m["acumulado"]) / float(p["contrato"]["creditos"])
        lim = alvo if i == len(p["contrato"]["marcos"]) - 1 else alvo * (1 - tol)
        a = int(m["ano"])
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


def relatorio_lote(res: dict, p: dict | None = None) -> str:
    """HTML do relatório "lote pronto para proposta"."""
    p = p or D.premissas()
    r = res["resumo"]
    t = res["tabela"]
    cron = r.get("cronograma_com_reserva") or r.get("cronograma_titulares") or {"marcos": []}
    c10, c50, c90 = r["creditos_contrato_titulares_p10_p50_p90"]
    corpo = [f'<div class="pagina"><h1>Lote pronto para proposta: {_e(r["uf"])}</h1>'
             f'<div class="sub">ProFloresta+ e registro Verra VM0047. Cenário {_e(r["cenario"])}, premissas '
             f'{_e(r["versao_premissas"])}, {_e(r["data"])}.</div>']  # fmt: skip
    corpo.append(
        '<div class="numeros">'
        f'<div class="numero"><b>{_n(r["ha_titulares"])} ha</b><span>{r["titulares"]} fazendas titulares</span></div>'
        f'<div class="numero"><b>{_n(c50)}</b><span>créditos das titulares em 25 anos (P10 {_n(c10)}, '
        f"P90 {_n(c90)})</span></div>"
        f'<div class="numero"><b>R$ {_n(r["custo_liquido_por_credito_medio"])}</b><span>custo líquido por crédito '
        f'(US$ {_n(r["custo_liquido_por_credito_usd_medio"], 1)})</span></div>'
        f'<div class="numero"><b>{_n(r["tir_desenvolvedor_media"], 1)}%</b><span>TIR real do acionista, média</span>'
        "</div></div>"
    )  # fmt: skip
    corpo.append(
        f'<p>Reserva: {r["reservas"]} fazendas (lote com reserva de {_n(r["ha_com_reserva"])} ha). Áreas de mitigação '
        f'do vazamento: {r["mitigacao"]}. Em espera até a terra ficar pronta: {r["em_espera"]} fazendas '
        f'({_n(r["em_espera_ha"])} ha). Regeneração assistida: {_n(r["ha_regeneracao_titulares"])} ha; plantio total: '
        f'{_n(r["ha_plantio_titulares"])} ha.</p>'
    )  # fmt: skip
    if not r.get("fecha_no_p50"):
        tem, pede = _n(r["creditos_40_titulares"]), _n(r["creditos_40_precisa_p50"])
        corpo.append(f'<p class="alerta">Não fecha: as fazendas prontas somam {tem} créditos em 40 anos e o contrato '
                     f"pede {pede} no P50. Faltam fazendas; as que estão em espera entram quando a terra ficar "
                     "pronta.</p>")  # fmt: skip
    elif not r.get("fecha_com_reserva"):
        tem, pede = _n(r["creditos_40_com_reserva"]), _n(r["creditos_40_precisa_com_reserva"])
        corpo.append(f'<p class="alerta">A reserva não fecha: para {r["chance_alvo"]:.0%} de chance de cumprir os '
                     f"marcos o lote precisa de {pede} créditos em 40 anos e as fazendas prontas somam {tem}. A chance "
                     "abaixo já é a do lote com a reserva que existe.</p>")  # fmt: skip
    corpo.append("<h2>Créditos acumulados contra o contrato</h2>")
    corpo.append(leque_svg(r["creditos_40_com_reserva"] or r["creditos_40_titulares"], p, r["volume_creditos"]))
    corpo.append('<p class="pequeno">Linha: P50 do lote com a reserva. Faixa: P10 a P90 (erro da captura comum ao lote '
                 "inteiro). Traços: acumulado exigido em cada marco; o pontilhado vai até o limite com a tolerância "
                 "de 25%.</p>")  # fmt: skip
    corpo.append('<h2>Marcos do Anexo IV</h2><table><tr><th>Ano</th><th class="n">Exigido</th><th class="n">Limite com '
                 'tolerância</th><th class="n">P50 do lote</th><th class="n">Chance de cumprir</th><th class="n">'
                 "Multa esperada</th></tr>")  # fmt: skip
    for m in cron["marcos"]:
        corpo.append(f'<tr><td>{m["ano"]}</td><td class="n">{_n(m["acumulado_exigido"])}</td><td class="n">'
                     f'{_n(m["limiar_com_tolerancia"])}</td><td class="n">{_n(m["acumulado_p50"])}</td><td class="n">'
                     f'{m["chance_cumprir"]:.0%}</td>'
                     f'<td class="n">R$ {_n(m["multa_esperada_rs"])}</td></tr>')  # fmt: skip
    corpo.append("</table>")
    if cron.get("marcos"):
        corpo.append(f'<p>Chance de cumprir todos os marcos: {cron["chance_cumprir_todos"]:.0%}. Chance de rescisão '
                     "(multas acima de 20% do contrato ou marco atrasado mais de 180 dias): "
                     f'{cron["chance_rescisao"]:.0%}.'
                     "</p>")  # fmt: skip
    corpo.append("</div>")
    # checklist
    corpo.append('<div class="pagina"><h2>Checklist do edital</h2><table><tr><th>Bloco</th><th>Item</th><th>Gravidade'
                 "</th><th>Situação</th><th>Detalhe</th></tr>")  # fmt: skip
    for it in r["checklist"]:
        corpo.append(f'<tr><td>{_e(it["bloco"])}</td><td>{_e(it["item"])}</td><td>{GRAVIDADE[it["gravidade"]]}</td>'
                     f'<td class="{it["situacao"]}">{SITUACAO[it["situacao"]]}</td>'
                     f'<td>{_e(it["detalhe"])}</td></tr>')  # fmt: skip
    corpo.append("</table></div>")
    # fazendas
    corpo.append('<div class="pagina"><h2>Fazendas do lote</h2><table><tr><th>Papel</th><th>Código do CAR</th>'
                 '<th>Método</th><th class="n">ha</th><th class="n">Créditos em 40 anos</th><th class="n">R$ por '
                 'crédito</th><th class="n">TIR</th><th>Terra</th></tr>')  # fmt: skip
    nomes = {"regeneracao_assistida": "regeneração", "plantio_total": "plantio"}
    em_espera = (t["papel"] == "em_espera") if "papel" in t else None
    espera = t.iloc[0:0] if em_espera is None else t[em_espera]
    linhas = t
    if len(espera) > MAX_ESPERA:
        espera_mostrada = espera.sort_values("custo_liquido_por_credito").head(MAX_ESPERA)
        linhas = t[~em_espera].to_dict("records") + espera_mostrada.to_dict("records")
    for x in linhas if isinstance(linhas, list) else linhas.to_dict("records"):
        tir = x.get("tir_desenvolvedor")
        corpo.append(
            f'<tr><td>{_e(x.get("papel"))}</td><td class="cod">{_e(x.get("cod_imovel"))}</td>'
            f'<td>{_e(nomes.get(x.get("modo_restauracao"), x.get("modo_restauracao") or ""))}</td>'
            f'<td class="n">{_n(x.get("restauracao_area_ha"), 1)}</td>'
            f'<td class="n">{_n(x.get("credito_liquido_t"))}</td>'
            f'<td class="n">{_n(x.get("custo_liquido_por_credito"))}</td><td class="n">'
            f'{_n(tir, 1) + "%" if isinstance(tir, (int, float)) and math.isfinite(tir) else ""}</td>'
            f'<td>{_e(x.get("caminho_terra") or "")}</td></tr>'
        )  # fmt: skip
    corpo.append("</table>")
    if len(espera) > MAX_ESPERA:
        corpo.append(f'<p class="pequeno">Mostradas {MAX_ESPERA} das {len(espera)} fazendas em espera (as de menor '
                     f'custo por crédito); a lista inteira está em lote_{_e(r["uf"])}.csv.</p>')  # fmt: skip
    corpo.append(f'<div class="aviso">{_e(p["aviso"])} Premissas e fontes: motor/premissas/restauracao_v2026_11.yaml '
                 f'({_e(p["versao_completa"])}).</div></div>')  # fmt: skip
    return _pagina(f"Lote {r['uf']}", "".join(corpo))


def folha_dono(linha: dict, p: dict | None = None, c: dict | None = None) -> str:
    """Folha de 3 páginas para o dono entender a proposta: o que recebe, o que muda e como sai. Sem nome."""
    p = p or D.premissas()
    c = c or D.cenario(p=p)
    cod = linha.get("cod_imovel")
    area = float(linha.get("restauracao_area_ha") or 0.0)
    modo = linha.get("modo_restauracao")
    nome_modo = {"regeneracao_assistida": "regeneração assistida: a mata volta sozinha, com cerca, aceiro e controle "
                                          "do capim; e plantio onde ela não volta",
                 "plantio_total": "plantio de mudas de árvores nativas"}.get(modo, "restauração")  # fmt: skip
    prazo = c["prazo_dono_anos"]
    fk = D.fatores_captura(p)
    faixa = [float(np.percentile(fk, q)) for q in (10, 50, 90)]
    parte, piso = c["parte_dono"], c["piso_dono_rs_ha_ano"]
    # média por ano no contrato todo (coluna pagamento_dono_rs_ha_ano); a parte do crédito anda com a captura
    pag50 = float(linha.get("pagamento_dono_rs_ha_ano") or piso)
    por_ha = [piso + max(pag50 - piso, 0.0) * f for f in faixa]
    total = [x * area for x in por_ha]
    alu = linha.get("aluguel_referencia_rs_ha_ano")
    onde = {"municipio": "no seu município", "uf": "no seu estado", "brasil": "no Brasil"}.get(
        str(linha.get("aluguel_referencia_fonte")), "na região"
    )
    cab = linha.get("cabecas_deslocadas")
    viz = linha.get("vazamento_mitigacao_imovel")
    viz = viz if _tem(viz) and _verdade(linha.get("vazamento_mitigacao")) else None
    cab = cab if _tem(cab) and float(cab) > 0 else None
    pg1 = (
        f'<div class="pagina"><h1>Proposta para a sua fazenda</h1><div class="sub">Imóvel do CAR <span class="cod">'
        f"{_e(cod)}</span>. Estimativa da Raíz, não é contrato.</div>"
        f"<h2>O que propomos</h2><p>Restaurar {_n(area, 1)} hectares de pasto que ficam fora da reserva legal e da "
        f"beira de rio, com {nome_modo}. O contrato dura {prazo} anos. A empresa que restaura paga a obra, cuida da "
        "área e vende os créditos de carbono que as árvores guardam.</p>"
        "<h2>O que você recebe</h2>"
        f"<p>Todo ano, um valor fixo de R$ {_n(piso)} por hectare, e mais {parte:.0%} do que a venda dos créditos da "
        "sua área render. Os créditos são vendidos de tempos em tempos, então essa parte chega em parcelas maiores, a "
        "primeira perto do sétimo ano.</p>"
        f'<div class="numeros"><div class="numero"><b>R$ {_n(total[1])}</b><span>por ano, em média, na área toda'
        f'</span></div><div class="numero"><b>R$ {_n(por_ha[1])}</b><span>por hectare e ano, em média</span></div>'
        f'<div class="numero"><b>R$ {_n(total[0])} a {_n(total[2])}</b><span>por ano se a floresta crescer menos ou '
        f'mais que o previsto</span></div><div class="numero"><b>{prazo} anos</b><span>de contrato</span></div></div>'
    )  # fmt: skip
    if _tem(alu):
        pg1 += (f"<p>Para comparar: quem arrenda terra {onde} pagava cerca de R$ {_n(alu)} por hectare "
                "ao ano "
                "no Censo Agropecuário de 2017. Um aluguel fixo também é possível, mas não acompanha o resultado da "
                "floresta.</p>")  # fmt: skip
    pg1 += "</div>"
    pg2 = (
        '<div class="pagina"><h2>O que muda na fazenda</h2><ul>'
        "<li>A área da proposta sai do pasto. O gado não pode voltar para ela durante o contrato.</li>"
        + (f"<li>Saem cerca de {_n(cab)} cabeças dessa área."
           + (f" Uma fazenda vizinha (CAR <span class=\"cod\">{_e(viz)}</span>) pode receber esse gado num pasto "
              "melhor cuidado, e isso conta a favor do projeto.</li>" if viz else "</li>") if cab else "")
        + "<li>A empresa coloca cerca e aceiro, controla o capim e combate o fogo.</li>"
        "<li>Técnicos vão medir as árvores de tempos em tempos.</li></ul>"
        "<h2>O que você assina</h2><ul>"
        f"<li>Cede à empresa o direito ao carbono da área por {prazo} anos, sem poder voltar atrás. É o que o "
        "comprador exige.</li>"
        "<li>O contrato é registrado na matrícula do imóvel, no cartório.</li>"
        "<li>A terra continua sua. O contrato vale também para quem comprar ou herdar a fazenda.</li></ul></div>"
    )  # fmt: skip
    opc = c["opcao_rs_ha_mes"] * c["opcao_meses"]
    pg3 = (
        '<div class="pagina"><h2>Como começa</h2>'
        f"<p>Em duas fases. Primeiro, uma opção: a empresa paga R$ {_n(c['opcao_rs_ha_mes'])} por hectare ao mês "
        f"(cerca de R$ {_n(opc * area)} no ano) enquanto disputa o leilão de compra de créditos. Se ganhar, a opção "
        "vira "
        "o contrato firme. Se perder, cada um segue o seu caminho e o que foi pago fica com você.</p>"
        "<h2>Riscos que você precisa saber</h2><ul>"
        "<li>Os valores são estimativas. Se a floresta crescer menos, a parte dos créditos é menor; o valor fixo "
        "por hectare continua.</li>"
        f"<li>Sair antes dos {prazo} anos tem custo: o projeto perde os créditos já emitidos da área, e o contrato "
        "vai dizer a multa.</li>"
        "<li>Leia o contrato com calma e, se puder, com um advogado ou o sindicato rural.</li></ul>"
        f'<div class="aviso">{_e(p["aviso"])} Premissas {_e(p["versao_completa"])}.</div></div>'
    )  # fmt: skip
    return _pagina(f"Proposta {cod}", pg1 + pg2 + pg3)


def gravar_lote(res: dict, pasta: str | Path, linhas_por_cod: dict[str, dict] | None = None,
                p: dict | None = None, c: dict | None = None) -> dict[str, str]:  # fmt: skip
    """Grava lote_<UF>.csv, lote_<UF>.json (resumo e checklist), relatorio_lote_<UF>.html e a folha de cada dono
    das titulares e reservas."""
    import json

    p = p or D.premissas()
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    uf = res["resumo"]["uf"] or "UF"
    out = {"csv": str(pasta / f"lote_{uf}.csv"), "json": str(pasta / f"lote_{uf}.json"),
           "relatorio": str(pasta / f"relatorio_lote_{uf}.html")}  # fmt: skip
    res["tabela"].to_csv(out["csv"], index=False)
    Path(out["json"]).write_text(
        json.dumps(res["resumo"], ensure_ascii=False, indent=1, default=float), encoding="utf-8"
    )
    Path(out["relatorio"]).write_text(relatorio_lote(res, p), encoding="utf-8")
    n = 0
    if linhas_por_cod:
        donos = pasta / "folhas_dono"
        donos.mkdir(exist_ok=True)
        for x in res["tabela"].to_dict("records"):
            if x.get("papel") in ("titular", "reserva") and x["cod_imovel"] in linhas_por_cod:
                (donos / f"folha_dono_{x['cod_imovel']}.html").write_text(
                    folha_dono(linhas_por_cod[x["cod_imovel"]], p, c), encoding="utf-8"
                )
                n += 1
    out["folhas_dono"] = str(n)
    return out
