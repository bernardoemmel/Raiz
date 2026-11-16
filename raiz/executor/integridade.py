"""Identidade da partição municipal, depois de conferir seus bytes e versões.

O selo não substitui a conferência das saídas nem afirma validade científica de
uma geometria. Uma marca incompleta ou um selo antigo nunca autoriza pular trabalho.
"""

from __future__ import annotations

import hashlib
import json


def identidade(uf: str, cod: int, tarefas: list, marca: dict) -> dict:
    ativas, dispensadas = {}, []
    for tarefa in tarefas:
        if any((marca["tarefas"].get(d) or {}).get("vazio") for d in tarefa.depende):
            dispensadas.append(tarefa.nome)
            continue
        feita = marca["tarefas"].get(tarefa.nome) or {}
        ativas[tarefa.nome] = {k: feita.get(k) for k in ("versao", "assinatura", "saidas", "vazio")}
    prova = {"formato": 1, "uf": uf, "municipio": int(cod), "tarefas": ativas, "dispensadas": dispensadas}
    bruto = json.dumps(prova, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    return {"formato": 1, "situacao": "integro", "sha256": hashlib.sha256(bruto).hexdigest(),
            "tarefas": sorted(ativas), "dispensadas": dispensadas}  # fmt: skip
