"""Coleta diária dos limites públicos de projetos e concessões, sem download manual (E-terra comprometida).

Fontes (as mesmas de raiz/coleta/compromissos_*.py, sem banco):
  verra            KML oficial de cada projeto brasileiro do catálogo Berkeley (floresta e uso da terra: ARR,
                   REDD, IFM);
  sfb_concessoes   limites das UMFs das concessões federais;
  limites_pesquisa base científica do Zenodo (CC BY 4.0), só como indício (nunca polígono oficial).
Saída, numa pasta que o workflow publica no Release "insumos":
  comprometida_limites.parquet   um polígono por linha: fonte, objeto, registro, tipo, situação, certeza, UF, datas;
  comprometida_cobertura.json    o que cada fonte cobriu (estado, bbox, data, contagens) e as versões;
  projetos_carbono.tar.gz        só os limites oficiais e ativos da Verra, em GeoJSON, no formato que o motor lê
                                 (motor/raiz_estado.py: pasta projetos_carbono/), para a frente ja_tem_projeto.
Sem nome, CPF ou proponente: os registros passam pela lista de campos de raiz/terra_comprometida.normalizar.
Uma fonte que falha vira cobertura "indisponivel": quem consome nunca lê isso como terra livre.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import tarfile
from pathlib import Path

import geopandas as gpd
import shapely

from raiz import terra_comprometida as tc

VERSAO = "comprometida-coleta-2026a"
BBOX_BRASIL = (-74.0, -34.0, -34.0, 6.0)
NOMES = ("comprometida_limites.parquet", "comprometida_cobertura.json", "projetos_carbono.tar.gz")
COLUNAS = ["fonte_id", "objeto_id", "registro", "tipo", "situacao", "certeza", "uf", "fonte_url", "data_referencia",
           "observado_em", "inicio", "fim"]  # fmt: skip


def _cobertura_da_fonte(fonte: str, itens: list[dict], com_geometria: int, esperados: int | None, hoje: str) -> dict:
    """Uma linha de cobertura por fonte, escopo bbox Brasil. Verra consulta projeto a projeto: 'consultado' só se todo
    projeto do catálogo trouxe polígono; 'parcial' se alguns trouxeram; 'indisponivel' se nenhum."""
    meta = tc.catalogo_fontes()["fontes"][fonte]
    estados = [c.get("estado") for c in itens]
    if fonte == "verra":
        if not com_geometria:
            estado = "indisponivel"
        else:
            estado = "consultado" if esperados and com_geometria >= esperados else "parcial"
    elif not itens or all(e == "indisponivel" for e in estados):
        estado = "indisponivel"
    else:
        estado = "consultado" if all(e == "consultado" for e in estados) else "parcial"
    return {
        "fonte_id": fonte,
        "estado": estado,
        "escopo": "bbox",
        "recorte": "BR",
        "bbox": list(BBOX_BRASIL),
        "url": meta["url"],
        "licenca": meta["licenca"],
        "data_referencia": next((c.get("data_referencia") for c in itens if c.get("data_referencia")), None),
        "consultado_em": hoje,
        "projetos_esperados": esperados,
        "projetos_com_poligono": com_geometria,
    }


def coletar(fontes=("verra", "sfb_concessoes"), *, observado_em: str | None = None, limite_verra: int | None = None,
            iterador=None) -> dict:  # fmt: skip
    """Roda os coletores e devolve {"registros": [...com geometria], "cobertura": [...], "erros": [...]}.
    iterador: troca o coletor de rede (testes e páginas gravadas)."""
    hoje = tc._data(observado_em) or dt.date.today().isoformat()
    if iterador is None:
        from raiz.coleta.compromissos_registros import iterar_compromissos as iterador
    fontes = list(dict.fromkeys(fontes))
    if "verra" in fontes and "berkeley" not in fontes:
        fontes = ["berkeley", *fontes]  # o catálogo dá os IDs; ele mesmo não é cobertura de área
    registros, por_fonte, esperados, erros = [], {}, None, []
    for res in iterador(fontes=fontes, bbox=BBOX_BRASIL, limite_verra=limite_verra):
        cob = res.get("cobertura") or {}
        f = cob.get("fonte_id")
        if f == "berkeley":
            esperados = sum(1 for r in res["registros"] if r["registro"] == "VCS")
            continue
        por_fonte.setdefault(f, []).append(cob)
        registros += [r for r in res.get("registros", []) if r.get("geometry") is not None]
        if cob.get("estado") == "indisponivel":
            erros.append(f"{f} {cob.get('recorte')}: indisponível")
    cobertura = []
    for f in fontes:
        if f == "berkeley":
            continue
        n_geo = sum(1 for r in registros if r["fonte_id"] == f)
        cobertura.append(_cobertura_da_fonte(f, por_fonte.get(f, []), n_geo, esperados if f == "verra" else None, hoje))
    return {"registros": registros, "cobertura": cobertura, "erros": erros, "observado_em": hoje,
            "projetos_catalogo": esperados}  # fmt: skip


def para_geodataframe(registros: list[dict]) -> gpd.GeoDataFrame:
    linhas = [{c: r.get(c) for c in COLUNAS} for r in registros]
    geoms = [shapely.make_valid(r["geometry"]) for r in registros]
    return gpd.GeoDataFrame(linhas, columns=COLUNAS, geometry=geoms, crs=4326)


def pacote_motor(registros: list[dict]) -> bytes:
    """projetos_carbono.tar.gz: GeoJSON de cada limite oficial e ativo da Verra (nunca indício, nunca concessão)."""
    buf = io.BytesIO()
    n = 0
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tar:
        for r in sorted(registros, key=lambda x: x["objeto_id"]):
            if r["fonte_id"] != "verra" or r["certeza"] != "poligono_oficial" or r["situacao"] != "ativo":
                continue
            feicao = {
                "type": "Feature",
                "properties": {"projeto": r["objeto_id"]},
                "geometry": json.loads(shapely.to_geojson(r["geometry"])),
            }
            corpo = json.dumps({"type": "FeatureCollection", "features": [feicao]}, separators=(",", ":")).encode()
            info = tarfile.TarInfo(f"projetos_carbono/{r['objeto_id']}.geojson")
            info.size, info.mtime = len(corpo), 0
            tar.addfile(info, io.BytesIO(corpo))
            n += 1
    return buf.getvalue() if n else b""


def gravar(resultado: dict, pasta: str | Path) -> dict:
    """Grava os três arquivos e devolve o manifesto (também gravado como comprometida_cobertura.json)."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    gdf = para_geodataframe(resultado["registros"])
    gdf.to_parquet(pasta / NOMES[0], index=False)
    motor = pacote_motor(resultado["registros"])
    if motor:
        (pasta / NOMES[2]).write_bytes(motor)
    elif (pasta / NOMES[2]).exists():
        (pasta / NOMES[2]).unlink()
    sha = hashlib.sha256((pasta / NOMES[0]).read_bytes()).hexdigest()
    contagem = gdf.groupby(["fonte_id", "certeza"]).size()
    manifesto = {
        "versao": VERSAO,
        "coletado_em": resultado["observado_em"],
        "sha256_limites": sha,
        "limites": int(len(gdf)),
        "por_fonte": {f"{a}:{b}": int(n) for (a, b), n in contagem.items()},
        "projetos_catalogo_verra": resultado.get("projetos_catalogo"),
        "projetos_motor": int(
            sum((gdf.fonte_id == "verra") & (gdf.certeza == "poligono_oficial") & (gdf.situacao == "ativo"))
        ),  # fmt: skip
        "cobertura": [
            tc.cobertura_segura(c) | {k: c[k] for k in ("projetos_esperados", "projetos_com_poligono")}
            for c in resultado["cobertura"]
        ],  # fmt: skip
        "erros": resultado["erros"][:50],
        "atribuicao": "Catálogo: Berkeley Carbon Trading Project (CC BY 4.0). Limites: Verra Registry, SFB e, como "
        "indício, base científica Zenodo 11459391 (CC BY 4.0).",
    }
    (pasta / NOMES[1]).write_text(json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifesto
