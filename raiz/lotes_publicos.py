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

from raiz.privacidade import documento_em_identificador

OPCOES = ("barata", "segura", "compacta")
CAMINHOS = ("matricula_conferida", "matricula_a_conferir", "concessao", "assentamento", "posse_em_titulacao")
NOME_PUBLICO = "lote_PA_central_r11.json"
NOME_NACIONAL = "lote_nacional_resumo.json"
PONTEIRO = "lote_nacional_atual.json"
UFS = tuple("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())
BIOMAS = ("Amazônia", "Caatinga", "Cerrado", "Mata Atlântica", "Pampa", "Pantanal")
SITUACOES_SOBREPOSICAO = ("nao_verificada", "verificada")
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
    if (
        not isinstance(modelo, str)
        or not re.fullmatch(r"[A-Za-z0-9_.+-]{1,100}", modelo)
        or documento_em_identificador(modelo)
    ):
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


def _situacao(valor) -> str:
    """Sobreposição só vira "verificada" quando o catálogo disse isso; qualquer outra coisa é "não verificada"."""
    return valor if valor in SITUACOES_SOBREPOSICAO else "nao_verificada"


def _opcao_nacional(r: dict) -> dict:
    n = _numero(r.get("fazendas"), inteiro=True)
    suficiente = n is not None and n >= 5  # a mesma supressão do resumo do PA: grupo com menos de 5 não mostra medida
    fecha = r.get("fecha_meta")
    return {
        "fazendas": n,
        "pequenas": _numero(r.get("pequenas"), inteiro=True) if suficiente else None,
        "hectares": _numero(r.get("hectares")) if suficiente else None,
        "creditos": _faixa(r.get("creditos")) if suficiente else None,
        "fecha_meta": fecha if isinstance(fecha, bool) and suficiente else None,
        "sobreposicao": _situacao(r.get("sobreposicao")),
    }


def _espera_nacional(e: dict) -> dict:
    n = _numero(e.get("fazendas"), inteiro=True)
    suficiente = n is not None and n >= 5
    return {
        "incluida_no_pedido": e.get("incluida_no_pedido") if isinstance(e.get("incluida_no_pedido"), bool) else None,
        "fazendas": n,
        "pequenas": _numero(e.get("pequenas"), inteiro=True) if suficiente else None,
        "hectares": _numero(e.get("hectares")) if suficiente else None,
        "creditos_p50": _numero(e.get("soma_creditos_p50")) if suficiente else None,
        # a terra em espera nunca vende: precisa de título, concessão ou regularização antes
        "habilita_venda": False,
    }


def projetar_nacional(ponteiro: dict, publicado_em: str) -> dict:
    """Resumo por UF, bioma e Brasil do ponteiro do lote nacional, sem fazenda, CAR, caminho nem pacote.

    Lista positiva: só entram as três opções (contagens e medidas), a terra em espera separada da pronta e a situação
    da sobreposição. Recorte que não é UF, bioma nem Brasil é ignorado. Grupos com menos de 5 fazendas escondem as
    medidas, como no resumo do PA.
    """
    if ponteiro.get("acesso") != "privado":
        raise ValueError("Ponteiro do lote nacional fora do contrato privado.")
    datetime.fromisoformat(publicado_em.replace("Z", "+00:00"))
    recortes = []
    for nome, item in (ponteiro.get("consultas") or {}).items():
        tipo = "uf" if nome in UFS else "bioma" if nome in BIOMAS else "brasil" if nome == "Brasil" else None
        resumo = (item or {}).get("resumo") if isinstance(item, dict) else None
        if tipo is None or not isinstance(resumo, dict):
            continue
        ops = resumo.get("opcoes") or {}
        if set(ops) != set(OPCOES):
            continue
        opcoes = {o: _opcao_nacional(ops[o]) for o in OPCOES}
        recortes.append(
            {
                "nome": nome,
                "tipo": tipo,
                "opcoes": opcoes,
                "terra_em_espera": _espera_nacional(resumo.get("terra_em_espera") or {}),
                "sobreposicao": _situacao(resumo.get("sobreposicao")),
                "vazio": all(not (o["fazendas"] or 0) for o in opcoes.values()),
            }
        )
    ordem = {"brasil": 0, "bioma": 1, "uf": 2}
    recortes.sort(key=lambda r: (ordem[r["tipo"]], r["nome"]))
    return {
        "contrato": "publico_lotes_nacional",
        "versao": 1,
        "estado": "publicado" if recortes else "ausente",
        "atualizado_em": publicado_em,
        "aviso": "Resumo por recorte do lote nacional. Pronta é a terra que cumpre o pedido em tudo; em espera é a que "
        'cumpre tudo menos o caminho da terra e não habilita venda. Sobreposição "não verificada" significa que a '
        "camada de terra já comprometida ainda não foi cruzada: ausência de indício não é terra livre.",
        "recortes": recortes,
    }


def baixar_nacional(arm) -> dict:
    """Lê o ponteiro privado (visibilidade reconferida pelo armazém) e projeta o resumo público."""
    from datetime import UTC

    arm._exigir_privado()
    dados = arm._baixar_asset(PONTEIRO, fresco=True)
    agora = datetime.now(UTC).isoformat(timespec="seconds")
    if not dados:
        return {
            "contrato": "publico_lotes_nacional",
            "versao": 1,
            "estado": "ausente",
            "atualizado_em": agora,
            "recortes": [],
        }
    if len(dados) > 50_000_000:
        raise ValueError("Ponteiro do lote nacional excede o limite de tamanho.")
    return projetar_nacional(json.loads(dados), agora)


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
    # O resumo nacional nunca derruba a publicação do site: sem ponteiro ou com erro, o arquivo sai "ausente".
    arm = arquivo_privado()
    try:
        nacional = baixar_nacional(arm)
    except Exception as erro:  # noqa: BLE001
        print(f"Resumo nacional dos lotes indisponível ({type(erro).__name__}); publicado como ausente.")
        nacional = {
            "contrato": "publico_lotes_nacional",
            "versao": 1,
            "estado": "ausente",
            "atualizado_em": resultado.get("atualizado_em")
            or datetime.now().astimezone().isoformat(timespec="seconds"),
            "recortes": [],
        }
    alvo = args.destino.with_name(NOME_NACIONAL)
    temporario = alvo.with_suffix(".tmp")
    temporario.write_text(json.dumps(nacional, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporario.replace(alvo)
    print(f"Resumo nacional dos lotes: {nacional['estado']}, {len(nacional['recortes'])} recortes.")


if __name__ == "__main__":
    main()
