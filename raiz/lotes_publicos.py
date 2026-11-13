"""Projeta o resumo comercial dos lotes, sem publicar sua composição ou diligência.

Lê apenas o manifesto autenticado. Os pacotes por fazenda nunca são baixados pelo
publicador do site, nem guardados em seu cache ou artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path

OPCOES = ("barata", "segura", "compacta")
CAMINHOS = ("matricula_conferida", "matricula_a_conferir", "concessao", "assentamento", "posse_em_titulacao")
NOME_PUBLICO = "lote_PA_central_r11.json"
PADRAO_MANIFESTO = re.compile(r"lote_PA_central_r11_(?:retomada_)?[0-9]+_[0-9]+(?:_[a-f0-9]{16})?\.json")


def _numero(valor, *, inteiro: bool = False):
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor) or valor < 0:
        return None
    return None if inteiro and int(valor) != valor else valor


def _faixa(valor):
    if not isinstance(valor, dict):
        return None
    pontos = [_numero(valor.get(p)) for p in ("p10", "p50", "p90")]
    if any(v is None for v in pontos) or not pontos[0] <= pontos[1] <= pontos[2]:
        return None
    return dict(zip(("p10", "p50", "p90"), pontos, strict=True))


def _terra_pronta(resumo: dict, fazendas: int | None, creditos: dict | None, meta: float | None) -> dict:
    """Terra documentada no lote, nunca a oferta estadual chamada 'pronta' pelo solver.

    O solver também admite matrícula a conferir. Essa classe NÃO comprova terra
    pronta. Quando há mistura, o manifesto ainda não informa os créditos do grupo
    documentado; a medida fica desconhecida, sem ratear por hectares ou fazendas.
    """
    por = resumo.get("certidoes", {}).get("por_caminho", {})
    contagens = {c: _numero(por.get(c, {}).get("fazendas"), inteiro=True) for c in CAMINHOS}
    pronto = None
    if fazendas is not None and all(n is not None for n in contagens.values()):
        if sum(contagens.values()) == fazendas:
            n = contagens["matricula_conferida"] + contagens["concessao"]
            if n == 0:
                pronto = 0
            elif n == fazendas and creditos:
                pronto = creditos["p50"]
    return {"creditos_p50": pronto, "fracao_meta": min(1, pronto / meta) if pronto is not None and meta else None}


def projetar(manifesto: dict, publicado_em: str) -> dict:
    """Lista positiva: nenhum texto livre, caminho, CAR, TIR ou trava sai da origem."""
    if manifesto.get("uf") != "PA" or manifesto.get("cenario") != "central_r11":
        raise ValueError("Manifesto fora do cenário revisado para publicação.")
    resumos = manifesto.get("resumos", {})
    if set(resumos) != set(OPCOES):
        raise ValueError("A publicação exige as três opções completas.")
    modelo = manifesto.get("modelo_versao")
    if not isinstance(modelo, str) or not re.fullmatch(r"[A-Za-z0-9_.+-]{1,100}", modelo):
        raise ValueError("Versão de modelo inválida.")
    datetime.fromisoformat(publicado_em.replace("Z", "+00:00"))
    metas = {_numero(resumos[o].get("volume_creditos")) for o in OPCOES}
    precos = {_numero(resumos[o].get("preco_contrato_usd")) for o in OPCOES}
    if len(metas) != 1 or len(precos) != 1 or None in metas or None in precos:
        raise ValueError("As opções não pertencem ao mesmo pedido publicado.")
    meta, preco = metas.pop(), precos.pop()
    opcoes = []
    for id_ in OPCOES:
        r = resumos[id_]
        titulares, reservas = (_numero(r.get(c), inteiro=True) for c in ("titulares", "reservas"))
        n = titulares + reservas if titulares is not None and reservas is not None else None
        # Pequenas fazendas continuam no lote; apenas medidas de grupos <5 são suprimidas.
        suficiente = n is not None and n >= 5
        fx = _faixa((r.get("faixa") or {}).get("carteira")) if suficiente else None
        opcoes.append(
            {
                "id": id_,
                "creditos": fx,
                "hectares": _numero(r.get("ha_lote")) if suficiente else None,
                "fazendas": n,
                "custo_usd_credito": _numero(r.get("custo_credito_usd_medio")) if suficiente else None,
                "terra_pronta": _terra_pronta(r, n, fx, meta)
                if suficiente
                else {"creditos_p50": None, "fracao_meta": None},
            }
        )
    return {
        "contrato": "publico_lotes",
        "versao": 1,
        "estado": "publicado",
        "atualizado_em": publicado_em,
        "cenario": "central_r11",
        "modelo_versao": modelo,
        "uf": "PA",
        "volume_creditos": meta,
        "preco_contrato_usd": preco,
        "cobertura": {
            "municipios": _numero(manifesto.get("municipios_calculados"), inteiro=True),
            "estados": 1,
            "fazendas": _numero(manifesto.get("imoveis_calculados"), inteiro=True),
            "hectares": None,
        },
        "opcoes": opcoes,
    }


def baixar_resumo(arm) -> dict:
    """Visibilidade reconferida pelo armazém antes de listar e de baixar o manifesto."""
    rel = arm._exigir_privado()
    ativos = [
        a for a in arm._assets(rel) if a.get("name") == NOME_PUBLICO or PADRAO_MANIFESTO.fullmatch(a.get("name", ""))
    ]
    if not ativos:
        return {"contrato": "publico_lotes", "versao": 1, "estado": "ausente"}
    ativo = max(ativos, key=lambda a: (a.get("updated_at", ""), a.get("id", 0)))
    if not isinstance(ativo.get("size"), int) or not 0 < ativo["size"] <= 2_000_000:
        raise ValueError("Manifesto privado excede o limite de tamanho.")
    dados = arm._baixar_ativo(ativo)
    if len(dados) != ativo["size"]:
        raise ValueError("Tamanho divergente no manifesto privado.")
    digest = hashlib.sha256(dados).hexdigest()
    nome_hash = re.search(r"_([a-f0-9]{16})\.json$", ativo["name"])
    if nome_hash and not digest.startswith(nome_hash[1]):
        raise ValueError("SHA-256 divergente no manifesto privado.")
    if ativo.get("digest") and ativo["digest"] != f"sha256:{digest}":
        raise ValueError("Digest divergente no manifesto privado.")
    return projetar(json.loads(dados), ativo["updated_at"])


def main():
    from raiz.executor.transferencia_privada import arquivo_privado

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destino", type=Path, default=Path("dados/lotes-publicos") / NOME_PUBLICO)
    args = parser.parse_args()
    resultado = baixar_resumo(arquivo_privado())
    args.destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = args.destino.with_suffix(".tmp")
    temporario.write_text(json.dumps(resultado, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporario.replace(args.destino)
    print(f"Resumo público dos lotes: {resultado['estado']}; nenhum pacote individual foi baixado.")


if __name__ == "__main__":
    main()
