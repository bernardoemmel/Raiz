"""Nota de risco de título (1 a 5) com bandeiras e decisão em quatro saídas: aceitar, aceitar com condições, análise
humana ou recusar. Regra em raiz/regras/padroes/nota_titulo.yaml.

Entradas por imóvel, pelo nome das colunas: caminho_terra e risco_terra (terra_<mun>.csv), regularizacao_classe
(regularizacao_<mun>.csv), matricula_situacao e matricula_onus_graves (matricula_<mun>.csv) e os achados do imóvel
(achados_<mun>.csv; com o banco, os confirmados ou descartados por gente não contam).
"""

from __future__ import annotations

import hashlib
import math
from functools import lru_cache
from pathlib import Path

import yaml

ARQ = Path(__file__).resolve().parents[1] / "regras" / "padroes" / "nota_titulo.yaml"
DECISOES = ("aceitar", "aceitar_com_condicoes", "analise_humana", "recusar")


@lru_cache
def _ler(arq: Path, _marca: tuple) -> dict:
    texto = arq.read_bytes()
    r = yaml.safe_load(texto)
    r["versao_completa"] = f"{r['versao']}+{hashlib.sha256(texto).hexdigest()[:8]}"
    return r


def regra(arq: Path | None = None) -> dict:
    a = Path(arq or ARQ)
    return _ler(a, (str(a), a.stat().st_mtime_ns, a.stat().st_size))


def versao() -> str:
    return regra()["versao_completa"]


def _s(v) -> str | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return str(v)


def _verdade(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "sim", "t")
    return bool(v) and not (isinstance(v, float) and math.isnan(v))


def nota_do_imovel(linha: dict, achados: list[dict], r: dict | None = None) -> dict:
    """achados: dicionários com fase, regra, situacao, gravidade, mensagem, valor (e confirmacao_decisao, se veio
    do banco)."""
    r = r or regra()
    B, S = r["base"], r["soma"]
    cam = _s(linha.get("caminho_terra")) or "sem_caminho"
    risco = _s(linha.get("risco_terra")) or "alto"
    classe = _s(linha.get("regularizacao_classe"))
    b = B.get(cam, B["sem_caminho"])
    if isinstance(b, dict):
        b = b.get(classe if cam in ("posse_em_titulacao", "assentamento") else risco, max(b.values()))
    nota = int(b)
    bandeiras, motivos = [], []
    if nota >= 4:
        motivos.append(f"terra em {cam.replace('_', ' ')}" + (f" ({classe.replace('_', ' ')})" if classe else ""))
    abertos = [a for a in achados if not _s(a.get("confirmacao_decisao"))]
    # a regularização da posse já entra pela classe na base: os achados dela viram bandeira, não somam de novo
    fases_reprova = sorted(
        {a["fase"] for a in abertos if a.get("gravidade") == "reprova" and a["fase"] != "regularizacao"}
    )
    nota += min(len(fases_reprova) * S["por_fase_reprovada"], S["max_reprova"])
    for a in abertos:
        if a.get("gravidade") == "reprova":
            bandeiras.append(str(a.get("mensagem") or a.get("regra")).rstrip("."))
    geo = [str(a.get("valor")) for a in achados if str(a.get("regra", "")).startswith("geometria.")]
    for d, extra in S["geometria"].items():
        if d in geo:
            nota += extra
            bandeiras.append(f"CAR e SIGEF divergem ({d})")
            break
    if _verdade(linha.get("matricula_onus_graves")):
        nota += S["onus_grave"]
        bandeiras.append("ônus grave na matrícula")
    sit = _s(linha.get("matricula_situacao"))
    if sit == "cancelada":
        nota = max(nota, S["piso_matricula_cancelada"])
        motivos.append("matrícula cancelada")
    elif sit in ("divergente", "revisar"):
        nota = max(nota, S["piso_matricula_divergente"])
        motivos.append(f"certidão {sit}")
    nota = max(1, min(5, nota))
    condicoes = [str(a.get("mensagem")).rstrip(".") for a in abertos if a.get("gravidade") == "confirmar"]
    if risco != "baixo" and _s(linha.get("risco_terra_motivo")):  # ex.: matrícula ainda não conferida no cartório
        condicoes.insert(0, str(linha["risco_terra_motivo"]).rstrip("."))
    D = r["decisao"]
    if nota >= D["recusar"]["nota_min"]:
        dec = "recusar"
    elif nota >= D["analise_humana"]["nota_min"]:
        dec = "analise_humana"
    elif nota <= D["aceitar"]["nota_max"] and not fases_reprova and not condicoes:
        dec = "aceitar"
    elif nota <= D["aceitar_com_condicoes"]["nota_max"] and not fases_reprova:
        dec = "aceitar_com_condicoes"
    else:
        dec = "analise_humana"
    mot = "; ".join((motivos + bandeiras)[:4]) or "achados que reprovam"
    texto = r["textos"][dec].format(condicoes="; ".join(condicoes[:4]) or "conferir os achados", motivos=mot)
    return {
        "cod_imovel": linha.get("cod_imovel"),
        "titulo_nota": nota,
        "titulo_decisao": dec,
        "titulo_decisao_texto": texto,
        "titulo_bandeiras": "; ".join(dict.fromkeys(bandeiras))[:500] or None,
        "titulo_condicoes": "; ".join(condicoes[:6])[:500] or None,
        "titulo_reprova": len([a for a in abertos if a.get("gravidade") == "reprova"]),
        "titulo_confirmar": len(condicoes),
        "titulo_nota_versao": r["versao_completa"],
    }
