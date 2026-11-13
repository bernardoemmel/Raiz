"""Limpeza das camadas de restrição antes do cruzamento (E2 passo 2; desenho do wdpar, sem código copiado):

1. conserta cada geometria (make_valid, só polígonos);
2. une as feições de cada classe (sobreposição dentro da classe some);
3. apaga a sobreposição entre classes pela prioridade: terra indígena > UC de proteção integral > UC de uso
   sustentável > embargo. Cada pedaço do território fica numa classe só;
4. corta polígonos gigantes em pedaços de até 512 vértices (como o motor), para o cruzamento ficar barato.

Com isso, a soma das restrições de um imóvel nunca passa da área dele.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import shapely

PRIORIDADE = ("ti", "uc_protecao_integral", "uc_uso_sustentavel", "embargo")


def _poligonos(g):
    g = shapely.make_valid(g)
    partes = [p for p in shapely.get_parts(g) if p.geom_type in ("Polygon", "MultiPolygon")]
    return shapely.union_all(partes) if partes else shapely.Polygon()


def subdividir(geom, maxv: int = 512) -> list:
    """Como o ST_Subdivide do PostGIS (e o subdividir do motor): retângulos até cada pedaço ter maxv vértices."""
    out, pilha = [], [geom]
    while pilha:
        g = pilha.pop()
        if g.is_empty:
            continue
        if shapely.get_num_coordinates(g) <= maxv:
            out.extend(p for p in shapely.get_parts(g) if p.geom_type == "Polygon" and not p.is_empty)
            continue
        x0, y0, x1, y1 = g.bounds
        if x1 - x0 >= y1 - y0:
            xm = (x0 + x1) / 2
            caixas = [shapely.box(x0, y0, xm, y1), shapely.box(xm, y0, x1, y1)]
        else:
            ym = (y0 + y1) / 2
            caixas = [shapely.box(x0, y0, x1, ym), shapely.box(x0, ym, x1, y1)]
        pilha += [_poligonos(shapely.intersection(g, c)) for c in caixas]
    return out


def limpar(camadas: dict[str, gpd.GeoDataFrame], crs: int = 5880, maxv: int = 512) -> gpd.GeoDataFrame:
    """Uma camada só, sem sobreposição, com a coluna `restricao` (a classe que venceu) e `prioridade` (0 = maior)."""
    desconhecidas = set(camadas) - set(PRIORIDADE)
    if desconhecidas:
        raise ValueError(f"classes sem prioridade definida: {sorted(desconhecidas)}")
    ja, linhas = shapely.Polygon(), []
    for i, nome in enumerate(PRIORIDADE):
        g = camadas.get(nome)
        if g is None or not len(g):
            continue
        uniao = _poligonos(shapely.union_all([_poligonos(x) for x in g.to_crs(crs).geometry.values if x is not None]))
        resto = _poligonos(shapely.difference(uniao, ja)) if not ja.is_empty else uniao
        if resto.is_empty:
            continue
        ja = _poligonos(shapely.union(ja, resto))
        linhas += [(nome, i, p) for p in subdividir(resto, maxv)]
    df = pd.DataFrame(linhas, columns=["restricao", "prioridade", "geometry"])
    return gpd.GeoDataFrame(df, geometry="geometry", crs=crs)


def por_imovel(base: gpd.GeoDataFrame, limpas: gpd.GeoDataFrame, con=None) -> pd.DataFrame:
    """Hectares de cada restrição (já sem sobreposição) por imóvel, pelo caminho novo (iOverlay)."""
    from raiz.funil.duck import pares
    from raiz.funil.novo import areas_iov

    cols = [f"{n}_ha" for n in PRIORIDADE]
    if not len(limpas) or not len(base):
        return pd.DataFrame(0.0, index=pd.Index(base.cod_imovel, name="cod_imovel"), columns=cols)
    base = base.to_crs(limpas.crs)
    ib, il = pares(base, limpas, con)
    a = areas_iov(base.geometry.values, limpas.geometry.values, ib, il) / 1e4
    t = pd.DataFrame({"cod_imovel": base.cod_imovel.values[ib], "r": limpas.restricao.values[il], "ha": a})
    t = t.pivot_table(index="cod_imovel", columns="r", values="ha", aggfunc="sum").rename(columns=lambda c: f"{c}_ha")
    return t.reindex(index=pd.Index(base.cod_imovel, name="cod_imovel"), columns=cols).fillna(0.0)
