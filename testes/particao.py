"""Divide a suíte Python em partes paralelas do CI sem omitir nem repetir testes.

Uso: `pytest -p testes.particao --parte=2/4 ...`. Cada arquivo de teste vai inteiro para uma parte, então
fixtures de módulo continuam valendo. As partes são equilibradas pelo tempo medido no CI
(`testes/duracoes_ci.json`); arquivo novo, sem medida, entra com o tempo mediano. Toda parte coleta a suíte
inteira, aplica a mesma divisão e grava no JUnit quantos testes a suíte tem, para o job `testes_python`
conferir que a soma das partes é a suíte completa.
"""

from __future__ import annotations

import json
import re
import statistics
from pathlib import Path

import pytest

DURACOES = Path(__file__).with_name("duracoes_ci.json")


def ler_parte(texto: str) -> tuple[int, int]:
    achado = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", texto or "")
    if not achado:
        raise ValueError(f"parte inválida: {texto!r}; use k/n, por exemplo 2/4")
    parte, total = int(achado[1]), int(achado[2])
    if not 1 <= parte <= total:
        raise ValueError(f"parte fora do intervalo: {texto!r}")
    return parte, total


def dividir(arquivos: list[str], duracoes: dict[str, float], partes: int) -> dict[str, int]:
    """Maior arquivo primeiro na parte mais leve; empates resolvidos pelo nome, sempre igual em todas as partes."""
    conhecidos = [duracoes[a] for a in arquivos if a in duracoes]
    padrao = statistics.median(conhecidos) if conhecidos else 1.0
    peso = {a: float(duracoes.get(a, padrao)) for a in set(arquivos)}
    carga = [0.0] * partes
    destino = {}
    for arquivo in sorted(peso, key=lambda a: (-peso[a], a)):
        menor = min(range(partes), key=lambda i: (carga[i], i))
        destino[arquivo] = menor + 1
        carga[menor] += peso[arquivo]
    return destino


def _arquivo(item: pytest.Item) -> str:
    return item.nodeid.split("::", 1)[0]


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--parte", default=None, help="roda só a parte k de n da suíte (k/n)")


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    texto = config.getoption("--parte")
    if not texto:
        return
    parte, total = ler_parte(texto)
    duracoes = json.loads(DURACOES.read_text(encoding="utf-8"))
    destino = dividir([_arquivo(i) for i in items], duracoes, total)
    ficam = [i for i in items if destino[_arquivo(i)] == parte]
    saem = [i for i in items if destino[_arquivo(i)] != parte]
    tamanho_suite = len(items)
    if saem:
        config.hook.pytest_deselected(items=saem)
    items[:] = ficam
    from _pytest.junitxml import xml_key

    xml = config.stash.get(xml_key, None)
    if xml is not None:
        xml.add_global_property("raiz_parte", f"{parte}/{total}")
        xml.add_global_property("raiz_testes_na_suite", str(tamanho_suite))
