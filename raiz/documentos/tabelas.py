"""Leitura das saídas do motor e do produto, sempre pelo nome das colunas (docs/colunas.md), tolerando colunas novas.

Procura <tabela>_<cod_municipio>.csv nas pastas de entrada (motor/saida/<UF>/, dados/estados/<UF>/, dados/amostra/ ou
RAIZ_DOCUMENTOS_ENTRADA) e nas saídas dos documentos (dados/documentos/saida/<UF>/). Coluna pessoal que aparecer por
engano (nome, CPF, contato) sai na leitura.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pandas as pd

from raiz.documentos.config import pasta_dados, pastas_entrada, uf_do_municipio

_PESSOAL = re.compile(
    r"cpf|cnpj|nome|^nom_|_nom_|e_?mail|telefone|celular|^fone|_fone|whats|endereco|endereço|logradouro|"
    r"^rg$|^rg_|_rg$|^nis|pis_pasep|titulo_eleitor|nasc|^mae|nome_mae|filiacao|^cep$|_cep$|propriet|dono|titular",
    re.IGNORECASE,
)
_LUGAR = re.compile(r"munic|^uf$|estado|bioma|nome_uc|nome_ti|terra_ind|unidade|nome_projeto|camada", re.IGNORECASE)
TEXTO = {"cod_imovel", "registro_cns", "registro_matricula", "grupo_id", "codigo_curto"}


def pasta_saida(cod_municipio: int | str) -> Path:
    p = pasta_dados() / "saida" / (uf_do_municipio(cod_municipio) or "XX")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _bases() -> list[Path]:
    return [*pastas_entrada(), pasta_dados() / "saida"]


def achar(tabela: str, cod_municipio: int | str) -> Path | None:
    uf = uf_do_municipio(cod_municipio)
    nome = f"{tabela}_{cod_municipio}.csv"
    for base in _bases():
        for p in (base / (uf or "") / nome, base / nome):
            if p.is_file():
                return p
    return None


def ler_csv(caminho: Path) -> pd.DataFrame:
    df = pd.read_csv(caminho, dtype={c: str for c in TEXTO}, low_memory=False)
    fora = [c for c in df.columns if _PESSOAL.search(c) and not _LUGAR.search(c)]
    return df.drop(columns=fora)


def ler(tabela: str, cod_municipio: int | str) -> pd.DataFrame | None:
    p = achar(tabela, cod_municipio)
    return ler_csv(p) if p else None


def arquivos(tabela: str) -> Iterator[Path]:
    """Todos os <tabela>_<mun>.csv das pastas de entrada (sem repetir o mesmo município)."""
    vistos: set[str] = set()
    for base in _bases():
        if not base.is_dir():
            continue
        for p in sorted(base.rglob(f"{tabela}_*.csv")):
            m = re.fullmatch(rf"{tabela}_(\d{{7}})\.csv", p.name)
            if m and m.group(1) not in vistos:
                vistos.add(m.group(1))
                yield p


def municipio_do_arquivo(caminho: Path) -> int | None:
    m = re.search(r"_(\d{7})\.csv$", caminho.name)
    return int(m.group(1)) if m else None


def linha_do_imovel(tabela: str, cod_imovel: str, cod_municipio: int | str) -> dict | None:
    df = ler(tabela, cod_municipio)
    if df is None or "cod_imovel" not in df.columns:
        return None
    r = df[df.cod_imovel == cod_imovel]
    return None if r.empty else {k: (None if pd.isna(v) else v) for k, v in r.iloc[0].to_dict().items()}
