"""Lista de códigos do CAR (CSV ou texto) para a triagem. Só o código entra: qualquer outra coluna do arquivo é
ignorada sem ser lida para lugar nenhum (nome, CPF e contato nunca passam por aqui). Código fora do padrão não é
repetido em mensagem nem log: só a contagem e a linha."""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

CAR = re.compile(r"^[A-Z]{2}-\d{7}-[0-9A-F]{32}$")
LIMITE = 5000
COLUNAS_ACEITAS = ("cod_imovel", "car", "codigo_car", "codigo", "cod_car")


def normalizar(v: str) -> str | None:
    """'pa1504950 0e3b...' -> 'PA-1504950-0E3B...'. None se não for um código do CAR."""
    s = re.sub(r"[^A-Za-z0-9]", "", str(v or "")).upper()
    if len(s) != 41:
        return None
    c = f"{s[:2]}-{s[2:9]}-{s[9:]}"
    return c if CAR.fullmatch(c) else None


def ler(origem: str | bytes | Path) -> tuple[list[str], list[int]]:
    """(códigos sem repetir, na ordem; linhas inválidas). Aceita CSV com cabeçalho (cod_imovel, car, codigo_car...),
    CSV de uma coluna sem cabeçalho ou texto com um código por linha, vírgula ou espaço."""
    if isinstance(origem, Path):
        origem = origem.read_bytes()
    texto = origem.decode("utf-8-sig", errors="replace") if isinstance(origem, bytes) else origem
    linhas = list(csv.reader(io.StringIO(texto)))
    col, inicio = 0, 0
    if linhas:
        cab = [c.strip().lower() for c in linhas[0]]
        achou = [i for i, c in enumerate(cab) if c in COLUNAS_ACEITAS]
        if achou:
            col, inicio = achou[0], 1
    codigos, invalidas, vistos = [], [], set()
    for n, linha in enumerate(linhas[inicio:], start=inicio + 1):
        if not linha or not any(c.strip() for c in linha):
            continue
        # texto solto: vários códigos na mesma linha, separados por espaço ou ponto e vírgula
        candidatos = linha[col].split() if len(linha) == 1 else [linha[col]]
        for cand in candidatos:
            c = normalizar(cand)
            if c is None:
                invalidas.append(n)
            elif c not in vistos:
                vistos.add(c)
                codigos.append(c)
    if len(codigos) > LIMITE:
        raise ValueError(f"lista com mais de {LIMITE} códigos: divida em partes")
    return codigos, sorted(set(invalidas))
