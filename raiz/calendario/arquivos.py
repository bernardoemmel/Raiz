"""Snapshot público e estado portátil da coleta. Nenhuma página bruta é gravada."""

from __future__ import annotations

import json
from pathlib import Path

import requests

from raiz.calendario.catalogo import COBERTURA_ID, COBERTURA_NOME
from raiz.calendario.coleta import _permitida, fontes
from raiz.calendario.feed import ics
from raiz.calendario.modelos import Evento, FonteEstado, filtrar
from raiz.privacidade import mascarar

ESTADO_PUBLICO = "https://github.com/bernardoemmel/Raiz/releases/download/calendario/estado.json"
MAX_ESTADO = 32 * 1024 * 1024


def recuperar_publico(caminho: Path) -> int:
    """Recupera o histórico já publicado; falha nunca autoriza começar uma agenda vazia."""
    try:
        with requests.get(ESTADO_PUBLICO, timeout=(10, 30), stream=True) as resposta:
            resposta.raise_for_status()
            partes, tamanho = [], 0
            for parte in resposta.iter_content(65536):
                tamanho += len(parte)
                if tamanho > MAX_ESTADO:
                    raise ValueError
                partes.append(parte)
        bruto = b"".join(partes).decode("utf-8")
        if mascarar(bruto) != bruto:
            raise ValueError
        dados = json.loads(bruto)
        decodificado = json.dumps(dados, ensure_ascii=False)
        if mascarar(decodificado) != decodificado:
            raise ValueError
        if (
            not isinstance(dados, dict)
            or not isinstance(dados.get("eventos"), list)
            or not isinstance(dados.get("fontes"), list)
            or type(dados.get("total")) is not int
            or dados["total"] != len(dados["eventos"])
        ):
            raise ValueError
        eventos, estados = validar(dados)
        if len({e.id for e in eventos}) != len(eventos):
            raise ValueError
        # Regrava somente os modelos validados: extras e nomes remotos não são transportados.
        estado = envelope(eventos, estados, limite=len(eventos) or 1)
        estado["eventos"] = [e.model_dump(mode="json") for e in eventos]
        caminho.parent.mkdir(parents=True, exist_ok=True)
        temporario = caminho.with_suffix(caminho.suffix + ".tmp")
        temporario.write_text(json.dumps(estado, ensure_ascii=False) + "\n", encoding="utf-8")
        temporario.replace(caminho)
        return len(eventos)
    except (OSError, ValueError, requests.RequestException):
        raise ValueError("não foi possível recuperar e validar o histórico público do calendário") from None


class ErroSnapshot(ValueError):
    """Diagnóstico publicável: nunca inclui valores, bytes ou caminho da entrada."""


def ler(caminho: Path) -> tuple[list[Evento], list[FonteEstado]]:
    try:
        return validar(json.loads(caminho.read_text(encoding="utf-8")))
    except ErroSnapshot:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OSError):
        # O CLI nunca publica os bytes, valores pessoais ou caminho da entrada inválida.
        raise ErroSnapshot("snapshot do calendário inválido; conteúdo omitido") from None


def validar(dados: dict) -> tuple[list[Evento], list[FonteEstado]]:
    """Valida arquivo ou resposta sem expor valores da entrada nos diagnósticos."""
    try:
        return _validar(dados)
    except ErroSnapshot:
        raise
    except (ValueError, TypeError, KeyError, AttributeError):
        # ValidationError do Pydantic contém input_value; não propagá-lo à API nem aos logs.
        raise ErroSnapshot("snapshot do calendário inválido; conteúdo omitido") from None


def _validar(dados: dict) -> tuple[list[Evento], list[FonteEstado]]:
    if not isinstance(dados, dict) or any(not isinstance(dados.get(c), list) for c in ("eventos", "fontes")):
        raise ErroSnapshot("snapshot do calendário inválido; conteúdo omitido")
    confiaveis = {f["id"]: f for f in fontes()}
    eventos = []
    for item in dados.get("eventos", []):
        e = Evento.model_validate(item)
        f = confiaveis.get(e.fonte_id)
        if f is None or not _permitida(e.fonte_url, f):
            raise ErroSnapshot("snapshot contém fonte fora do manifesto")
        if e.car_fonte_url and not _permitida(e.car_fonte_url, f):
            raise ErroSnapshot("snapshot contém documento do CAR fora do manifesto")
        # Nomes e textos de erro não vêm do arquivo remoto. Só rótulos institucionais
        # revisados no manifesto e mensagens fixas são publicados/importados.
        eventos.append(e.model_copy(update={"fonte_nome": f["nome"]}))
    estados = []
    confiaveis[COBERTURA_ID] = {"nome": COBERTURA_NOME}
    for item in dados.get("fontes", []):
        s = FonteEstado.model_validate(item)
        if s.id not in confiaveis:
            raise ErroSnapshot("snapshot contém fonte desconhecida")
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
