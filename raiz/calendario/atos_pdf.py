"""Limites conservadores de atos em diários oficiais, usados somente em memória."""

from __future__ import annotations

import re

# Cada título de ato encerra o anterior, inclusive quando o ato seguinte não
# interessa ao calendário. Isso impede atribuir seu CAR a um leilão anterior.
_TITULO = re.compile(
    r"(?im)^[ \t]*(?=(?:EDITAL|AVISO|EXTRATO|PORTARIA|RESOLU[ÇC][ÃA]O|DECRETO|"
    r"CONTRATO|TERMO|ATA|NOTIFICA[ÇC][ÃA]O|COMUNICADO|RETIFICA[ÇC][ÃA]O|ERRATA|LICEN[ÇC]A)\b)"
)
_PROTOCOLO = re.compile(r"(?im)^[ \t]*Protocolo\s*:\s*\d{4,12}\s*$")


def diario(fonte: dict) -> bool:
    return (
        fonte["id"] == "dou"
        or fonte["id"].startswith("doe_")
        or fonte.get("grupo") == "diario_estadual"
        or str(fonte.get("modo", "")).startswith("diario_")
    )


def blocos(texto: str, fonte: dict) -> tuple[list[str], bool]:
    """Não trata a edição inteira como anúncio se não reconhecer seus limites."""
    if not diario(fonte):
        partes = re.split(r"(?i)(?=\bEDITAL\s+DE\s+(?:LEIL[ÃA]O|HASTA|PENHORA))", texto)
        return [p for p in partes if p.strip()], True
    tem_protocolo = bool(_PROTOCOLO.search(texto))
    if not tem_protocolo and not _TITULO.search(texto):
        return [], False
    # IOEPA encerra cada publicação com seu protocolo. Nos demais PDFs, a página
    # também é fronteira conservadora: uma continuação pode ficar pendente, mas
    # não herda o CAR de um ato sem cabeçalho na página seguinte.
    trechos = _PROTOCOLO.split(texto) if tem_protocolo else texto.split("\f")
    saida = []
    for trecho in trechos:
        titulos = list(_TITULO.finditer(trecho))
        if not titulos:
            # Um protocolo delimita um ato mesmo quando seu título não está no
            # vocabulário acima; sem protocolo, conteúdo sem título é ambíguo.
            if tem_protocolo and trecho.strip():
                saida.append(trecho)
            continue
        for i, inicio in enumerate(titulos):
            fim = titulos[i + 1].start() if i + 1 < len(titulos) else len(trecho)
            saida.append(trecho[inicio.start() : fim])
    return saida, True
