"""Filtros de produção com áreas exclusivas, preservando os sinais legais do motor.

As colunas históricas continuam sendo sobreposições brutas por fonte. As novas restricao_*_ha contam cada
trecho uma vez, pela prioridade TI > UC integral > UC sustentável (exceto APA) > embargo ativo. Quilombos e
APAs conservam suas colunas e regras originais: não se encaixam nessa prioridade de quatro classes.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import shapely

from raiz.funil import restricoes


def embargos_ativos(df: pd.DataFrame, cod: int) -> gpd.GeoDataFrame:
    """Somente geometria dos termos ativos do município; os atributos do termo não entram na saída."""
    exigidas = {"COD_MUNICIPIO", "SIT_CANCELADO", "SIT_DESEMBARGO"}
    faltam = exigidas - set(df.columns)
    if faltam:
        raise ValueError(f"embargos sem colunas obrigatórias: {sorted(faltam)}")
    codigos = pd.to_numeric(df.COD_MUNICIPIO, errors="coerce")
    ativos = df.loc[(codigos == cod) & (df.SIT_CANCELADO != "S") & (df.SIT_DESEMBARGO != "S")]
    if isinstance(ativos, gpd.GeoDataFrame):
        geoms = ativos.geometry
        return gpd.GeoDataFrame(geometry=geoms, crs=ativos.crs).to_crs(4674)
    if "GEOM_AREA_EMBARGADA" not in ativos:
        raise ValueError("embargos sem geometria")
    # Erro de WKT não deve produzir um falso zero de restrição.
    geoms = shapely.from_wkt(ativos.GEOM_AREA_EMBARGADA.where(ativos.GEOM_AREA_EMBARGADA.notna(), None))
    return gpd.GeoDataFrame(geometry=geoms, crs=4674)


def calcular(g: gpd.GeoDataFrame, motor_filtros, embargos: gpd.GeoDataFrame, con=None) -> pd.DataFrame:
    """Acrescenta a composição sem dupla contagem, sem alterar filtros/áreas do contrato anterior.

    O chamador mantém ponte_vetorial ativa para o mesmo módulo R utilizado pelo motor_filtros, reutilizando
    a conexão tanto nos cruzamentos brutos quanto no cruzamento da camada limpa.
    """
    t = motor_filtros.filtros(g)
    base = g.to_crs(4674)
    if len(base):
        x0, y0, x1, y1 = base.total_bounds
        ti = motor_filtros.camada("ti").cx[x0:x1, y0:y1]
        uc = motor_filtros.camada("uc").cx[x0:x1, y0:y1]
        embargos = embargos.to_crs(4674).cx[x0:x1, y0:y1]
        camadas = {
            "ti": ti,
            "uc_protecao_integral": uc[uc.grupo == "Proteção Integral"],
            "uc_uso_sustentavel": uc[(uc.grupo == "Uso Sustentável") & (uc.categoria != "Área de Proteção Ambiental")],
            "embargo": embargos,
        }
    else:
        camadas = {}
    limpas = restricoes.limpar(camadas)
    # Conserta também o CAR para a interseção; não descarta imóveis pequenos ou sem restrição.
    base = base.to_crs(limpas.crs)
    base.geometry = base.geometry.map(restricoes._poligonos)
    areas = restricoes.por_imovel(base, limpas, con).add_prefix("restricao_")
    areas["restricao_total_ha"] = areas.sum(axis=1)
    return t.merge(areas, left_on="cod_imovel", right_index=True, how="left", validate="one_to_one")
