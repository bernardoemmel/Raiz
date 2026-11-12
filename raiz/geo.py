"""Camadas geográficas do front no PostGIS (rotas /geo da API).

`raiz geo carregar 1507300 1504950` lê o que front/scripts/geo.py gerou (divisa do município, terras indígenas,
unidades de conservação e rios do TerraBrasilis, em GeoJSON) e grava em geo.camada, trocando o que havia do
município. Os imóveis não passam por aqui: a API serve os polígonos de funil.imovel, que a carga da rodada do motor
já grava. O mapa base (base_<mun>.pmtiles) fica em arquivo e é servido com Range.

Só nomes de lugar passam (nome da TI, da UC, do município); qualquer outra propriedade com cara de dado pessoal sai,
e todo texto passa pela máscara de CPF/CNPJ.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import Connection, text

from raiz import RAIZ_REPO
from raiz.config import config
from raiz.privacidade import colunas_pessoais, mascarar

CAMADAS = ("municipio", "ti", "uc", "rios")


def pasta_geo() -> Path:
    """Onde ficam os arquivos gerados por front/scripts/geo.py (e o base_<mun>.pmtiles)."""
    return Path(config().geo_dir) if config().geo_dir else RAIZ_REPO / "front" / "geo"


def limpar_propriedades(p: dict) -> dict:
    fora = set(colunas_pessoais(p.keys(), permitir=("nome",)))  # "nome" aqui é nome de lugar (TI, UC, município)
    return {k: (mascarar(v) if isinstance(v, str) else v) for k, v in p.items() if k not in fora}


def carregar(con: Connection, cod_ibge: int, pasta: Path | None = None) -> dict[str, int]:
    """Grava as camadas de um município. Devolve {camada: feições}. Camada sem arquivo fica como estava."""
    pasta = pasta or pasta_geo()
    out = {}
    for camada in CAMADAS:
        arq = pasta / f"{camada}_{cod_ibge}.geojson"
        if not arq.exists():
            continue
        fc = json.loads(arq.read_text(encoding="utf-8"))
        con.execute(text("delete from geo.camada where cod_ibge = :c and camada = :k"), {"c": cod_ibge, "k": camada})
        n = 0
        for f in fc.get("features", []):
            if not f.get("geometry"):
                continue
            con.execute(
                text("""insert into geo.camada (cod_ibge, camada, propriedades, geom, fonte)
                        values (:c, :k, cast(:p as jsonb),
                                ST_SetSRID(ST_MakeValid(ST_GeomFromGeoJSON(:g)), 4674), :f)"""),
                {
                    "c": cod_ibge,
                    "k": camada,
                    "p": json.dumps(limpar_propriedades(f.get("properties") or {}), ensure_ascii=False),
                    "g": json.dumps(f["geometry"]),
                    "f": arq.name,
                },
            )
            n += 1
        out[camada] = n
    return out


def arquivo_base(cod_ibge: int, pasta: Path | None = None) -> Path | None:
    f = (pasta or pasta_geo()) / f"base_{int(cod_ibge)}.pmtiles"
    return f if f.exists() else None
