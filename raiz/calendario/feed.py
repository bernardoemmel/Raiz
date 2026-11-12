"""iCalendar RFC 5545, UID estável, retificações e cancelamentos, sem bibliotecas novas."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from raiz.calendario.modelos import Evento


def _texto(v: str) -> str:
    return v.replace("\\", "\\\\").replace("\r", "").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def _dobrar(linha: str) -> list[str]:
    """75 octetos por linha, sem cortar UTF-8; continuação começa com espaço."""
    partes, atual = [], ""
    for c in linha:
        if len((atual + c).encode()) > 75:
            partes.append(atual)
            atual = " "
        atual += c
    return [*partes, atual]


def ics(eventos: list[Evento]) -> str:
    linhas = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Raiz//Calendario//PT-BR",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:Calendário da Raíz",
    ]
    for e in eventos:
        quando = (e.atualizado_em or e.coletado_em).astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        descricao = (
            f"Fonte: {e.fonte_nome}. Coleta: {e.coletado_em:%d/%m/%Y}. "
            f"Confiança da extração: {e.confianca:.0%}. Situação: {e.situacao}. "
            "Confira horário, fuso e condições na fonte oficial."
        )
        if e.codigos_car_publicos:
            descricao += " CAR: " + ", ".join(e.codigos_car_publicos)
        linhas += [
            "BEGIN:VEVENT",
            f"UID:{e.id}@calendario.raiz",
            f"DTSTAMP:{quando}",
            f"LAST-MODIFIED:{quando}",
            f"SEQUENCE:{e.sequencia}",
            f"DTSTART;VALUE=DATE:{e.dia:%Y%m%d}",
            f"DTEND;VALUE=DATE:{e.dia + dt.timedelta(days=1):%Y%m%d}",
            "SUMMARY:" + _texto(e.titulo),
            "DESCRIPTION:" + _texto(descricao),
            "URL:" + e.fonte_url,
            "STATUS:"
            + ("CANCELLED" if e.situacao == "cancelado" else "TENTATIVE" if e.situacao == "adiado" else "CONFIRMED"),
            "END:VEVENT",
        ]
    linhas.append("END:VCALENDAR")
    return "\r\n".join(p for linha in linhas for p in _dobrar(linha)) + "\r\n"
