"""Aviso ao cliente sobre um evento de perda, curto, na ordem fonte, fato, fazenda, prazo, o que fazer (plano E9,
passo 4). Sem nome de pessoa e com CPF/CNPJ mascarados; o contato do cliente fica no back-end (esquema pessoal).

Cada marco gera um aviso (identificador fixo: perda + marco), que nasce aguardando a aprovação do fundador. Marcos:
    nova_perda             o evento apareceu
    perda_confirmada       algum alerta do evento foi marcado verdadeiro
    lembrete_aviso_verra   faltam poucos dias para o prazo de avisar a Verra (30 dias da descoberta)
    prazo_atencao          faltam 180 dias ou menos para o prazo do relatório de perda
    prazo_urgente          faltam 30 dias ou menos
    prazo_vencido          o prazo passou sem relatório
"""

from __future__ import annotations

import datetime as dt
import hashlib

import pandas as pd

from raiz.legibilidade import medir
from raiz.vigilancia.privacidade import mascarar
from raiz.vigilancia.regras import Regras

NOME_FONTE = {
    "mapbiomas_alerta": "MapBiomas Alerta",
    "deter": "DETER do INPE",
    "prodes": "PRODES do INPE",
    "firms": "satélites NOAA-20 e NOAA-21 (NASA FIRMS)",
    "ibama_embargo": "embargo do Ibama",
}
NOME_TIPO = {"desmatamento": "derrubada", "degradacao": "degradação da floresta", "fogo": "fogo", "embargo": "embargo"}


def _d(d) -> str:
    return d.strftime("%d/%m/%Y") if d else "data a confirmar"


def _ha(x: float) -> str:
    s = f"{x:,.1f}" if x >= 0.05 else f"{x:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def marcos(perda: dict, regras: Regras) -> list[str]:
    if perda["estado"] in ("descartada", "relatada"):
        return []
    v = regras.verra
    pr = perda["prazo"]
    out = ["nova_perda"]
    if perda["estado"] == "confirmada":
        out.append("perda_confirmada")
    if not pr["aviso_verra_feito_em"] and pr["aviso_verra_dias_restantes"] <= int(v["lembrete_aviso_verra_dias"]):
        out.append("lembrete_aviso_verra")
    if pr["relatorio_obrigatorio"] is not False and not pr["relatorio_enviado_em"]:
        dias = pr["relatorio_dias_restantes"]
        if dias < 0:
            out.append("prazo_vencido")
        elif dias <= int(v["prazo_urgente_dias"]):
            out.append("prazo_urgente")
        elif dias <= int(v["prazo_atencao_dias"]):
            out.append("prazo_atencao")
    return out


def texto(perda: dict, projeto_nome: str, marco: str) -> str:
    pr = perda["prazo"]
    fontes = " e ".join(NOME_FONTE.get(f, f) for f in perda["fontes"])
    tipo = " e ".join(NOME_TIPO.get(t, t) for t in perda["tipos"])
    imagem = _d(perda["data_evento_fim"] or perda["data_evento_inicio"])
    classes = ", ".join(f"{c} {_ha(h)} ha" for c, h in perda["classes_ha"].items())
    fonte = f"Fonte: {fontes}, imagem de {imagem}."
    fato = (
        f"Fato: sinal de {tipo} em {_ha(perda['area_ha'])} ha dentro da área de carbono do projeto {projeto_nome}"
        f"{f' ({classes})' if classes else ''}, evento {perda['perda_id']}, "
        f"{'confirmado' if perda['estado'] == 'confirmada' else f'confiança de {perda["confianca"]:.0%}'}."
    )
    if perda["imoveis"]:
        lista = ", ".join(
            f"{i['cod_imovel']}{f' ({i["municipio"]}/{i["uf"]})' if i.get('municipio') else ''}"
            for i in perda["imoveis"][:3]
        )
        mais = f" e mais {len(perda['imoveis']) - 3}" if len(perda["imoveis"]) > 3 else ""
        fazenda = f"Fazenda: imóvel do CAR {lista}{mais}."
    else:
        c = perda.get("centroide")
        fazenda = f"Fazenda: área do projeto, ponto {c[1]:.5f}, {c[0]:.5f}." if c else "Fazenda: área do projeto."
    obrig = pr["relatorio_obrigatorio"]
    rel = f"relatório de perda até {_d(pr['relatorio_ate'])}" + (
        "" if obrig else " (obrigatório se o projeto já emitiu crédito)"
    )
    if marco == "prazo_vencido":
        prazo = (
            f"Prazo: o relatório de perda venceu em {_d(pr['relatorio_ate'])}; sem ele, o projeto não emite crédito."
        )
    elif pr["aviso_verra_feito_em"]:
        prazo = f"Prazo: Verra já avisada em {_d(pr['aviso_verra_feito_em'])}; {rel}."
    else:
        prazo = f"Prazo: avisar a Verra por e-mail até {_d(pr['aviso_verra_ate'])} e entregar o {rel}."
    if perda["estado"] == "confirmada":
        fazer = "O que fazer: confirmar a área afetada e a causa. O rascunho do relatório de perda está pronto."
    else:
        fazer = (
            "O que fazer: conferir em campo ou com imagem nova e responder se a perda é verdadeira. "
            "O rascunho do relatório de perda já está pronto."
        )
    return mascarar("\n".join([fonte, fato, fazenda, prazo, fazer]))


def avisos(
    perda: dict, projeto, regras: Regras, eventos: pd.DataFrame | None, criados: dict[str, str], hoje: dt.date
) -> list[dict]:
    """Avisos do evento, com a situação de cada um (aguardando_aprovacao, aprovado, enviado, descartado)."""
    out = []
    for m in marcos(perda, regras):
        aid = hashlib.sha1(f"{perda['perda_id']}|{m}".encode()).hexdigest()[:12]
        criados.setdefault(aid, hoje.isoformat())
        estado = "aguardando_aprovacao"
        if eventos is not None and len(eventos):
            e = eventos[(eventos["alvo"] == "aviso") & (eventos["alvo_id"] == aid)]
            if len(e):
                ultimo = e.sort_values("registrado_em").iloc[-1]["tipo"]
                estado = {
                    "aviso_aprovado": "aprovado",
                    "aviso_enviado": "enviado",
                    "aviso_descartado": "descartado",
                }.get(ultimo, estado)
        out.append(
            {
                "aviso_id": aid,
                "perda_id": perda["perda_id"],
                "projeto_id": perda["projeto_id"],
                "cliente": projeto.get("cliente"),
                "marco": m,
                "estado": estado,
                "criado_em": criados[aid],
                "texto": (t := texto(perda, projeto.nome, m)),
                "legibilidade": medir(t),
            }
        )
    return out
