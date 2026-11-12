"""Seleciona diários pela cobertura pública real; não lê nem revela camadas pagas."""

from __future__ import annotations

import json
from pathlib import Path

import requests

from raiz.calendario.modelos import UFS

MANIFESTO_PUBLICO = "https://github.com/bernardoemmel/Raiz/releases/download/dados/estados.json"
MAX_MANIFESTO = 2 * 1024 * 1024


def carregar_manifesto(caminho: Path | None = None) -> dict:
    """Só a cobertura básica. Falha de leitura não vira cobertura nacional presumida."""
    try:
        if caminho is not None:
            if caminho.stat().st_size > MAX_MANIFESTO:
                raise ValueError
            bruto = caminho.read_bytes()
        else:
            with requests.get(MANIFESTO_PUBLICO, timeout=(10, 30), stream=True) as resposta:
                resposta.raise_for_status()
                partes, tamanho = [], 0
                for parte in resposta.iter_content(65536):
                    tamanho += len(parte)
                    if tamanho > MAX_MANIFESTO:
                        raise ValueError
                    partes.append(parte)
                bruto = b"".join(partes)
        manifesto = json.loads(bruto)
        estados_processados(manifesto)
        return manifesto
    except (OSError, ValueError, requests.RequestException) as ex:
        raise ValueError("não foi possível conferir o manifesto público dos estados processados") from ex


def estados_processados(manifesto: dict) -> set[str]:
    """UF anunciada com zero municípios ainda não está processada; parcial também conta."""
    if not isinstance(manifesto, dict) or manifesto.get("escopo") != "publico_basico":
        raise ValueError("o calendário exige o manifesto público básico")
    estados = manifesto.get("estados")
    if not isinstance(estados, dict):
        raise ValueError("cobertura de estados inválida")
    processados = set()
    for uf, dados in estados.items():
        if uf not in UFS or not isinstance(dados, dict):
            raise ValueError("cobertura de estados inválida")
        numero = dados.get("municipios")
        if isinstance(numero, bool) or not isinstance(numero, int) or numero < 0:
            raise ValueError("contagem de municípios inválida")
        if numero:
            processados.add(uf)
    return processados


def selecionar(fontes: list[dict], manifesto: dict) -> list[dict]:
    """Mantém fontes nacionais e todos os diários das UFs já processadas, sem piso de cobertura."""
    ufs = estados_processados(manifesto)
    diarios = {f.get("uf") for f in fontes if f.get("grupo") == "diario_estadual"}
    if ufs - diarios:
        # A UF nova não pode desaparecer da cobertura silenciosamente.
        raise ValueError("há estado processado sem diário no catálogo: " + ", ".join(sorted(ufs - diarios)))
    selecionadas = []
    for fonte in fontes:
        if fonte.get("grupo") == "diario_estadual" and fonte.get("uf") not in ufs:
            continue
        if fonte.get("grupo") == "leilao_regional" and not ufs.intersection(fonte.get("ufs", [])):
            continue
        selecionadas.append({**fonte, "_ufs_processadas": sorted(ufs)})
    return selecionadas
