"""Sinal barato do PRODES pelo catálogo público de downloads do TerraBrasilis.

``created`` é a atualização do arquivo no catálogo, não a data do desmatamento.
A assinatura considera link, created e enabled, inclusive arquivos desabilitados.
Só a aceitação dos dados coletados deve avançar a assinatura em coleta.replicacao;
esta verificação apenas marca os datasets que precisam ser coletados.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests
from sqlalchemy import Connection, text

from raiz.coleta import replicacao

FONTE = "prodes"
URL_CATALOGO = "https://terrabrasilis.dpi.inpe.br/business/api/v1/download/all"
_DATASET = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*-prodes")
_CAMINHO = re.compile(r"/download/dataset/([^/]+)/.+")


@dataclass(frozen=True)
class ResultadoPRODES:
    dataset: str
    assinatura: str
    anterior: str | None
    mudou: bool
    sujo: bool
    arquivos: int
    removido: bool


def _agrupar(catalogo: object) -> dict[str, list[dict]]:
    """Valida o catálogo inteiro antes de interpretar ausência como remoção."""
    if not isinstance(catalogo, list):
        raise ValueError("catálogo PRODES deve ser uma lista de objetos")
    grupos: dict[str, list[dict]] = {}
    for indice, item in enumerate(catalogo):
        erro = f"item {indice} inválido no catálogo PRODES"
        if not isinstance(item, dict):
            raise ValueError(erro)
        link, created, enabled = (item.get(k) for k in ("link", "created", "enabled"))
        if not isinstance(link, str) or not link.strip():
            raise ValueError(f"{erro}: link ausente")
        if not isinstance(created, str) or not created.strip():
            raise ValueError(f"{erro}: created ausente")
        try:
            dt.datetime.fromisoformat(created)
        except ValueError as ex:
            raise ValueError(f"{erro}: created não é uma data ISO") from ex
        if not isinstance(enabled, bool):
            raise ValueError(f"{erro}: enabled deve ser booleano")
        try:
            caminho = urlsplit(link).path
        except ValueError as ex:
            raise ValueError(f"{erro}: link inválido") from ex
        trecho = _CAMINHO.fullmatch(caminho)
        if trecho is None:
            if "-prodes" in caminho:
                raise ValueError(f"{erro}: caminho do dataset PRODES inválido")
            continue
        dataset = trecho[1]
        if _DATASET.fullmatch(dataset):
            grupos.setdefault(dataset, []).append({"link": link, "created": created, "enabled": enabled})
    return grupos


def _hash(itens: list[dict]) -> str:
    # Traduções repetem o mesmo arquivo: a assinatura representa os ativos, não o idioma da página.
    unicos = sorted({(i["link"], i["created"], i["enabled"]) for i in itens})
    registros = [{"link": link, "created": created, "enabled": enabled} for link, created, enabled in unicos]
    bruto = json.dumps(registros, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(bruto).hexdigest()


def assinaturas(catalogo: object, anteriores: Iterable[str] = ()) -> dict[str, str]:
    """SHA-256 por dataset/bioma; datasets anteriores ausentes recebem o hash de [].

    ``anteriores`` são os nomes de datasets já conhecidos (ex.: ``amz-prodes``),
    necessários para detectar a remoção de todos os arquivos de um dataset.
    A ordem, o idioma e outros campos de apresentação não alteram a assinatura.
    """
    grupos = _agrupar(catalogo)
    for dataset in anteriores:
        if not isinstance(dataset, str) or not _DATASET.fullmatch(dataset):
            raise ValueError("dataset anterior PRODES inválido")
        grupos.setdefault(dataset, [])
    return {dataset: _hash(grupos[dataset]) for dataset in sorted(grupos)}


def ler_catalogo(s: requests.Session, *, timeout: float = 30, url: str = URL_CATALOGO) -> list[dict]:
    """Um GET pequeno, sem baixar os arquivos; falhas HTTP/JSON não viram catálogo vazio."""
    resposta = s.get(url, timeout=timeout)
    resposta.raise_for_status()
    catalogo = resposta.json()
    _agrupar(catalogo)
    return catalogo


def verificar(
    s: requests.Session, con: Connection, *, timeout: float = 30, url: str = URL_CATALOGO
) -> list[ResultadoPRODES]:
    """Compara com a versão aceita, marca sujo e registra mudanças por dataset.

    Não altera assinatura, cursor ou dados coletados. Um estado já sujo permanece
    sujo até a coleta aceitar os dados. O chamador controla a transação e deve ter
    sincronizado as fontes do manifesto. Erros de rede ou catálogo propagam antes
    de qualquer gravação, permitindo ao chamador registrar/alertar a falha.
    """
    catalogo = ler_catalogo(s, timeout=timeout, url=url)
    grupos = _agrupar(catalogo)
    estados = {
        e.recorte: e
        for e in con.execute(
            text("select recorte, assinatura, sujo from coleta.replicacao where fonte = :f"), {"f": FONTE}
        ).all()
        if _DATASET.fullmatch(e.recorte)
    }
    atuais = assinaturas(catalogo, estados)
    agora = dt.datetime.now(dt.UTC)
    resultados = []
    for dataset, assinatura in atuais.items():
        e = estados.get(dataset)
        anterior = e.assinatura if e is not None else None
        mudou = anterior != assinatura
        sujo = mudou or bool(e and e.sujo)
        arquivos = len({i["link"] for i in grupos.get(dataset, [])})
        removido = dataset not in grupos
        replicacao.atualizar(con, FONTE, dataset, sujo=sujo, verificado_em=agora)
        if mudou:
            replicacao.evento(
                con,
                FONTE,
                dataset,
                "mudaram",
                arquivos,
                {"assinatura": assinatura, "anterior": anterior, "removido": removido, "sinal": "catalogo"},
            )
        resultados.append(ResultadoPRODES(dataset, assinatura, anterior, mudou, sujo, arquivos, removido))
    return resultados
