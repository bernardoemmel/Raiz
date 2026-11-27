"""De onde vêm as colunas de cada fazenda: das pastas do motor (arquivo privado restaurado, sem banco) ou do banco.

As duas rotas devolvem o mesmo dicionário por CAR, com as colunas pelo nome (docs/colunas.md): o imóvel, o
desenvolvedor, a terra, o título, a camada já comprometida e o que mais houver, sem colunas pessoais."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path


def _por_municipio(codigos: list[str]) -> dict[tuple[str, int], set[str]]:
    out: dict[tuple[str, int], set[str]] = defaultdict(set)
    for c in codigos:
        out[(c[:2], int(c[3:10]))].add(c)
    return out


def das_pastas(codigos: list[str], pasta: str | Path) -> dict[str, dict]:
    """pasta: saida/ do motor (com <UF>/imoveis_<mun>.csv) ou a própria pasta do estado."""
    from raiz.pedidos.oferta import linhas_da_pasta

    pasta = Path(pasta)
    out: dict[str, dict] = {}
    for (uf, cod), so in sorted(_por_municipio(codigos).items()):
        p = pasta / uf if (pasta / uf).is_dir() else pasta
        if not (p / f"imoveis_{cod}.csv").exists():
            continue
        for linha in linhas_da_pasta(p, cod, so=so):
            out[str(linha["cod_imovel"])] = linha
    return out


def do_banco(codigos: list[str], engine) -> dict[str, dict]:
    from raiz.front_api import imoveis_do_municipio
    from raiz.protecao.privacidade import remover_colunas_pessoais  # noqa: F401  (a linha do banco já vem sem pessoais)

    out: dict[str, dict] = {}
    for (_uf, cod), so in sorted(_por_municipio(codigos).items()):
        for linha in imoveis_do_municipio(engine, cod_ibge=cod):
            c = str(linha.get("cod_imovel"))
            if c in so:
                out[c] = linha
    return out


def linhas(codigos: list[str], *, pasta: str | Path | None = None, engine=None) -> dict[str, dict]:
    if pasta is not None:
        return das_pastas(codigos, pasta)
    if engine is not None:
        return do_banco(codigos, engine)
    raise ValueError("informe a pasta do motor ou o banco")
