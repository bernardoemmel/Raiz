"""Relatório do lote: imóveis agrupados (grupo_id do desenvolvedor_<mun>.csv, lista de códigos do CAR ou frente de um
município), com a faixa P10 a P90 de carbono e receita por imóvel e do lote (soma e carteira lado a lado), título e
riscos. Pequenas entram agrupadas: nenhum imóvel sai do lote por tamanho.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from pathlib import Path

from raiz.documentos import __version__
from raiz.documentos.gerados import faixas as FX
from raiz.documentos.gerados.conversao import pasta_gerados, renderizar
from raiz.documentos.gerados.dados import fmt_data, fmt_moeda, fmt_num, linha_imovel, num, porte
from raiz.documentos.gerados.dados import verdadeiro as V

ROTULO_TITULO = {
    "conferida": "conferida",
    "divergente": "divergente",
    "cancelada": "cancelada",
    "revisar": "certidão ilegível",
    "a_conferir": "a conferir",
}


def _titulo(li: dict) -> str:
    sit = li.get("matricula_situacao")
    if V(li.get("matricula_conferida")) is True:
        return "conferida"
    if sit in ROTULO_TITULO and sit != "a_conferir":
        return ROTULO_TITULO[sit]
    f = num(li, "f_matricula", padrao=0) or 0
    if f >= 0.5:
        return "a conferir"
    if (num(li, "assentamento_ha", padrao=0) or 0) > 0.5 * (num(li, "ha", padrao=1) or 1):
        return "assentamento"
    return "parcial" if f > 0.001 else "sem matrícula"


def _terra(li: dict) -> str:
    rot = li.get("caminho_terra_rotulo") or li.get("caminho_terra") or li.get("frente") or "—"
    risco = li.get("risco_terra")
    return f"{rot} (risco {risco})" if risco else str(rot)


def _riscos(linhas: list[dict]) -> list[str]:
    out = []
    for li in linhas:
        cod, motivos = li["cod_imovel"], []
        sit = li.get("matricula_situacao")
        if sit in ("divergente", "cancelada", "revisar"):
            m = (li.get("matricula_motivo") or "").split(";")[0].strip()
            motivos.append(f"matrícula {ROTULO_TITULO[sit]}" + (f" ({m})" if m else ""))
        if V(li.get("matricula_onus_graves")):
            motivos.append("ônus grave na matrícula")
        if V(li.get("matricula_quebra_cadeia")):
            motivos.append("quebra na cadeia de donos")
        for col, txt in (
            ("embargo_ha", "embargo do Ibama"),
            ("desm_pos2020_ha", "desmatamento depois de 2020"),
            ("ti_ha", "sobreposição com terra indígena"),
        ):
            v = num(li, col, padrao=0) or 0
            if v > 1:
                motivos.append(f"{txt} ({fmt_num(v, 1)} ha)")
        if motivos:
            out.append(f"{cod}: {'; '.join(motivos)}.")
    return out


def contexto(
    cods: list[str],
    lote_nome: str,
    cod_municipio: int | None = None,
    rho: float | None = None,
    hoje: dt.date | None = None,
    n_sorteios: int = 20000,
) -> dict:
    if not cods:
        raise ValueError("lote sem imóveis")
    rho = FX.rho_padrao() if rho is None else rho
    cache: dict = {}
    linhas = [linha_imovel(c, cache, cod_municipio) for c in cods]
    fxs = [FX.do_imovel(li) for li in linhas]
    carb, rec = [f.carbono for f in fxs], [f.receita for f in fxs]
    moeda = fxs[0].moeda
    s_c, c_c = FX.soma(carb), FX.carteira(carb, rho, n_sorteios)
    s_r = FX.soma(rec)
    so_motor = all(f.fonte in ("motor", "sem_dado") for f in fxs)
    c_r = (
        FX.receita_carteira(carb, FX.REGRA_PROVISORIA["preco"], rho, n_sorteios)
        if so_motor
        else FX.carteira(rec, rho, n_sorteios)
    )
    rho_txt = f"{rho:.1f}".replace(".", ",")

    def faixa(medida, f, moeda_=None):
        fmt = (lambda x: fmt_moeda(x, moeda_)) if moeda_ else fmt_num
        return dict(medida=medida, p10=fmt(f.p10), p50=fmt(f.p50), p90=fmt(f.p90))

    portes = Counter(porte(li) for li in linhas)
    municipios = sorted({str(li.get("municipio") or li["cod_municipio"]) for li in linhas})
    ha = sum(num(li, "ha", padrao=0) or 0 for li in linhas)
    rest = sum(num(li, "comp_para_restaurar_ha", "carbono_ha", padrao=0) or 0 for li in linhas)
    titulos = Counter(_titulo(li) for li in linhas)
    grupo = next((li.get("grupo_id") for li in linhas if li.get("grupo_id")), None)
    pequenas = portes.get("pequeno", 0)
    resumo = [
        dict(rotulo="Imóveis", valor=f"{len(linhas)} ({', '.join(f'{v} {k}' for k, v in portes.most_common())})"),
        dict(rotulo="Municípios", valor=", ".join(municipios)),
        dict(rotulo="Área total", valor=f"{fmt_num(ha, 1)} ha"),
        dict(rotulo="Área para restaurar", valor=f"{fmt_num(rest, 1)} ha"),
        dict(rotulo="Matrícula conferida", valor=f"{titulos.get('conferida', 0)} de {len(linhas)} imóveis"),
        dict(rotulo="Título por situação", valor=", ".join(f"{v} {k}" for k, v in titulos.most_common())),
    ]
    if grupo:
        resumo.insert(0, dict(rotulo="Grupo", valor=str(grupo)))
    imoveis = []
    for li, f in zip(linhas, fxs, strict=True):
        c = f.carbono
        imoveis.append(
            dict(
                cod=li["cod_imovel"],
                municipio=str(li.get("municipio") or li["cod_municipio"]),
                porte=porte(li),
                ha=fmt_num(num(li, "ha"), 1),
                restaurar=fmt_num(num(li, "comp_para_restaurar_ha", "carbono_ha"), 1),
                carbono="—" if c.vazia else f"{fmt_num(c.p10)} · {fmt_num(c.p50)} · {fmt_num(c.p90)}",
                titulo=_titulo(li),
                terra=_terra(li),
            )
        )
    regras = sorted({f"{f.versao}: {f.regra}" for f in fxs if f.fonte != "sem_dado"})
    versoes_mat = sorted({str(li["matricula_leitor_versao"]) for li in linhas if li.get("matricula_leitor_versao")})
    tabelas_usadas = sorted({t for li in linhas for t in li["_tabelas"]})
    return dict(
        data=fmt_data(hoje),
        lote_nome=lote_nome,
        n_imoveis=len(linhas),
        municipios=", ".join(municipios),
        frase_lote=(
            f"Pequenas entram agrupadas: {pequenas} dos {len(linhas)} imóveis têm até 4 módulos fiscais."
            if pequenas
            else ""
        ),
        resumo=resumo,
        faixas_lote=[
            faixa("Carbono por ano (tCO₂), soma", s_c),
            faixa(f"Carbono por ano (tCO₂), carteira (correlação {rho_txt})", c_c),
            faixa(f"Receita por ano ({moeda}), soma", s_r, moeda),
            faixa(f"Receita por ano ({moeda}), carteira (correlação {rho_txt})", c_r, moeda),
        ],
        texto_faixas=(
            "Em 8 de cada 10 cenários o valor fica entre o P10 e o P90. A soma supõe que todos os imóveis erram para "
            "o mesmo lado (piso e teto mais largos); a carteira deixa os erros se compensarem em parte. Receita antes "
            "dos custos da restauração e da parte do desenvolvedor."
        ),
        imoveis=imoveis,
        riscos=_riscos(linhas),
        faixas_regra=" | ".join(regras) or "sem conta de carbono para os imóveis do lote",
        metodo_carteira=FX.metodo_carteira(rho, n_sorteios),
        versoes=(
            f"documentos {__version__}; tabelas lidas: {', '.join(tabelas_usadas)}"
            + (f"; leitura de matrícula {', '.join(versoes_mat)}" if versoes_mat else "")
        ),
    )


def gerar(
    cods: list[str],
    lote_nome: str,
    saida: Path | None = None,
    cod_municipio: int | None = None,
    rho: float | None = None,
    hoje: dt.date | None = None,
) -> Path:
    nome = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in lote_nome)[:60]
    saida = saida or pasta_gerados() / f"relatorio_lote_{nome}.docx"
    return renderizar("relatorio_lote.docx", contexto(cods, lote_nome, cod_municipio, rho, hoje), saida)
