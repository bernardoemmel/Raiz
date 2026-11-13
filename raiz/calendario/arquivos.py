"""Snapshot público e estado portátil da coleta. Nenhuma página bruta é gravada."""

from __future__ import annotations

import json
from pathlib import Path

from raiz.calendario.catalogo import COBERTURA_ID, COBERTURA_NOME
from raiz.calendario.coleta import _permitida, fontes
from raiz.calendario.feed import ics
from raiz.calendario.modelos import Evento, FonteEstado, filtrar


def ler(caminho: Path) -> tuple[list[Evento], list[FonteEstado]]:
    return validar(json.loads(caminho.read_text(encoding="utf-8")))


def validar(dados: dict) -> tuple[list[Evento], list[FonteEstado]]:
    """Valida dados de arquivo ou resposta, sem confiar em nomes/textos recebidos."""
    if not isinstance(dados, dict):
        raise ValueError("snapshot deve ser um objeto")
    confiaveis = {f["id"]: f for f in fontes()}
    eventos = []
    for item in dados.get("eventos", []):
        e = Evento.model_validate(item)
        f = confiaveis.get(e.fonte_id)
        if f is None or not _permitida(e.fonte_url, f):
            raise ValueError("snapshot contém fonte fora do manifesto")
        if e.car_fonte_url and not _permitida(e.car_fonte_url, f):
            raise ValueError("snapshot contém documento do CAR fora do manifesto")
        # Nomes e textos de erro não vêm do arquivo remoto. Só rótulos institucionais
        # revisados no manifesto e mensagens fixas são publicados/importados.
        eventos.append(e.model_copy(update={"fonte_nome": f["nome"]}))
    estados = []
    confiaveis[COBERTURA_ID] = {"nome": COBERTURA_NOME}
    for item in dados.get("fontes", []):
        s = FonteEstado.model_validate(item)
        if s.id not in confiaveis:
            raise ValueError("snapshot contém fonte desconhecida")
        estados.append(
            s.model_copy(
                update={
                    "nome": confiaveis[s.id]["nome"],
                    "erro": "Fonte com leitura incompleta; consulte a publicação oficial."
                    if s.situacao in ("erro", "parcial")
                    else None,
                }
            )
        )
    return eventos, estados


def envelope(eventos, estados, *, limite=100, deslocamento=0, **filtros) -> dict:
    selecionados = filtrar(eventos, **filtros)
    return {
        "eventos": [e.publico() for e in selecionados[deslocamento : deslocamento + limite]],
        "total": len(selecionados),
        "fontes": [s.model_dump(mode="json") for s in estados],
        "coletado_em": max((s.coletado_em.isoformat() for s in estados), default=None),
    }


def publicar(pasta: Path, eventos: list[Evento], estados: list[FonteEstado]) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    publico = envelope(eventos, estados, limite=len(eventos) or 1)
    estado = {**publico, "eventos": [e.model_dump(mode="json") for e in eventos]}
    for nome, dados in (("eventos.json", publico), ("estado.json", estado)):
        temp = pasta / (nome + ".tmp")
        temp.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(pasta / nome)
    (pasta / "eventos.ics").write_bytes(ics(eventos).encode())
