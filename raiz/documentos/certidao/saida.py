"""Saídas por município, lidas pelo front e pelo back-end pelo nome das colunas (docs/colunas.md).

matricula_conferencia_<mun>.csv  uma linha por (imóvel, matrícula) do certidoes_<mun>.csv, com a última conferência;
matricula_<mun>.csv              uma linha por imóvel, com matricula_conferida (True quando todas as matrículas do
                                 imóvel foram lidas e conferidas; False quando alguma foi lida e não conferiu; vazio
                                 quando falta ler). O selo "Matrícula conferida" do front lê esta coluna.
Nada de nome ou CPF: só situação, motivos já limpos, áreas, contagens e versões.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from raiz.documentos import tabelas
from raiz.documentos.armazem import Armazem
from raiz.documentos.certidao.regras import normalizar_cns, normalizar_matricula

PIOR = ["cancelada", "divergente", "revisar", "a_conferir", "conferida"]

COLS_CONF = [
    "cod_imovel",
    "registro_cns",
    "registro_matricula",
    "ha_sobre_car",
    "situacao",
    "precisa_confirmar",
    "motivo",
    "area_matricula_ha",
    "onus_ativos",
    "onus_graves",
    "quebra_cadeia",
    "n_transmissoes",
    "matricula_destino",
    "leitura_id",
    "lido_em",
    "modelo",
    "leitor_versao",
    "regras_versao",
]


def _motivo(motivos_json: str) -> str:
    ordem = {"reprova": 0, "confirmar": 1, "info": 2}
    ms = sorted(json.loads(motivos_json or "[]"), key=lambda m: ordem.get(m["gravidade"], 3))
    return "; ".join(m["texto"] for m in ms[:3])


def conferencias_do_municipio(cod_municipio: int, armazem: Armazem | None = None) -> pd.DataFrame:
    armazem = armazem or Armazem()
    motor = tabelas.ler("certidoes", cod_municipio)
    if motor is None:
        raise FileNotFoundError(f"certidoes_{cod_municipio}.csv não encontrado nas pastas de entrada")
    vig = armazem.conferencias_vigentes(list(motor.cod_imovel.unique()))
    por_chave = {
        (c["cod_imovel"], normalizar_cns(c["registro_cns"]), normalizar_matricula(c["registro_matricula"])): c
        for c in vig
    }
    linhas = []
    for _, r in motor.iterrows():
        k = (r.cod_imovel, normalizar_cns(r.registro_cns), normalizar_matricula(r.registro_matricula))
        c = por_chave.get(k)
        base = dict(
            cod_imovel=r.cod_imovel,
            registro_cns=r.registro_cns,
            registro_matricula=r.registro_matricula,
            ha_sobre_car=r.get("ha_sobre_car"),
        )
        if c is None:
            linhas.append({**base, "situacao": "a_conferir"})
            continue
        der = json.loads(c["derivados_json"] or "{}")
        linhas.append(
            {
                **base,
                "situacao": c["situacao"],
                "precisa_confirmar": bool(c["precisa_confirmar"]),
                "motivo": _motivo(c["motivos_json"]),
                "area_matricula_ha": der.get("area_ha"),
                "onus_ativos": len(der.get("onus_ativos") or []),
                "onus_graves": bool(der.get("onus_graves")),
                "quebra_cadeia": bool(der.get("quebras_cadeia")),
                "n_transmissoes": der.get("n_transmissoes"),
                "matricula_destino": der.get("matricula_destino"),
                "leitura_id": c["leitura_id"],
                "lido_em": c["lido_em"],
                "modelo": c["modelo"],
                "leitor_versao": f"{c['leitor_versao']}+{c['prompt_versao']}",
                "regras_versao": c["regras_versao"],
            }
        )
    return pd.DataFrame(linhas, columns=COLS_CONF)


def por_imovel(conf: pd.DataFrame) -> pd.DataFrame:
    linhas = []
    for cod, g in conf.groupby("cod_imovel", sort=True):
        sits = list(g.situacao)
        lidas = g[g.situacao != "a_conferir"]
        pior = next(s for s in PIOR if s in sits)
        if all(s == "conferida" for s in sits):
            conferida = True
        elif any(s in ("cancelada", "divergente", "revisar") for s in sits):
            conferida = False
        else:  # falta ler alguma matrícula do imóvel
            conferida = None
        linhas.append(
            dict(
                cod_imovel=cod,
                matricula_conferida=conferida,
                matricula_situacao=pior,
                matriculas_total=len(g),
                matriculas_lidas=len(lidas),
                matriculas_conferidas=int((g.situacao == "conferida").sum()),
                matricula_area_ha=round(float(lidas.area_matricula_ha.fillna(0).sum()), 2) if len(lidas) else None,
                matricula_onus_ativos=int(lidas.onus_ativos.fillna(0).sum()) if len(lidas) else None,
                matricula_onus_graves=bool(lidas.onus_graves.fillna(False).astype(bool).any()) if len(lidas) else None,
                matricula_quebra_cadeia=bool(lidas.quebra_cadeia.fillna(False).astype(bool).any())
                if len(lidas)
                else None,
                matricula_precisa_confirmar=bool(lidas.precisa_confirmar.fillna(False).astype(bool).any())
                if len(lidas)
                else None,
                matricula_motivo="; ".join(m for m in lidas.motivo.dropna() if m)[:400] or None,
                matricula_lido_em=lidas.lido_em.max() if len(lidas) else None,
                matricula_modelo=",".join(sorted(set(lidas.modelo.dropna()))) or None,
                matricula_leitor_versao=",".join(sorted(set(lidas.leitor_versao.dropna()))) or None,
            )
        )
    return pd.DataFrame(linhas)


def gravar_municipio(cod_municipio: int, armazem: Armazem | None = None) -> tuple[Path, Path]:
    conf = conferencias_do_municipio(cod_municipio, armazem)
    pasta = tabelas.pasta_saida(cod_municipio)
    a = pasta / f"matricula_conferencia_{cod_municipio}.csv"
    b = pasta / f"matricula_{cod_municipio}.csv"
    conf.to_csv(a, index=False)
    por_imovel(conf).to_csv(b, index=False)
    return a, b
