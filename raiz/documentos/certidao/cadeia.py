"""Cadeia dominial de cada certidão lida, ato por ato, para o Postgres (E5 passo 6, no molde do ACRIS).

cadeia_<mun>.csv: uma linha por ato da leitura vigente de cada matrícula do município (as do certidoes_<mun>.csv),
com os dados da matrícula repetidos em cada linha (situação, origem, matrícula de origem, área, destino) e as partes
do ato em JSON só com rótulo (P1, P2), tipo, documento mascarado e nome de instituição (órgão público e banco).
A carga (raiz/carga.py) leva para titulo.matricula, titulo.ato e titulo.ato_parte, sem repetir a mesma leitura.
Nada de nome ou CPF: a leitura já vem limpa (leitor.sanear) e o documento passa de novo pela máscara aqui.
"""

from __future__ import annotations

import json

import pandas as pd

from raiz.documentos.certidao.esquema import TRANSMISSAO
from raiz.documentos.certidao.regras import normalizar_ato, normalizar_cns, normalizar_matricula
from raiz.documentos.privacidade import mascarar, mascarar_documento

COLUNAS = [
    "registro_cns",
    "registro_matricula",
    "leitura_hash",
    "leitura_id",
    "lido_em",
    "modelo",
    "leitor_versao",
    "regras_versao",
    "matricula_situacao",
    "conferencia",
    "origem",
    "origem_referencia",
    "origem_matricula",
    "data_abertura",
    "area_matricula_ha",
    "matricula_destino",
    "georreferenciado",
    "n_transmissoes",
    "quebras",
    "onus_graves",
    "proprietarios_json",
    "ordem",
    "ato_numero",
    "ato_tipo",
    "natureza",
    "afeta",
    "data",
    "fracao_pct",
    "pagina",
    "transmissao",
    "anterior_numero",
    "cancelado_por",
    "quebra",
    "quebra_motivo",
    "resumo",
    "transmitentes_json",
    "adquirentes_json",
]
INSTITUICOES = {"orgao_publico", "instituicao_financeira"}


def _parte(partes: dict, rotulo: str) -> dict:
    p = partes.get(rotulo) or {}
    tipo = p.get("tipo") or "desconhecido"
    return dict(
        rotulo=rotulo,
        tipo=tipo,
        documento=mascarar_documento(p.get("documento")),
        instituicao=p.get("nome_instituicao") if tipo in INSTITUICOES else None,
    )


def linhas_da_leitura(dados: dict, derivados: dict, meta: dict) -> list[dict]:
    """Uma linha por ato. meta: leitura_hash, leitura_id, lido_em, modelo, leitor_versao, regras_versao, conferencia."""
    mat = dados.get("matricula") or {}
    cart = dados.get("cartorio") or {}
    atos = list(dados.get("atos") or [])
    partes = {p.get("rotulo"): p for p in (dados.get("partes") or []) if p.get("rotulo")}
    origem = mat.get("origem")
    base = dict(
        registro_cns=normalizar_cns(cart.get("cns")),
        registro_matricula=normalizar_matricula(mat.get("numero")),
        **{k: meta.get(k) for k in ("leitura_hash", "leitura_id", "lido_em", "modelo", "leitor_versao")},
        regras_versao=meta.get("regras_versao"),
        matricula_situacao=derivados.get("situacao_documento"),
        conferencia=meta.get("conferencia"),
        origem=origem,
        origem_referencia=mascarar(mat.get("origem_referencia")) if mat.get("origem_referencia") else None,
        origem_matricula=normalizar_matricula(mat.get("origem_referencia")) if origem == "matricula_anterior" else None,
        data_abertura=mat.get("data_abertura"),
        area_matricula_ha=derivados.get("area_ha"),
        matricula_destino=normalizar_matricula(derivados.get("matricula_destino")),
        georreferenciado=derivados.get("georreferenciado"),
        n_transmissoes=derivados.get("n_transmissoes"),
        quebras=len(derivados.get("quebras_cadeia") or []),
        onus_graves=derivados.get("onus_graves"),
        proprietarios_json=json.dumps(
            [
                dict(rotulo=p.get("rotulo"), tipo=p.get("tipo"), documento=mascarar_documento(p.get("documento")))
                for p in derivados.get("proprietarios_atuais") or []
            ],
            ensure_ascii=False,
        ),
    )
    if not atos:
        return [{**base, "ordem": None}]
    cancelado_por: dict[str, str] = {}
    for a in atos:
        for alvo in a.get("cancela") or []:
            cancelado_por[normalizar_ato(alvo)] = normalizar_ato(a.get("numero"))
    quebras = {q.get("numero"): q.get("motivo") for q in derivados.get("quebras_cadeia") or []}
    out, anterior = [], None
    for i, a in enumerate(atos):
        num = normalizar_ato(a.get("numero")) or f"ATO-{i + 1}"
        transmissao = a.get("natureza") in TRANSMISSAO
        out.append(
            {
                **base,
                "ordem": i,
                "ato_numero": num,
                "ato_tipo": a.get("tipo"),
                "natureza": a.get("natureza"),
                "afeta": a.get("afeta"),
                "data": a.get("data"),
                "fracao_pct": a.get("fracao_pct"),
                "pagina": a.get("pagina"),
                "transmissao": transmissao,
                "anterior_numero": anterior if transmissao else None,
                "cancelado_por": cancelado_por.get(num),
                "quebra": num in quebras,
                "quebra_motivo": quebras.get(num),
                "resumo": mascarar(a.get("resumo")) if a.get("resumo") else None,
                "transmitentes_json": json.dumps(
                    [_parte(partes, r) for r in a.get("transmitentes") or []], ensure_ascii=False
                ),
                "adquirentes_json": json.dumps(
                    [_parte(partes, r) for r in a.get("adquirentes") or []], ensure_ascii=False
                ),
            }
        )
        if transmissao or a.get("natureza") == "abertura":
            anterior = num
    return out


def cadeia_das_conferencias(vigentes: list[dict]) -> pd.DataFrame:
    """vigentes: conferências vigentes do armazém (com dados_json, derivados_json e registro_hash da leitura). Cada
    leitura entra uma vez, mesmo quando a matrícula cobre mais de um imóvel."""
    linhas, vistas = [], set()
    for c in vigentes:
        h = c.get("registro_hash")
        if h in vistas:
            continue
        vistas.add(h)
        meta = dict(
            leitura_hash=h,
            leitura_id=c.get("leitura_id"),
            lido_em=c.get("lido_em"),
            modelo=c.get("modelo"),
            leitor_versao=f"{c.get('leitor_versao')}+{c.get('prompt_versao')}",
            regras_versao=c.get("regras_versao"),
            conferencia=c.get("situacao"),
        )
        linhas += linhas_da_leitura(json.loads(c["dados_json"] or "{}"), json.loads(c["derivados_json"] or "{}"), meta)
    return pd.DataFrame(linhas, columns=COLUNAS)
