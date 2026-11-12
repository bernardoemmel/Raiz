"""Checklist do edital: prazos em ordem, requisitos com a situação do lote e, por imóvel, o que atende e o que falta.

O modelo leu o edital (edital.py); aqui o código avalia cada critério com os dados do motor e da conferência de
matrícula. Situação por imóvel: ok, falta, conferir (o dado não basta) ou não se aplica. Área mínima vale para o lote
somado: é assim que imóveis pequenos entram juntos.
"""

from __future__ import annotations

import datetime as dt
import unicodedata
from collections import Counter
from pathlib import Path

from raiz.documentos import __version__
from raiz.documentos.armazem import Leitura
from raiz.documentos.gerados.conversao import pasta_gerados, renderizar
from raiz.documentos.gerados.dados import fmt_data, fmt_num, linha_imovel, num
from raiz.documentos.gerados.dados import verdadeiro as V
from raiz.documentos.gerados.edital import GRUPOS

NOME_GRUPO = {
    "habilitacao_juridica": "Habilitação jurídica",
    "regularidade_fiscal": "Regularidade fiscal",
    "qualificacao_tecnica": "Qualificação técnica",
    "qualificacao_economica": "Qualificação econômica",
    "imovel_e_area": "Imóvel e área",
    "ambiental": "Ambiental",
    "proposta_tecnica": "Proposta técnica",
    "proposta_de_preco": "Proposta de preço",
    "garantia": "Garantia",
    "outro": "Outro",
}
ATIVO = {"at", "ativo", "ativa", "active"}


def _sem_acento(s) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn").lower()


def _ate(li: dict, col: str, limite: float = 1.0, *outras) -> tuple[str, str]:
    v = num(li, col, *outras)
    if v is None:
        return "conferir", f"sem a coluna {col}"
    return ("ok", "") if v <= limite else ("falta", f"{fmt_num(v, 1)} ha")


def avaliar(req: dict, li: dict, edital: dict) -> tuple[str, str]:
    """(situação, detalhe) de um requisito para um imóvel."""
    c, vn, vt = req.get("criterio") or "nenhum", req.get("valor_num"), req.get("valor_texto")
    if c == "nenhum":
        return ("documento", "") if req.get("documento") else ("conferir", "")
    if c == "car_ativo":
        st = li.get("status_imovel")
        if st is None:
            return "conferir", "sem situação do CAR"
        return ("ok", "") if _sem_acento(st) in ATIVO else ("falta", f"CAR {st}")
    if c == "sem_embargo":
        return _ate(li, "embargo_ha")
    if c == "sem_desmatamento_apos_2008":
        return _ate(li, "desm_pos2008_ha")
    if c == "sem_desmatamento_apos_2020":
        return _ate(li, "desm_pos2020_ha")
    if c == "sem_alerta_desmatamento":
        return _ate(li, "alerta_pos2020_ha")
    if c == "fora_terra_indigena":
        return _ate(li, "ti_ha", 1.0, "ti_funai_ha")
    if c == "fora_unidade_conservacao":
        return _ate(li, "uc_ha", 1.0, "uc_protecao_integral_ha")
    if c == "sem_projeto_carbono_sobreposto":
        return _ate(li, "projeto_carbono_ha", 10.0)
    if c == "reserva_legal_regular":
        return _ate(li, "deficit_RL_alem_ha", 1.0, "deficit_RL_ha")
    if c == "matricula_regular":
        conf = V(li.get("matricula_conferida"))
        if conf is True:
            return "ok", "matrícula conferida"
        if conf is False:
            return "falta", f"matrícula {li.get('matricula_situacao') or 'não conferida'}"
        f = num(li, "f_matricula", padrao=0) or 0
        return ("conferir", "falta ler a certidão") if f >= 0.5 else ("falta", "sem matrícula no SIGEF")
    if c == "georreferenciamento_sigef":
        return ("ok", "") if (num(li, "sigef_ha", padrao=0) or 0) > 0 else ("falta", "sem parcela no SIGEF")
    if c == "posse_ou_propriedade":
        cam = li.get("caminho_terra")
        if cam in ("privada_matricula", "publica_concessao"):
            return "ok", cam
        if cam in ("posse_em_titulacao", "assentamento"):
            return "conferir", cam
        if cam:
            return "falta", cam
        return ("ok", "matrícula no SIGEF") if (num(li, "f_matricula", padrao=0) or 0) >= 0.5 else ("conferir", "")
    if c == "area_maxima_ha":
        ha = num(li, "ha")
        if ha is None or vn is None:
            return "conferir", ""
        return ("ok", "") if ha <= vn else ("falta", f"{fmt_num(ha, 1)} ha")
    if c == "area_minima_ha":
        return "lote", ""  # somado no lote
    if c == "bioma":
        if not vt or not li.get("bioma"):
            return "conferir", ""
        return ("ok", "") if _sem_acento(li["bioma"]) in _sem_acento(vt) else ("falta", str(li["bioma"]))
    if c == "uf_elegivel":
        alvo = vt or edital.get("uf")
        uf = li.get("uf")
        if not alvo or not uf:
            return "conferir", ""
        return ("ok", "") if _sem_acento(uf) in _sem_acento(alvo) else ("falta", str(uf))
    if c == "municipio_elegivel":
        lista = [_sem_acento(m) for m in (edital.get("municipios") or [])] + ([_sem_acento(vt)] if vt else [])
        mun = li.get("municipio")
        if not lista or not mun:
            return "conferir", ""
        return ("ok", "") if any(_sem_acento(mun) in m or m in _sem_acento(mun) for m in lista) else ("falta", mun)
    return "conferir", ""


def _prazos(edital: dict, hoje: dt.date) -> list[dict]:
    out = []
    for p in edital.get("prazos") or []:
        try:
            d = dt.date.fromisoformat(str(p.get("data"))[:10])
        except ValueError:
            d = None
        faltam = "—" if d is None else ("passou" if d < hoje else ("hoje" if d == hoje else f"{(d - hoje).days} dias"))
        quando = (fmt_data(d) if d else "sem data") + (f" {p['hora']}" if p.get("hora") else "")
        out.append(dict(_d=d or dt.date.max, data=quando, evento=p.get("evento") or "", faltam=faltam))
    return [{k: v for k, v in x.items() if k != "_d"} for x in sorted(out, key=lambda x: x["_d"])]


def contexto(
    leitura: Leitura, cods: list[str] | None = None, cod_municipio: int | None = None, hoje: dt.date | None = None
) -> dict:
    hoje = hoje or dt.date.today()
    e = leitura.dados or {}
    cache: dict = {}
    linhas = [linha_imovel(c, cache, cod_municipio) for c in (cods or [])]
    reqs = sorted(
        e.get("requisitos") or [],
        key=lambda r: GRUPOS.index(r.get("grupo", "outro")) if r.get("grupo") in GRUPOS else 99,
    )
    por_imovel = {li["cod_imovel"]: Counter() for li in linhas}
    faltas = {li["cod_imovel"]: [] for li in linhas}
    area_lote = sum(num(li, "ha", padrao=0) or 0 for li in linhas)
    requisitos = []
    for r in reqs:
        sits = []
        for li in linhas:
            s, det = avaliar(r, li, e)
            if s == "lote":
                vn = r.get("valor_num")
                s = "conferir" if vn is None else ("ok" if area_lote >= vn else "falta")
                det = f"o lote soma {fmt_num(area_lote, 1)} ha"
            sits.append(s)
            chave = "ok" if s in ("ok", "nao_se_aplica") else ("falta" if s == "falta" else "conferir")
            if s != "documento":
                por_imovel[li["cod_imovel"]][chave] += 1
            if s == "falta":
                faltas[li["cod_imovel"]].append(f"{r.get('id')}: {det or r.get('descricao', '')[:40]}")
        if not linhas:
            situacao = "documento a juntar" if r.get("documento") else "—"
        elif all(s == "documento" for s in sits):
            situacao = "documento a juntar"
        elif all(s == "ok" for s in sits):
            situacao = "todos atendem"
        else:
            n_ok, n_falta = sits.count("ok"), sits.count("falta")
            situacao = f"{n_ok} de {len(sits)} atendem" + (f"; {n_falta} não" if n_falta else "; conferir")
        requisitos.append(
            dict(
                marca="☑" if linhas and all(s == "ok" for s in sits) else "☐",
                grupo=NOME_GRUPO.get(r.get("grupo"), "Outro"),
                descricao=(r.get("descricao") or "") + ("" if r.get("obrigatorio", True) else " (opcional)"),
                situacao=situacao,
                referencia=r.get("referencia") or "—",
            )
        )
    n_area = sum(1 for r in reqs if (r.get("criterio") or "nenhum") != "nenhum")
    n_doc = sum(1 for r in reqs if r.get("documento"))
    imoveis = [
        dict(cod=c, atende=v["ok"], falta=v["falta"], conferir=v["conferir"], faltas="; ".join(faltas[c][:4]) or "—")
        for c, v in por_imovel.items()
    ]
    titulo = " ".join(x for x in (e.get("modalidade"), e.get("numero")) if x) or "Edital"
    return dict(
        data=fmt_data(hoje),
        titulo=titulo,
        orgao=e.get("orgao") or "órgão não identificado",
        modalidade=e.get("modalidade") or "—",
        objeto=e.get("objeto") or "—",
        fonte=leitura.chave if not leitura.chave.startswith("sha:") else f"arquivo {leitura.arquivo_sha256[:12]}",
        prazos=_prazos(e, hoje),
        resumo_requisitos=(
            f"{len(reqs)} requisitos: {n_area} sobre o imóvel ou a área (avaliados com os dados do "
            f"motor), {n_doc} documentos a juntar."
            + (f" Lote com {len(linhas)} imóveis e {fmt_num(area_lote, 1)} ha." if linhas else " Sem lote: só a lista.")
        ),
        requisitos=requisitos,
        imoveis=imoveis,
        observacoes=list(e.get("observacoes") or [])[:8],
        modelo=leitura.modelo or leitura.modelo_pedido,
        lido_em=(leitura.lido_em or "")[:10],
        versao=f"{leitura.prompt_versao}; documentos {__version__}",
    )


def gerar(
    leitura: Leitura,
    cods: list[str] | None = None,
    saida: Path | None = None,
    cod_municipio: int | None = None,
    hoje: dt.date | None = None,
) -> Path:
    nome = (leitura.dados or {}).get("numero") or leitura.arquivo_sha256[:12]
    nome = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(nome))[:50]
    saida = saida or pasta_gerados() / f"checklist_edital_{nome}.docx"
    return renderizar("checklist_edital.docx", contexto(leitura, cods, cod_municipio, hoje), saida)
