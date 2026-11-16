"""Lê o fechamento repetido legado sem reescrever o retrato nem sua identidade.

GEOS pode retirar só uma repetição do fechamento a cada ``normalize``. A escrita
legada normaliza uma vez; a validação normaliza outra. Esta compatibilidade só
admite essa diferença exata, preservando os bytes e a proveniência originais.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import tempfile
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon

from raiz.aprendizado.arquivo_historico import _normalizar
from raiz.aprendizado.reexecucao import FONTES, HistoricoInsuficiente
from raiz.aprendizado.retratos import MAX_COMPRIMIDO, MAX_DESCOMPRIMIDO, canonico, descomprimir, quadros
from raiz.aprendizado.retratos import validar_retrato as _validar_estrito

ERRO_CANONICO = "retrato fora do contrato público canônico"


def _exigir(condicao: bool) -> None:
    if not condicao:
        raise HistoricoInsuficiente(f"{ERRO_CANONICO}: fechamento legado incompatível")


def _fechamento(geom):
    """Retira apenas cópias finais do primeiro vértice, sem tolerância ou reparo."""
    if geom.has_z or geom.has_m:
        return geom, 0  # não ampliar o caso comprovado em geometrias 2D
    if isinstance(geom, MultiPolygon):
        partes = [_fechamento(p) for p in geom.geoms]
        removidos = sum(n for _, n in partes)
        return (MultiPolygon([p for p, _ in partes]) if removidos else geom), removidos
    if not isinstance(geom, Polygon):
        return geom, 0
    aneis, removidos = [], 0
    for anel in (geom.exterior, *geom.interiors):
        coords = list(anel.coords)
        while len(coords) > 4 and coords[-2] == coords[0]:
            coords.pop()
            removidos += 1
        aneis.append(coords)
    return (Polygon(aneis[0], aneis[1:]) if removidos else geom), removidos


def _dados_compativeis(obj: dict) -> dict:
    frames = quadros(obj["dados"])
    esperadas, removidos = {}, 0
    for nome, df in frames.items():
        originais = obj["dados"][nome]
        _exigir(originais == sorted(originais, key=lambda r: r["_chave"]))
        esp = FONTES[nome]
        for li in originais:
            dados = {k: v for k, v in li.items() if k not in ("_chave", "_linha_hash")}
            digest = hashlib.sha256(json.dumps(dados, sort_keys=True, allow_nan=False).encode()).hexdigest()
            _exigir(li["_linha_hash"] == digest)
            _exigir(li["_chave"] == str(dados[esp.chave] if esp.chave else digest))
        if not esp.geometria:
            continue
        geometrias, wkts = [], []
        for li, geom in zip(originais, df.geometry, strict=True):
            _exigir(geom.wkt == li["geom"])
            nova, quantidade = _fechamento(geom)
            removidos += quantidade
            geometrias.append(nova)
            wkts.append(nova.wkt)
        df.geometry = geometrias
        esperadas[nome] = wkts
    _exigir(removidos > 0)
    normalizado = _normalizar(frames, exigir_completo=False)
    for nome, novas in normalizado.items():
        for i, (original, nova) in enumerate(zip(obj["dados"][nome], novas, strict=True)):
            # Nem texto livre, nem atributos/contexto, nem números/tipos podem
            # aproveitar a exceção geométrica para passar pela sanitização.
            excluir = {"_chave", "_linha_hash", "geom"} if FONTES[nome].geometria else set()
            _exigir(
                canonico({k: v for k, v in original.items() if k not in excluir})
                == canonico({k: v for k, v in nova.items() if k not in excluir})
            )
            if FONTES[nome].geometria:
                # Igualdade exata da sequência restante, não mera equivalência
                # topológica. Outra ordem, vértice ou orientação é rejeitada.
                _exigir(nova["geom"] == esperadas[nome][i])
                if FONTES[nome].chave:
                    _exigir(nova["_chave"] == original["_chave"])
    return {n: sorted(rs, key=lambda r: r["_chave"]) for n, rs in normalizado.items()}


def validar_retrato(caminho: Path) -> dict:
    """Valida estritamente e retorna sempre o objeto original, sem migração."""
    try:
        return _validar_estrito(caminho)
    except HistoricoInsuficiente as erro:
        if str(erro) != ERRO_CANONICO:
            raise
    # Conferir novamente os bytes lidos evita depender da primeira leitura se
    # o arquivo tiver sido trocado. A cópia passa pelas mesmas guardas completas.
    _exigir(caminho.stat().st_size <= MAX_COMPRIMIDO)
    bruto = descomprimir(caminho.read_bytes(), MAX_DESCOMPRIMIDO)
    _exigir(caminho.name == f"{hashlib.sha256(bruto).hexdigest()}.json.gz")
    obj = json.loads(bruto)
    _exigir(canonico(obj) == bruto)
    copia = canonico({**obj, "dados": _dados_compativeis(obj)})
    with tempfile.TemporaryDirectory(prefix="raiz-valida-legado-") as tmp:
        temporario = Path(tmp) / f"{hashlib.sha256(copia).hexdigest()}.json.gz"
        temporario.write_bytes(gzip.compress(copia, mtime=0))
        _validar_estrito(temporario)
    return obj
