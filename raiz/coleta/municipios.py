"""Lista de municípios por UF: arquivo local dados/municipios.csv (codigo_ibge, uf) ou a API de localidades do IBGE."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests

from raiz import RAIZ_REPO

ARQUIVO = RAIZ_REPO / "dados" / "municipios.csv"
API = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios"


def da_uf(uf: str, s: requests.Session | None = None, arquivo: Path = ARQUIVO) -> list[int]:
    if arquivo.exists():
        m = pd.read_csv(arquivo)
        return sorted(m.loc[m.uf.str.upper() == uf.upper(), "codigo_ibge"].astype(int))
    r = (s or requests.Session()).get(API.format(uf=uf.upper()), timeout=60)
    r.raise_for_status()
    return sorted(int(x["id"]) for x in r.json())
