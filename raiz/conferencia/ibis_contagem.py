"""Mesma expressão Ibis em DuckDB e SQLite, só com códigos de municípios.

Os bancos são efêmeros e não recebem CAR, produtor, documento ou geometria. O
carregamento parametrizado evita a inferência de tipos do importador de dados.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path


def conferir(codigos: list[str]) -> dict:
    import ibis

    if any(not isinstance(c, str) or re.fullmatch(r"[1-5]\d{6}", c) is None for c in codigos):
        raise ValueError("código municipal inválido; nenhuma linha foi descartada")
    linhas = [(c,) for c in codigos]
    resultados, consultas = {}, {}
    for nome in ("duckdb", "sqlite"):
        banco = getattr(ibis, nome).connect()
        try:
            tabela = banco.create_table("conferencia", schema={"cod_ibge": "string"})
            for inicio in range(0, len(linhas), 10000):
                banco.con.executemany("INSERT INTO conferencia VALUES (?)", linhas[inicio : inicio + 10000])
            consulta = tabela.group_by("cod_ibge").aggregate(imoveis=tabela.count()).order_by("cod_ibge")
            consultas[nome] = ibis.to_sql(consulta, dialect=nome)
            resultados[nome] = {str(r.cod_ibge): int(r.imoveis) for r in consulta.execute().itertuples()}
        finally:
            banco.disconnect()
    esperado = dict(sorted(Counter(codigos).items()))
    iguais = resultados["duckdb"] == resultados["sqlite"] == esperado
    return {
        "versao": 1,
        "uso": "conferencia; ingestao inalterada",
        "iguais": iguais,
        "linhas": len(codigos),
        "municipios": len(esperado),
        "entrada_sha256": hashlib.sha256("\n".join(codigos).encode()).hexdigest(),
        "versoes": {
            **{n: importlib.metadata.version(n) for n in ("ibis-framework", "duckdb", "sqlglot")},
            "sqlite": sqlite3.sqlite_version,
        },
        "consultas": consultas,
        "contagens": resultados,
    }


def ler_csvs(pasta: Path, coluna: str) -> list[str]:
    codigos = []
    arquivos = sorted(pasta.glob("imoveis_*.csv"))
    if not arquivos:
        raise ValueError("nenhum CSV municipal encontrado")
    for arquivo in arquivos:
        with arquivo.open(newline="", encoding="utf-8-sig") as f:
            leitor = csv.DictReader(f)
            if coluna not in (leitor.fieldnames or []):
                raise ValueError("coluna municipal ausente; nenhuma linha foi descartada")
            codigos.extend(r[coluna] for r in leitor)
    return codigos


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("pasta", type=Path)
    p.add_argument("--coluna", default="cod_municipio_ibge")
    p.add_argument("--saida", type=Path, required=True)
    args = p.parse_args()
    resultado = conferir(ler_csvs(args.pasta, args.coluna))
    args.saida.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n")
    print(
        f"Conferência: {resultado['municipios']} municípios, {resultado['linhas']} linhas; iguais={resultado['iguais']}"
    )
    return 0 if resultado["iguais"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
