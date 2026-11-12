"""Tarefa "titulo" do executor, por município: regularização da posse, achados de título e nota de risco.

Grava na pasta do município:
  regularizacao_<mun>.csv  o que falta para o título da posse (raiz/titulo/regularizacao.py);
  achados_<mun>.csv        requisitos da regularização, motivos das certidões lidas e a comparação geométrica do CAR
                           com as parcelas do SIGEF que o cobrem (quando há polígonos: geo_<mun>.parquet e o SIGEF do
                           espelho);
  titulo_<mun>.csv         nota de 1 a 5, bandeiras e decisão (raiz/titulo/nota.py), com titulo_versao.
A versão da tarefa junta a das três regras; mudou alguma, o executor refaz.
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from raiz.titulo import geometria as G
from raiz.titulo import nota as N
from raiz.titulo import regularizacao as RG
from raiz.titulo.achados import COLUNAS, Achado, chave_registro

VERSAO_GEOMETRIA = "geometria-car-sigef-2026a"
FRACAO_PARCELA = 0.2  # parcela entra na comparação quando ao menos 20% dela cai dentro do CAR
TOLERANCIA_CAR_M = G.TOLERANCIA_M["inacessivel"]  # o CAR é declarado: a tolerância mais larga do INCRA


def versao() -> str:
    return f"{RG.versao()}|{N.versao()}|{VERSAO_GEOMETRIA}"


def geometria_car_sigef(geo, sigef) -> list[Achado]:
    """Compara o polígono de cada imóvel do CAR com a união das parcelas do SIGEF que o cobrem (fase geometria).
    geo: GeoDataFrame (cod_imovel, geometry); sigef: GeoDataFrame das parcelas (geometry; parcela_codigo se houver)."""
    out: list[Achado] = []
    if geo is None or sigef is None or len(geo) == 0 or len(sigef) == 0:
        return out
    geo = geo.to_crs(4674) if geo.crs is not None else geo.set_crs(4674)
    sigef = sigef.to_crs(4674) if sigef.crs is not None else sigef.set_crs(4674)
    idx = sigef.sindex
    for cod, g in zip(geo.cod_imovel.astype(str), geo.geometry, strict=True):
        if g is None or g.is_empty:
            continue
        cands = sigef.iloc[list(idx.intersection(g.bounds))]
        sel = []
        for _, p in cands.iterrows():
            pg = p.geometry
            if pg is None or pg.is_empty or not pg.intersects(g):
                continue
            if pg.intersection(g).area >= FRACAO_PARCELA * pg.area:
                sel.append(p)
        if not sel:
            continue
        uniao = sel[0].geometry
        for p in sel[1:]:
            uniao = uniao.union(p.geometry)
        alvo = g if g.geom_type == "Polygon" else max(getattr(g, "geoms", [g]), key=lambda x: x.area)
        if uniao.geom_type != "Polygon":
            uniao = max(getattr(uniao, "geoms", [uniao]), key=lambda x: x.area)
        c = G.comparar(alvo, uniao, TOLERANCIA_CAR_M)
        parcelas = [str(p.get("parcela_codigo")) for p in sel if p.get("parcela_codigo") is not None]
        if c["classe"] in ("D1", "D2", "D3", "D4"):
            sit, grav = "ok", "info"
        elif c["classe"] == "D5":
            sit, grav = "conferir", "confirmar"
        else:
            sit, grav = "conferir", "confirmar"
        out.append(
            Achado(
                registro=chave_registro(cod, parcelas_sigef=parcelas),
                cod_imovel=cod,
                fase="geometria",
                regra="geometria.car_sigef",
                situacao=sit,
                gravidade=grav,
                mensagem=f"CAR contra SIGEF: {c['classe_texto']} (sobreposição {c['iou']:.0%}, área difere "
                f"{c['dif_area_pct']:.1f}%, afastamento máximo {c['afastamento_max_m']:,.1f} m)",
                campo="classe",
                valor=c["classe"],
                fonte=f"CAR e {len(sel)} parcela(s) do SIGEF",
                regra_versao=VERSAO_GEOMETRIA,
            )
        )
    return out


def _geometrias(pasta: Path, cod: int, espelho: Path | None):
    """(CAR, SIGEF) como GeoDataFrames, ou (None, None) quando falta algum."""
    import geopandas as gpd

    f = pasta / f"geo_{cod}.parquet"
    if not f.exists():
        return None, None
    try:
        from raiz.funil import ponte

        sigef = ponte.ler_local(espelho or ponte.espelho_padrao(), "sigef", pasta.name.upper(), cod)
    except Exception:  # noqa: BLE001 - sem espelho do SIGEF, a comparação geométrica fica para depois
        return None, None
    if sigef is None or len(sigef) == 0:
        return None, None
    return gpd.read_parquet(f)[["cod_imovel", "geometry"]], sigef


def _limpo(v):
    return None if isinstance(v, float) and math.isnan(v) else v


def escrever_municipio(pasta: str | Path, cod: int, espelho: Path | None = None) -> dict:
    pasta = Path(pasta)
    reg, ach = RG.calcular_municipio(pasta, cod)
    geo, sigef = _geometrias(pasta, cod, espelho)
    geom = pd.DataFrame([a.linha() for a in geometria_car_sigef(geo, sigef)], columns=COLUNAS)
    ach = pd.concat([ach, RG.achados_da_certidao(pasta, cod), geom], ignore_index=True)
    # nota: terra + regularização + matrícula conferida + achados do imóvel
    im = RG.entrada_municipio(pasta, cod).merge(
        reg[["cod_imovel", "regularizacao_classe"]], on="cod_imovel", how="left"
    )
    fm = RG.arquivo_documentos(pasta, cod, "matricula")
    if fm is not None:
        mt = pd.read_csv(fm, dtype={"cod_imovel": str})
        cols = [c for c in ("cod_imovel", "matricula_situacao", "matricula_onus_graves") if c in mt.columns]
        im = im.merge(mt[cols], on="cod_imovel", how="left")
    por = {c: g.to_dict("records") for c, g in ach.groupby("cod_imovel")} if len(ach) else {}
    r = N.regra()
    notas = []
    for linha in im.to_dict("records"):
        linha = {k: _limpo(v) for k, v in linha.items()}
        n = N.nota_do_imovel(linha, por.get(linha["cod_imovel"], []), r)
        n["titulo_versao"] = versao()
        notas.append(n)
    nt = pd.DataFrame(notas)
    reg.to_csv(pasta / f"regularizacao_{cod}.csv", index=False)
    ach.to_csv(pasta / f"achados_{cod}.csv", index=False)
    nt.to_csv(pasta / f"titulo_{cod}.csv", index=False)
    return {
        "imoveis": len(reg),
        "achados": len(ach),
        "comparados_car_sigef": len(geom),
        **{f"classe_{k}": int(v) for k, v in reg.regularizacao_classe.value_counts().items()},
        **{f"decisao_{k}": int(v) for k, v in nt.titulo_decisao.value_counts().items()},
    }


def versao_do_arquivo(f: Path) -> str | None:
    if not f.exists():
        return None
    v = pd.read_csv(f, usecols=lambda c: c == "titulo_versao", nrows=1)
    return str(v.iloc[0, 0]) if len(v) and len(v.columns) else None


def recalcular(saida: str | Path, ufs: list[str] | None = None) -> dict:
    """Refaz a tarefa nos municípios que faltam ou estão noutra versão."""
    saida = Path(saida)
    v = versao()
    feitos, em_dia, erros = [], 0, []
    for pasta_uf in sorted(p for p in saida.iterdir() if p.is_dir() and (not ufs or p.name.upper() in ufs)):
        for f in sorted(pasta_uf.glob("imoveis_*.csv")):
            cod = int(f.stem.split("_")[1])
            if versao_do_arquivo(pasta_uf / f"titulo_{cod}.csv") == v:
                em_dia += 1
                continue
            try:
                escrever_municipio(pasta_uf, cod)
                feitos.append(cod)
            except Exception as ex:  # noqa: BLE001 - um município quebrado não para os outros
                erros.append(f"{cod}: {ex}")
    return {"refeitos": feitos, "em_dia": em_dia, "erros": erros}
