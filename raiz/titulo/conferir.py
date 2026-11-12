"""Conferir um documento de terra recebido (memorial descritivo ou planilha ODS do SIGEF) contra o CAR e o SIGEF do
imóvel, e o conjunto de teste do leitor de memorial (E5 passos 1 e 4).

conferir_poligono: o polígono do documento contra o polígono do CAR (geo_<mun>.parquet) e contra as parcelas do SIGEF
que cobrem o CAR (espelho), na escala D1 a D7 (raiz/titulo/geometria.py), com a tolerância do INCRA. Sai como achados
da fase geometria, que podem ir para o banco (titulo.achado, sem rodada: documento avulso).

conjunto_teste: sorteia parcelas do SIGEF, escreve o memorial de cada uma nos dois estilos (SIGEF e antigo, por rumo)
e guarda o par polígono e texto; avaliar_conjunto lê de volta e mede o acerto do leitor (o placar de regressão).
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from shapely.geometry import Polygon, mapping, shape

from raiz.titulo import geometria as G
from raiz.titulo import memorial as M
from raiz.titulo.achados import Achado, chave_registro

VERSAO = "conferir-documento-2026a"


def _maior(g):
    if g is None or g.is_empty:
        return None
    return g if g.geom_type == "Polygon" else max(getattr(g, "geoms", [g]), key=lambda x: x.area)


def poligono_do_car(pasta: Path, cod: int, cod_imovel: str):
    import geopandas as gpd

    f = Path(pasta) / f"geo_{cod}.parquet"
    if not f.exists():
        return None
    g = gpd.read_parquet(f)
    g = g.set_crs(4674) if g.crs is None else g.to_crs(4674)
    x = g[g.cod_imovel.astype(str) == cod_imovel]
    return _maior(x.geometry.iloc[0]) if len(x) else None


def parcelas_do_sigef(pasta: Path, cod: int, alvo: Polygon, espelho: Path | None = None):
    try:
        from raiz.funil import ponte

        s = ponte.ler_local(espelho or ponte.espelho_padrao(), "sigef", Path(pasta).name.upper(), cod)
    except Exception:  # noqa: BLE001 - sem espelho, sem comparação com o SIGEF
        return None
    if s is None or len(s) == 0:
        return None
    s = s.set_crs(4674) if s.crs is None else s.to_crs(4674)
    s = s[s.intersects(alvo)]
    if len(s) == 0:
        return None
    u = s.geometry.iloc[0]
    for g in s.geometry.iloc[1:]:
        u = u.union(g)
    return _maior(u)


def conferir_poligono(
    poligono: Polygon,
    cod_imovel: str,
    origem: str,
    tolerancia_m: float = G.TOLERANCIA_M["artificial"],
    car: Polygon | None = None,
    sigef: Polygon | None = None,
) -> tuple[dict, list[Achado]]:
    """Compara o polígono do documento com o do CAR e o do SIGEF (os que vierem). origem: memorial | planilha."""
    reg = chave_registro(cod_imovel)
    res, achados = {}, []
    for nome, outro, tol in (("sigef", sigef, tolerancia_m), ("car", car, G.TOLERANCIA_M["inacessivel"])):
        if outro is None:
            continue
        c = G.comparar(poligono, outro, tol)
        res[nome] = c
        bom = c["classe"] in ("D1", "D2", "D3")
        achados.append(
            Achado(
                reg, cod_imovel, "geometria", f"{origem}.contra_{nome}", "ok" if bom else "conferir",
                "info" if bom else ("reprova" if c["classe"] in ("D6", "D7") else "confirmar"),
                f"{origem} contra {nome.upper()}: {c['classe_texto']} (sobreposição {c['iou']:.0%}, área difere "
                f"{c['dif_area_pct']:.1f}%, afastamento máximo {c['afastamento_max_m']:,.2f} m, tolerância "
                f"{tol:.2f} m)", "classe", c["classe"], f"{origem} e {nome.upper()}", regra_versao=VERSAO,
            )
        )  # fmt: skip
    return res, achados


def gravar_achados(con, achados: list[Achado]) -> int:
    """Achados de documento avulso no banco (titulo.achado, sem rodada)."""
    from sqlalchemy import text

    from raiz.titulo.achados import COLUNAS

    if not achados:
        return 0
    con.execute(
        text(f"""insert into titulo.achado (rodada_id, {", ".join(COLUNAS)})
                 values (null, {", ".join(":" + c for c in COLUNAS)})"""),
        [a.linha() for a in achados],
    )
    return len(achados)


# --- conjunto de teste do leitor de memorial ---------------------------------------------------------------------


def conjunto_teste(parcelas, n: int = 200, semente: int = 20261112, pasta: Path | None = None) -> list[dict]:
    """Sorteia n parcelas (GeoDataFrame em graus) e gera o memorial de cada uma nos dois estilos. Com pasta, grava
    pares.jsonl (código, polígono GeoJSON, texto) para o placar de regressão."""
    rnd = random.Random(semente)
    idx = list(range(len(parcelas)))
    rnd.shuffle(idx)
    pares = []
    for k in idx[:n]:
        g = _maior(parcelas.geometry.iloc[k])
        if g is None or len(g.exterior.coords) < 4:
            continue
        pts = list(g.exterior.coords)[:-1]
        cod = str(parcelas.iloc[k].get("parcela_codigo") or f"parcela-{k}")
        vs = [(f"TST{(k % 9) + 1}-M-{i + 1:04d}", x, y) for i, (x, y) in enumerate(pts)]
        for estilo in ("sigef", "rumo"):
            pares.append(
                dict(codigo=cod, estilo=estilo, poligono=mapping(Polygon(pts)), texto=M.gerar(vs, estilo=estilo))
            )
    if pasta is not None:
        pasta.mkdir(parents=True, exist_ok=True)
        with (pasta / "pares.jsonl").open("w", encoding="utf-8") as f:
            for p in pares:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
    return pares


def avaliar_conjunto(pares: list[dict], leitor=None) -> dict:
    """Lê cada memorial de volta e compara com o polígono de origem (tolerância de 0,50 m)."""
    por_estilo: dict[str, list] = {}
    for p in pares:
        lt = M.ler(p["texto"], leitor)
        ok = False
        if lt.poligono is not None and lt.poligono.is_valid:
            c = G.comparar(shape(p["poligono"]), lt.poligono, G.TOLERANCIA_M["artificial"])
            ok = c["classe"] in ("D1", "D2")
        por_estilo.setdefault(p["estilo"], []).append((ok, lt.confianca, lt.revisar))
    out = {}
    for e, xs in por_estilo.items():
        out[e] = dict(
            memoriais=len(xs),
            acerto=round(sum(x[0] for x in xs) / len(xs), 4),
            confianca_media=round(sum(x[1] for x in xs) / len(xs), 4),
            para_revisao=sum(x[2] for x in xs),
        )
    return out
