"""Limites secundários de projetos de carbono, sempre como indício (nunca polígono oficial).

Duas bases públicas que conferem o que o registro oficial diz e cobrem o que ele deixa de fora (KML ilegível, projeto
sem "Project Boundary", registro fora do ar). Foram elas que mostraram, em 16/11/2026, o imóvel de Paragominas
dentro do YBYRÁ REDD+ (VCS4681) quando a coleta Verra tinha caído:

  infoamazonia_carbono  InfoAmazonia, reportagem "Carbono sujo" (2025): 111 projetos na Amazônia (Verra e
                        Cercarbono), a partir dos KML dos registros. Shapefile consolidado num commit fixo do
                        repositório público, conferido por sha256. O repositório não declara licença: uso interno, com
                        crédito, sem redistribuir o arquivo bruto.
  para_redd_zenodo      Paim, West & Silva, Zenodo 23929936 (CC BY 4.0, nov/2026): limites de 24 projetos REDD+ no
                        Pará (linhas "KML Projeto" do GeoPackage), conferido por md5 e tamanho publicados.

Só entram identificador do projeto, registro, situação, UF e geometria. O shapefile da InfoAmazonia traz CNPJ e nome
de empresas: essas colunas nunca são lidas. Nada de código das fontes é executado.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import tempfile
from pathlib import Path

import geopandas as gpd
import httpx
import shapely

from raiz.coleta.compromissos_registros import status_registro
from raiz.terra_comprometida import catalogo_fontes, normalizar

LIMITE = 150 * 1024 * 1024

# InfoAmazonia: commit fixo (último da pasta em 12/03/2026). Commit novo = conferir e trocar aqui, de propósito.
IA_COMMIT = "350f832309a89286af119785deb580db84e4f643"
IA_PASTA = "2025_06-carbono_sujo/data-tidy/shp_projetos"
IA_ARQUIVOS = {
    # extensão: (servidor, sha256). O .shp está no Git LFS (media.githubusercontent.com); os outros, no git comum.
    "shp": ("media", "92a0860ced43efdb8b98d16f1174495d34e446f0353f9413a057c4d02d06822c"),
    "shx": ("raw", "7e9590fd91850a82c878ecbfb1a7286fac0e1721e40951369e46a65164b5467a"),
    "dbf": ("raw", "658f0a97ca510a3ff237a812892d1b45ab3a78107816cb293827649a6096741a"),
    "prj": ("raw", "b7fe68a2eb827ea974a1a995a73676e095a366b383a10a66c7498300d1c58153"),
}
IA_DATA = "2026-03-12"
IA_URL = "https://github.com/InfoAmazonia/unid_geojornalismo/tree/main/2025_06-carbono_sujo"

PA_REGISTRO = "23929936"
PA_ARQUIVO = "database_v1.3.gpkg"
PA_API = f"https://zenodo.org/api/records/{PA_REGISTRO}"


def _baixar(cliente, url: str, destino: Path) -> None:
    with cliente.stream("GET", url) as r, destino.open("wb") as out:
        r.raise_for_status()
        total = 0
        for bloco in r.iter_bytes(1024 * 1024):
            total += len(bloco)
            if total > LIMITE:
                raise ValueError("Arquivo de limites excede o limite")
            out.write(bloco)


def _digest(arquivo: Path, algoritmo: str) -> str:
    with arquivo.open("rb") as f:
        return hashlib.file_digest(f, algoritmo).hexdigest()


def _poligonal(g):
    if g is None or g.is_empty:
        return None
    g = shapely.make_valid(shapely.force_2d(g))
    if g.geom_type == "GeometryCollection":
        g = shapely.union_all([p for p in g.geoms if p.geom_type in ("Polygon", "MultiPolygon")] or [shapely.Polygon()])
    return g if g.geom_type in ("Polygon", "MultiPolygon") and not g.is_empty else None


def _cobertura(fonte: str, data_referencia: str | None, hoje: str) -> dict:
    meta = catalogo_fontes()["fontes"][fonte]
    return {
        "fonte_id": fonte,
        "estado": "parcial",  # base secundária: cobre só os projetos que reuniu, nunca o Brasil inteiro
        "escopo": "brasil",
        "recorte": "BR",
        "url": meta["url"],
        "licenca": meta["licenca"],
        "data_referencia": data_referencia,
        "consultado_em": hoje,
    }


def _id_infoamazonia(v) -> tuple[str, str] | None:
    """BR4681VER -> (VCS4681, VCS); BR125CER -> (CER125, CERCARBONO)."""
    m = re.fullmatch(r"BR(\d{1,8})(VER|CER)", str(v or "").strip())
    if not m:
        return None
    return (f"VCS{m[1]}", "VCS") if m[2] == "VER" else (f"CER{m[1]}", "CERCARBONO")


def _uf_unica(v):
    v = str(v or "").strip().upper()
    return v if re.fullmatch(r"[A-Z]{2}", v) else None  # "AC, MT": projeto em duas UFs fica sem UF


def ler_infoamazonia(arquivo: Path, *, observado_em: str | None = None) -> dict:
    hoje = observado_em or dt.date.today().isoformat()
    g = gpd.read_file(arquivo, columns=["id_crbn", "status", "uf"])  # nunca CNPJ, empresa ou nome
    if g.crs is None:
        raise ValueError("Limites InfoAmazonia sem CRS declarado")
    g = g.to_crs(4326)
    registros = []
    for oid, grupo in g.groupby("id_crbn", sort=True):
        ident = _id_infoamazonia(oid)
        geom = _poligonal(shapely.union_all([shapely.make_valid(shapely.force_2d(x)) for x in grupo.geometry.dropna()]))
        if ident is None or geom is None:
            continue
        situacoes = {status_registro(s) for s in grupo.status.dropna()}
        # Mais de uma situação no mesmo projeto: fica a mais conservadora para o comprador (ainda vale como indício).
        situacao = next((s for s in ("ativo", "em_validacao", "desconhecido", "inativo", "retirado") if s in situacoes),
                        "desconhecido")  # fmt: skip
        ufs = {_uf_unica(u) for u in grupo.uf}
        registros.append(
            normalizar(
                {
                    "fonte_id": "infoamazonia_carbono",
                    "objeto_id": ident[0],
                    "registro": ident[1],
                    "tipo": "projeto_carbono",
                    "situacao": situacao,
                    "certeza": "poligono_secundario",
                    "uf": ufs.pop() if len(ufs) == 1 else None,
                    "geometry": geom,
                    "fonte_url": IA_URL,
                    "data_referencia": IA_DATA,
                    "observado_em": hoje,
                }
            )
        )
    return {"registros": registros, "cobertura": _cobertura("infoamazonia_carbono", IA_DATA, hoje)}


def coletar_infoamazonia(*, cliente=None, observado_em: str | None = None) -> dict:
    hoje = observado_em or dt.date.today().isoformat()
    if cliente is None:
        with httpx.Client(timeout=120, follow_redirects=True) as c:
            return coletar_infoamazonia(cliente=c, observado_em=hoje)
    servidores = {
        "raw": f"https://raw.githubusercontent.com/InfoAmazonia/unid_geojornalismo/{IA_COMMIT}/{IA_PASTA}",
        "media": f"https://media.githubusercontent.com/media/InfoAmazonia/unid_geojornalismo/{IA_COMMIT}/{IA_PASTA}",
    }
    try:
        with tempfile.TemporaryDirectory(prefix="raiz-limites-ia-") as tmp:
            for ext, (servidor, sha) in IA_ARQUIVOS.items():
                destino = Path(tmp) / f"shp_projetos.{ext}"
                _baixar(cliente, f"{servidores[servidor]}/shp_projetos.{ext}", destino)
                if _digest(destino, "sha256") != sha:
                    raise ValueError("Checksum dos limites InfoAmazonia não confere")
            return ler_infoamazonia(Path(tmp) / "shp_projetos.shp", observado_em=hoje)
    except httpx.HTTPError:
        raise ValueError("Limites InfoAmazonia indisponíveis") from None


def ler_para_redd(arquivo: Path, *, observado_em: str | None = None, data_referencia: str | None = None) -> dict:
    hoje = observado_em or dt.date.today().isoformat()
    # Só os limites dos projetos; as outras linhas são recortes de sobreposição com CAR, SIGEF, glebas etc.
    g = gpd.read_file(arquivo, columns=["Project_ID", "Source", "Type"], where="\"Type\" = 'KML Projeto'")
    if g.crs is None:
        raise ValueError("Limites REDD+ do Pará sem CRS declarado")
    g = g.to_crs(4326)
    registros = []
    for (pid, fonte), grupo in g.groupby(["Project_ID", "Source"], sort=True):
        num = str(pid).split(".")[0].strip()
        geom = _poligonal(shapely.union_all([shapely.make_valid(shapely.force_2d(x)) for x in grupo.geometry.dropna()]))
        if str(fonte).strip().lower() != "verra" or not re.fullmatch(r"\d{1,8}", num) or geom is None:
            continue
        registros.append(
            normalizar(
                {
                    "fonte_id": "para_redd_zenodo",
                    "objeto_id": f"VCS{num}",
                    "registro": "VCS",
                    "tipo": "projeto_carbono",
                    "situacao": "desconhecido",  # a base não traz o status atual; o registro oficial diz
                    "certeza": "poligono_secundario",
                    "uf": "PA",
                    "geometry": geom,
                    "fonte_url": f"https://zenodo.org/records/{PA_REGISTRO}",
                    "data_referencia": data_referencia,
                    "observado_em": hoje,
                }
            )
        )
    return {"registros": registros, "cobertura": _cobertura("para_redd_zenodo", data_referencia, hoje)}


def coletar_para_redd(*, cliente=None, observado_em: str | None = None) -> dict:
    hoje = observado_em or dt.date.today().isoformat()
    if cliente is None:
        with httpx.Client(timeout=120, follow_redirects=True) as c:
            return coletar_para_redd(cliente=c, observado_em=hoje)
    try:
        r = cliente.get(PA_API)
        r.raise_for_status()
        meta = r.json()
        if str(meta.get("id")) != PA_REGISTRO or meta.get("metadata", {}).get("license", {}).get("id") != "cc-by-4.0":
            raise ValueError("Versão ou licença da base REDD+ do Pará mudou")
        f = next((x for x in meta.get("files", []) if x.get("key") == PA_ARQUIVO), None)
        if f is None:
            raise ValueError("Arquivo da base REDD+ do Pará não encontrado")
        algoritmo, esperado = str(f["checksum"]).split(":", 1)
        if algoritmo != "md5" or int(f["size"]) > LIMITE:
            raise ValueError("Base REDD+ do Pará fora do contrato de integridade")
        with tempfile.TemporaryDirectory(prefix="raiz-limites-pa-") as tmp:
            destino = Path(tmp) / PA_ARQUIVO
            # Endereço fixo, nunca segue URL arbitrária do JSON.
            _baixar(cliente, f"{PA_API}/files/{PA_ARQUIVO}/content", destino)
            if destino.stat().st_size != int(f["size"]) or _digest(destino, "md5") != esperado:
                raise ValueError("Checksum da base REDD+ do Pará não confere")
            return ler_para_redd(
                destino, observado_em=hoje, data_referencia=meta.get("metadata", {}).get("publication_date")
            )
    except httpx.HTTPError:
        raise ValueError("Base REDD+ do Pará indisponível") from None
