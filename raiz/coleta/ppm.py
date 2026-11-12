"""Gatilho da Pesquisa da Pecuária Municipal pelo calendário de divulgação do IBGE (produto 9107).

Leitura do calendário adaptada do PYield (MIT, pyield/ipca/_calendario.py): API v3 de calendário do servicodados,
paginada por `page`/`nextPage`, itens com produto_id, tipo_id (1 = divulgação), ano de referência e data de
divulgação "dd/mm/aaaa hh:mm:ss". A coleta da PPM (SIDRA 3939) só roda quando passou uma divulgação nova.
Pendente no manifesto: conferir robots e termos do servicodados antes de ligar em produção.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import httpx

URL = "https://servicodados.ibge.gov.br/api/v3/calendario/{produto}"
PRODUTO_PPM = 9107


@dataclass(frozen=True)
class Divulgacao:
    ano_referencia: int
    data: dt.date


def buscar_paginas(cliente: httpx.Client, produto: int = PRODUTO_PPM, por_pagina: int = 100) -> list[dict]:
    itens, pagina = [], 1
    while True:
        r = cliente.get(URL.format(produto=produto), params={"qtd": por_pagina, "page": pagina}, timeout=10)
        r.raise_for_status()
        j = r.json()
        itens += j["items"]
        proxima = j["nextPage"]
        if type(proxima) is not int or (proxima != 0 and proxima <= pagina):
            raise ValueError("paginação inválida no calendário do IBGE")
        if proxima == 0:
            return itens
        pagina = proxima


def divulgacoes(itens: list[dict], produto: int = PRODUTO_PPM) -> list[Divulgacao]:
    out = set()
    for it in itens:
        if it.get("produto_id") != produto or it.get("tipo_id") != 1:
            continue
        data = dt.datetime.strptime(it["data_divulgacao"].split(" ")[0], "%d/%m/%Y").date()
        out.add(Divulgacao(int(it["ano_referencia_inicio"]), data))
    anos = [d.ano_referencia for d in out]
    if len(anos) != len(set(anos)):
        raise ValueError("datas conflitantes no calendário da PPM")
    return sorted(out, key=lambda d: d.ano_referencia)


def deve_coletar(divs: list[Divulgacao], ultimo_ano_coletado: int | None, hoje: dt.date) -> Divulgacao | None:
    """A divulgação mais nova que já passou e ainda não foi coletada (ou None)."""
    passadas = [
        d for d in divs if d.data <= hoje and (ultimo_ano_coletado is None or d.ano_referencia > ultimo_ano_coletado)
    ]
    return max(passadas, key=lambda d: d.ano_referencia) if passadas else None
