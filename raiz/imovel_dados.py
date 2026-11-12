"""Colunas e camadas dentro do imóvel para o front (docs/design/dados-para-o-front-v1.md, itens 2 e 3).

Por município, a partir do que o motor já entrega (imoveis_, mapbiomas_, flag_ e geo_<mun>) e do raster de cobertura
do MapBiomas que o motor baixa pela API (cache/mapbiomas/<UF>/<UF>_cobertura_<ano>.tif):

- ficha_<mun>.csv: porte, etapa_funil, motivo_saida, faixas P10/P50/P90 do carbono e da receita por ano com a regra
  escrita, composição da área em hectares (somando a área do imóvel), cidade e estrada mais próximas (OpenStreetMap);
- camadas_<mun>.parquet: polígonos simplificados de mata em pé, área que pode voltar a ser mata, pasto, lavoura, água
  e APP, por imóvel (GeoJSON por imóvel na API e PMTiles por município).

O que depende do banco (selo, código curto, critérios com data, aceite) sai na API (raiz/front_api.py).
Pixel conta para o imóvel quando o centro cai dentro dele (a mesma regra do zonal_janela do motor).
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
import yaml

from raiz import motivos as motivos_mod

# MapBiomas, legenda da coleção 10/11
MATA = (3, 4, 5, 6, 49)  # formação florestal, savânica, mangue, floresta alagável, restinga arbórea
FLORESTA_REGENERACAO = (3, 4)  # a floresta que o motor usa para "pasto a até 1 km de floresta"
NATIVA_NAO_FLORESTAL = (11, 12, 13, 29, 32, 50)
PASTO = (15,)
LAVOURA = (9, 18, 19, 20, 35, 36, 39, 40, 41, 46, 47, 48, 62)
AGUA = (26, 31, 33)
GRUPOS = {"mata_em_pe": 1, "pasto": 2, "lavoura": 3, "agua": 4, "pode_voltar": 5}
DISTANCIA_M = 1000  # pasto a até 1 km de floresta pode voltar a ser mata (regra do motor)
SIMPLIFICAR_GRAUS = 0.00015  # ~15 m
PORTES = ((4, "pequeno"), (15, "médio"), (math.inf, "grande"))  # módulos fiscais, Lei 8.629/1993, art. 4º
ETAPAS = ("cadastro", "sem_problema", "apta", "caminho_terra", "titulo_conferido", "aceite")
# fotos antigas (antes do caminho da terra) usavam com_matricula: vale como caminho_terra na comparação entre rodadas
ETAPAS_ANTIGAS = {"com_matricula": "caminho_terra"}
FAIXAS = Path(__file__).parent / "regras" / "padroes" / "faixas.yaml"


def _num(linha: dict, c: str) -> float | None:
    v = linha.get(c)
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def porte(m_fiscal: float | None) -> str | None:
    if m_fiscal is None:
        return None
    return next(n for lim, n in PORTES if m_fiscal <= lim)


def etapa_e_motivo(linha: dict) -> tuple[str, dict | None]:
    """Última etapa do funil que o imóvel alcançou e o primeiro motivo que o tirou (um só, exclusivo)."""
    lido = motivos_mod.ler(linha)
    if lido["problema"] or not lido["apta"]:
        ruins = [m for m in motivos_mod.motivos(linha) if m["bloqueia"] and not m["ok"]]
        etapa = "cadastro" if lido["problema"] else "sem_problema"
        return etapa, ({"id": ruins[0]["id"], "texto": ruins[0]["texto"]} if ruins else None)
    # a situação da terra não corta: toda apta chega ao caminho da terra; título conferido só para matrícula
    # conferida no cartório ou terra pública sob concessão (selo prata)
    from raiz import terra

    d = terra.do_imovel(linha)
    if terra.selo_prata(d):
        return "titulo_conferido", {"id": "aceite", "texto": "Dono ainda não aceitou"}
    mid, texto = terra.MOTIVO_ETAPA[d["caminho_terra"]]
    return "caminho_terra", {"id": mid, "texto": texto}


def faixas(linha: dict, f: dict | None = None) -> dict:
    f = f or yaml.safe_load(FAIXAS.read_text(encoding="utf-8"))
    p50 = _num(linha, "carbono_tco2_ano") or 0.0
    c = {"p10": p50 * f["carbono"]["fator_p10"], "p50": p50, "p90": p50 * f["carbono"]["fator_p90"]}
    r = f["receita"]
    return {
        "carbono_tco2_ano_p10": round(c["p10"], 1),
        "carbono_tco2_ano_p50": round(c["p50"], 1),
        "carbono_tco2_ano_p90": round(c["p90"], 1),
        "receita_ano_p10": round(c["p10"] * r["preco_p10"]),
        "receita_ano_p50": round(c["p50"] * r["preco_p50"]),
        "receita_ano_p90": round(c["p90"] * r["preco_p90"]),
        "receita_moeda": r["moeda"],
        "faixas_versao": f["versao"],
        "faixas_regra": " ".join(f["regra"].split()),
    }


def _ha_pixel(lat: float, res: float) -> float:
    m = res * 111320.0
    return m * m * math.cos(math.radians(lat)) / 1e4


def _hidrografia(caixa, cache_tb: Path):
    """Polígonos de água do PRODES que o motor guardou em cache/tb (blocos de 0,5 grau)."""
    import geopandas as gpd

    from raiz.funil import grade

    partes = []
    x0, y0, x1, y1 = caixa
    for ch in grade.blocos_tocados(shapely.box(x0, y0, x1, y1)):
        f = cache_tb / f"prodes-legal-amz__hydrography__{ch}.parquet"
        if f.exists():
            partes.append(gpd.read_parquet(f))
    if not partes:
        return None
    return gpd.GeoDataFrame(pd.concat(partes), geometry="geometry").to_crs(4674)


def camadas_e_composicao(
    geo, linhas: dict[str, dict], cobertura_tif: str | Path | None, cache_tb: Path | None = None
) -> tuple[list[dict], dict[str, dict]]:
    """geo: GeoDataFrame dos imóveis (qualquer CRS). Devolve (feições das camadas, composição por imóvel)."""
    import rasterio
    from rasterio.features import geometry_mask, shapes
    from rasterio.windows import from_bounds
    from scipy.ndimage import distance_transform_edt

    from raiz.regras import parametros

    g = geo.to_crs(4674).reset_index(drop=True)
    feicoes, comp = [], {}
    hidro = _hidrografia(tuple(g.total_bounds), cache_tb) if cache_tb else None
    P = parametros()
    ras = rasterio.open(cobertura_tif) if cobertura_tif and Path(cobertura_tif).exists() else None
    try:
        for cod, geom in zip(g.cod_imovel, g.geometry.values, strict=True):
            linha = linhas.get(cod, {})
            ha = _num(linha, "ha") or 0.0
            c = {k: 0.0 for k in ("mata_em_pe", "pasto", "lavoura", "agua", "outros")}
            pode_voltar_ha = 0.0
            if ras is not None and geom is not None and not geom.is_empty:
                res = abs(ras.res[0])
                pad = DISTANCIA_M / 111320.0 * 1.2
                x0, y0, x1, y1 = geom.bounds
                w = from_bounds(x0 - pad, y0 - pad, x1 + pad, y1 + pad, ras.transform).round_offsets().round_lengths()
                cob = ras.read(1, window=w, boundless=True, fill_value=0)
                tr = ras.window_transform(w)
                dentro = geometry_mask([geom], cob.shape, tr, invert=True)
                if not dentro.any():
                    dentro = geometry_mask([geom], cob.shape, tr, invert=True, all_touched=True)
                hp = _ha_pixel(geom.centroid.y, res)
                v = cob[dentro]
                for nome, cls in (("mata_em_pe", MATA), ("pasto", PASTO), ("lavoura", LAVOURA), ("agua", AGUA)):
                    c[nome] = float(np.isin(v, cls).sum() * hp)
                c["outros"] = float(((v > 0) & ~np.isin(v, MATA + PASTO + LAVOURA + AGUA)).sum() * hp)
                floresta = np.isin(cob, FLORESTA_REGENERACAO)
                dist_px = DISTANCIA_M / (res * 111320.0)
                perto = distance_transform_edt(~floresta) <= dist_px if floresta.any() else np.zeros_like(floresta)
                grupo = np.zeros(cob.shape, dtype=np.uint8)
                grupo[np.isin(cob, MATA)] = GRUPOS["mata_em_pe"]
                grupo[np.isin(cob, PASTO)] = GRUPOS["pasto"]
                grupo[np.isin(cob, PASTO) & perto] = GRUPOS["pode_voltar"]
                grupo[np.isin(cob, LAVOURA)] = GRUPOS["lavoura"]
                grupo[np.isin(cob, AGUA)] = GRUPOS["agua"]
                grupo[~dentro] = 0
                pode_voltar_ha = float((grupo == GRUPOS["pode_voltar"]).sum() * hp)
                nomes = {v: k for k, v in GRUPOS.items()}
                por_grupo: dict[str, list] = {}
                for gj, val in shapes(grupo, mask=grupo > 0, transform=tr):
                    por_grupo.setdefault(nomes[int(val)], []).append(shapely.geometry.shape(gj))
                for nome, polis in por_grupo.items():
                    u = shapely.union_all(polis)
                    u = shapely.set_precision(u.simplify(SIMPLIFICAR_GRAUS, preserve_topology=True), 1e-6)
                    if not u.is_empty:
                        n_px = int((grupo == GRUPOS[nome]).sum())
                        feicoes.append({"cod_imovel": cod, "camada": nome, "ha": round(n_px * hp, 2), "geometry": u})
            # APP: faixa da escadinha em volta da água do PRODES, dentro do imóvel
            if hidro is not None and geom is not None and not geom.is_empty:
                agua = hidro[hidro.intersects(geom.buffer(0.01))]
                if len(agua):
                    import geopandas as gpd

                    mf = _num(linha, "m_fiscal") or 0.0
                    faixa = P.escadinha_m(mf)
                    a = gpd.GeoSeries(agua.geometry.values, crs=4674).to_crs(5880)
                    im = gpd.GeoSeries([geom], crs=4674).to_crs(5880).iloc[0]
                    ag = shapely.union_all(a.values)
                    app = shapely.intersection(shapely.difference(ag.buffer(faixa), ag), im)
                    if not app.is_empty:
                        app4674 = gpd.GeoSeries([app], crs=5880).to_crs(4674).iloc[0]
                        app4674 = shapely.set_precision(app4674.simplify(SIMPLIFICAR_GRAUS / 3), 1e-6)
                        feicoes.append({"cod_imovel": cod, "camada": "app", "ha": round(app.area / 1e4, 2),
                                        "geometry": app4674})  # fmt: skip
            # composição: soma exatamente a área do imóvel (a contagem de pixels erra por fração de pixel na borda:
            # se passar da área, todas as classes encolhem na mesma proporção); o que o raster não cobre é sem_dado
            classificado = sum(c.values())
            if ha > 0 and classificado > ha:
                c = {k: v * ha / classificado for k, v in c.items()}
                classificado = ha
            carbono = min(_num(linha, "carbono_ha") or 0.0, c["pasto"])
            comp[cod] = {
                "comp_mata_em_pe_ha": round(c["mata_em_pe"], 2),
                "comp_pasto_ha": round(c["pasto"] - carbono, 2),
                "comp_para_restaurar_ha": round(carbono, 2),
                "comp_lavoura_ha": round(c["lavoura"], 2),
                "comp_agua_ha": round(c["agua"], 2),
                "comp_outros_ha": round(c["outros"], 2),
                "comp_sem_dado_ha": round(max(ha - classificado, 0.0), 2),
                "pode_voltar_ha": round(pode_voltar_ha, 2),
            }
    finally:
        if ras is not None:
            ras.close()
    return feicoes, comp


def gerar_municipio(
    pasta: str | Path, cod: int, cobertura_tif=None, cache_tb: Path | None = None, osm_dia: str | None = None
) -> tuple[pd.DataFrame, object]:
    """ficha_<mun>.csv (DataFrame) e camadas_<mun>.parquet (GeoDataFrame) de um município."""
    import geopandas as gpd

    from raiz import osm
    from raiz.privacidade import remover_colunas_pessoais

    pasta = Path(pasta)
    im, _ = remover_colunas_pessoais(pd.read_csv(pasta / f"imoveis_{cod}.csv", low_memory=False))
    for tipo in ("filtros", "mapbiomas", "flag", "terra"):
        f = pasta / f"{tipo}_{cod}.csv"
        if f.exists():
            extra = pd.read_csv(f, low_memory=False)
            novas = [c for c in extra.columns if c == "cod_imovel" or c not in im.columns]
            im = im.merge(extra[novas], on="cod_imovel", how="left")
    linhas = {str(r["cod_imovel"]): r for r in im.to_dict("records")}
    geo_f = pasta / f"geo_{cod}.parquet"
    geo = gpd.read_parquet(geo_f) if geo_f.exists() else None
    feicoes, comp = ([], {})
    perto = {}
    if geo is not None:
        feicoes, comp = camadas_e_composicao(geo, linhas, cobertura_tif, cache_tb)
        g4326 = geo.to_crs(4326)
        pontos = dict(zip(g4326.cod_imovel.astype(str), shapely.point_on_surface(g4326.geometry.values), strict=True))
        try:
            lugares, estradas = osm.lugares_e_estradas(tuple(g4326.total_bounds), osm_dia)
            perto = osm.por_imovel(pontos, lugares, estradas)
        except Exception:  # noqa: BLE001 - sem rede para o Protomaps: a ficha sai sem cidade e estrada
            perto = {}
    f = yaml.safe_load(FAIXAS.read_text(encoding="utf-8"))
    saida = []
    for cod_im, linha in linhas.items():
        etapa, motivo = etapa_e_motivo(linha)
        saida.append(
            {
                "cod_imovel": cod_im,
                "porte": porte(_num(linha, "m_fiscal")),
                "etapa_funil": etapa,
                "motivo_saida": motivo["id"] if motivo else None,
                "motivo_saida_texto": motivo["texto"] if motivo else None,
                **faixas(linha, f),
                **comp.get(cod_im, {}),
                **perto.get(cod_im, {}),
            }
        )
    camadas = gpd.GeoDataFrame(feicoes, geometry="geometry", crs=4674) if feicoes else None
    return pd.DataFrame(saida), camadas


def escrever_municipio(pasta: str | Path, cod: int, cache_motor: Path, osm_dia: str | None = None) -> dict:
    """Gera e grava ficha_<mun>.csv, camadas_<mun>.parquet e camadas_<mun>.pmtiles na pasta do motor."""
    import geopandas as gpd

    from raiz import tiles

    pasta = Path(pasta)
    uf = pasta.name.upper()
    cob = sorted((cache_motor / "mapbiomas" / uf).glob(f"{uf}_cobertura_*.tif"))
    df, cam = gerar_municipio(pasta, cod, cob[-1] if cob else None, cache_motor / "tb", osm_dia)
    tmp = pasta / f"ficha_{cod}.csv.tmp"
    df.to_csv(tmp, index=False)
    tmp.replace(pasta / f"ficha_{cod}.csv")
    out = {"imoveis": len(df), "camadas": 0, "pmtiles_kb": 0}
    if cam is not None:
        cam.to_parquet(pasta / f"camadas_{cod}.parquet")
        out["camadas"] = len(cam)
        geo_f = pasta / f"geo_{cod}.parquet"
        if geo_f.exists():
            geo = gpd.read_parquet(geo_f)[["cod_imovel", "geometry"]].to_crs(4326)
            geo["geometry"] = geo.geometry.simplify(0.00005)
            pm = pasta / f"camadas_{cod}.pmtiles"
            tiles.gerar(pm, {"imoveis": geo, "camadas": cam[["cod_imovel", "camada", "ha", "geometry"]]})
            out["pmtiles_kb"] = pm.stat().st_size // 1024
    return out
