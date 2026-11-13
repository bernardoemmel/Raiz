"""Limites secundários versionados de registros adicionais, sempre como indício.

Fonte científica CC BY 4.0 (Zenodo 11459391). Baixa só o GeoPackage regional
sul-americano, verifica tamanho e checksum publicados, lê colunas fechadas e
exclui pontos. O processo não importa código distribuído com a pesquisa.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import tempfile
from pathlib import Path

import geopandas as gpd
import httpx

from raiz.terra_comprometida import catalogo_fontes, normalizar

API = "https://zenodo.org/api/records/11459391"
ARQUIVO = "south_america.gpkg"
LIMITE = 230 * 1024 * 1024
REGISTROS = {
    "Verra": "VCS",
    "American Carbon Registry": "ACR",
    "Climate Action Reserve": "CAR",
    "EcoRegistry": "ECOREGISTRY",
    "BioCarbon Registry": "BIOCARBON",
    "Gold Standard": "GS",
}


def _data(v):
    try:
        return dt.datetime.strptime(str(v), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


def ler_limites(arquivo: Path, *, bbox=None, observado_em=None) -> dict:
    """Nunca lê nome de projeto, proponente ou comentários para o DTO."""
    hoje = observado_em or dt.date.today().isoformat()
    colunas = ["ProjectID", "Registry Name", "Geometry Type", "Project Start Date", "Project End Date"]
    g = gpd.read_file(arquivo, columns=colunas, where="\"Country\" = 'Brazil'", bbox=bbox)
    if g.crs is None:
        raise ValueError("Limites de pesquisa sem CRS declarado")
    g = g.to_crs(4326)
    registros = []
    for _, row in g.iterrows():
        if row["Registry Name"] not in REGISTROS:
            raise ValueError("Registro de pesquisa desconhecido")
        geom = row.geometry
        if row["Geometry Type"] != "Polygon" or geom is None or geom.geom_type not in ("Polygon", "MultiPolygon"):
            continue
        registros.append(
            normalizar(
                {
                    "fonte_id": "limites_pesquisa",
                    "objeto_id": str(row["ProjectID"]),
                    "registro": REGISTROS[row["Registry Name"]],
                    "tipo": "projeto_carbono",
                    "situacao": "desconhecido",
                    "certeza": "poligono_secundario",
                    "geometry": geom,
                    "uf": None,
                    "fonte_url": "https://zenodo.org/records/11459391",
                    "data_referencia": None,
                    "observado_em": hoje,
                    "inicio": _data(row["Project Start Date"]),
                    "fim": _data(row["Project End Date"]),
                }
            )
        )
    meta = catalogo_fontes()["fontes"]["limites_pesquisa"]
    return {
        "registros": registros,
        "cobertura": {
            "fonte_id": "limites_pesquisa",
            "estado": "parcial",
            "escopo": "bbox" if bbox else "brasil",
            "recorte": "BR" if bbox is None else ",".join(map(str, bbox)),
            "bbox": list(bbox) if bbox else None,
            "url": meta["url"],
            "licenca": meta["licenca"],
            "data_referencia": None,
            "consultado_em": hoje,
        },
    }


def coletar_limites_pesquisa(*, bbox=None, cliente=None, arquivo: Path | None = None, observado_em=None) -> dict:
    """Download regional por streaming, checksum da versão e arquivo temporário privado.

    `arquivo` permite reusar cache local já baixado, mas a conferência do checksum
    publicado continua obrigatória. A coleta padrão não usa o dataset mundial.
    """
    if cliente is None:
        with httpx.Client(timeout=90, follow_redirects=True) as c:
            return coletar_limites_pesquisa(bbox=bbox, cliente=c, arquivo=arquivo, observado_em=observado_em)
    try:
        r = cliente.get(API)
        r.raise_for_status()
        meta = r.json()
        if str(meta.get("id")) != "11459391" or meta.get("metadata", {}).get("license", {}).get("id") != "cc-by-4.0":
            raise ValueError("Versão ou licença do dataset de limites mudou")
        f = next(x for x in meta["files"] if x["key"] == ARQUIVO)
        algoritmo, esperado = f["checksum"].split(":", 1)
        if algoritmo != "md5" or f["size"] > LIMITE:
            raise ValueError("Dataset regional fora do contrato de integridade")
        with tempfile.TemporaryDirectory(prefix="raiz-limites-privados-") as tmp:
            destino = Path(arquivo) if arquivo else Path(tmp) / ARQUIVO
            if arquivo is None:
                # Endereço fixo observado no manifesto, nunca segue URL arbitrária do JSON.
                with cliente.stream("GET", f"{API}/files/{ARQUIVO}/content") as resposta, destino.open("wb") as out:
                    resposta.raise_for_status()
                    total = 0
                    for bloco in resposta.iter_bytes(1024 * 1024):
                        total += len(bloco)
                        if total > LIMITE:
                            raise ValueError("Dataset regional excede limite")
                        out.write(bloco)
            with destino.open("rb") as arq:
                obtido = hashlib.file_digest(arq, "md5").hexdigest()
            if destino.stat().st_size != f["size"] or obtido != esperado:
                raise ValueError("Checksum do dataset regional não confere")
            resultado = ler_limites(destino, bbox=bbox, observado_em=observado_em)
            # Publicação do dataset é data da fonte; não data de validade de cada projeto.
            resultado["cobertura"]["data_referencia"] = meta["metadata"].get("publication_date")
            return resultado
    except httpx.HTTPError:
        raise ValueError("Fonte de limites de pesquisa indisponível") from None
