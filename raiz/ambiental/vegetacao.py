"""Reserva legal pelo tipo de vegetação (Mapa de Vegetação do IBGE 1:250 000) e área da Lei da Mata Atlântica.

O motor (motor/raiz_estado.py, pct_rl) escolhe o índice da reserva pelo BIOMA no ponto central do imóvel. A lei não
fala de bioma: o art. 12 da Lei 12.651/2012 dá, na Amazônia Legal, 80% em área de florestas, 35% em área de cerrado e
20% em área de campos gerais, e o §2º manda somar cada parte do imóvel com o seu índice. Três erros saem daí:
  - savana dentro do bioma Amazônia (lavrado de Roraima, cerrados do Amapá, campinas): o motor dá 80%, a lei 35% ou 20%;
  - floresta estacional dentro do bioma Cerrado (norte de Mato Grosso, Tocantins): o motor dá 35%, a lei 80%;
  - Maranhão a leste do meridiano de 44º (fora da Amazônia Legal, LC 124/2007): o motor dá 35% ou 80%, a lei 20%.

Este módulo classifica cada polígono do IBGE em floresta, cerrado, campos, transicao (contato floresta x savana) ou
agua, e mede por imóvel quantos hectares caem em cada classe, dentro e fora da Amazônia Legal.

Entrada: vege_area.zip do IBGE (geoftp, versão 2026), convertido por preparar() em ambiental_vegetacao.parquet
(classe, regiao, lei_ma, geometria; bbox para leitura por janela). Regras em raiz/regras/padroes/ambiental.yaml.
"""

from __future__ import annotations

import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

URL_IBGE = (
    "https://geoftp.ibge.gov.br/informacoes_ambientais/vegetacao/vetores/escala_250_mil/versao_2026/vege_area.zip"
)
CRS_AREA = 5880
CLASSES = ("floresta", "cerrado", "campos", "transicao")
_FLORESTAIS = re.compile(r"arb[oó]rea|manguezal", re.I)


def _regioes(codigo: str | None) -> list[str]:
    """Letras de região de um código do IBGE: 'SN' -> ['S', 'N']; 'Sas' -> ['S']; 'rsh' -> ['r']; 'STN' -> 3."""
    if not codigo or not isinstance(codigo, str):
        return []
    if codigo[0] == "r":
        return ["r"]
    m = re.match(r"[A-Z]+", codigo)
    if not m:
        return []
    letras = m.group(0)
    # um código com subtipo tem uma maiúscula seguida de minúsculas (Sas, Dau); contato é só maiúsculas (SN, STN),
    # às vezes com sufixo minúsculo (SNt)
    return list(letras)


def _classe_regiao(letra: str, rv: dict) -> str | None:
    if letra in rv["floresta"]:
        return "floresta"
    if letra in rv["cerrado"]:
        return "cerrado"
    if letra in rv["campos"]:
        return "campos"
    if letra == "L":
        return rv.get("campinarana_sem_subtipo", "floresta")
    return None


def _juntar(classes: list[str]) -> str | None:
    """Contato: só floresta -> floresta; floresta com outra -> transicao; senão a mais protetiva (cerrado > campos)."""
    cs = {c for c in classes if c}
    if not cs:
        return None
    if cs == {"floresta"}:
        return "floresta"
    if "floresta" in cs:
        return "transicao"
    return "cerrado" if "cerrado" in cs else "campos"


def classificar_codigo(natural: str | None, nome: str | None, preterita: str | None, regiao: str | None, rv: dict):
    """Classe de reserva de um polígono. natural = leg_uveg (vegetação que está lá), nome = nm_uveg,
    preterita = veg_pretet (vegetação antes da ocupação), regiao = cd_fito."""
    if regiao == "Magua" or natural == "Magua":
        return "agua"
    if natural and isinstance(natural, str):
        letras = _regioes(natural)
        if len(letras) == 1:
            r = letras[0]
            sub = natural[:2]
            if sub in rv.get("gramineo_lenhosa", ()):
                return "campos"
            if r == "L":
                return {"Ld": "floresta", "La": "cerrado", "Lb": "cerrado", "Lg": "campos"}.get(sub, "floresta")
            if r == "P":
                return "floresta" if _FLORESTAIS.search(nome or "") else "campos"
            return _classe_regiao(r, rv)
        if len(letras) > 1:
            return _juntar([_classe_regiao(x, rv) for x in letras])
    for cod in (preterita, regiao):
        letras = _regioes(cod)
        if letras:
            return _juntar([_classe_regiao(x, rv) for x in letras])
    return None


def lei_mata_atlantica(natural: str | None, preterita: str | None, regiao: str | None, regioes: list[str]) -> bool:
    """Formações do art. 2º da Lei 11.428/2006 (a UF é conferida à parte). Pioneira só a costeira (Pf, Pm: mangue e
    restinga), não a aluvial (várzea, Pantanal)."""
    cod = regiao if regiao and regiao != "Magua" else preterita
    letras = _regioes(cod)
    if not letras:
        return False
    if letras == ["P"]:
        n = natural if isinstance(natural, str) else ""
        return n.startswith(("Pf", "Pm"))
    return any(x in regioes and x != "P" for x in letras)


def classificar(df: pd.DataFrame, regra: dict) -> pd.DataFrame:
    """Colunas classe e lei_ma para cada linha do vege_area do IBGE (campos leg_uveg, nm_uveg, veg_pretet, cd_fito)."""
    rv = regra["vegetacao"]
    reg_ma = regra["lei_mata_atlantica"]["regioes"]
    col = {
        c: (df[c] if c in df else pd.Series(None, index=df.index))
        for c in ("leg_uveg", "nm_uveg", "veg_pretet", "cd_fito")
    }
    chaves = list(zip(col["leg_uveg"], col["nm_uveg"], col["veg_pretet"], col["cd_fito"], strict=True))
    memo: dict = {}
    classe, lei = [], []
    for k in chaves:
        if k not in memo:
            memo[k] = (classificar_codigo(*k, rv), lei_mata_atlantica(k[0], k[2], k[3], reg_ma))
        classe.append(memo[k][0])
        lei.append(memo[k][1])
    out = df.copy()
    out["classe"] = classe
    out["lei_ma"] = lei
    return out


def preparar(zip_ibge: str | Path, destino: str | Path, regra: dict) -> dict:
    """vege_area.zip do IBGE -> parquet só com o que a triagem usa (sem dado pessoal: é mapa de vegetação)."""
    import pyogrio

    zip_ibge = Path(zip_ibge)
    caminho = f"/vsizip/{zip_ibge.resolve()}/vege_area.shp"
    cols = ["cd_fito", "leg_uveg", "nm_uveg", "veg_pretet"]
    g = pyogrio.read_dataframe(caminho, columns=cols)
    g = classificar(g, regra)
    g = g[g.classe.notna() & (g.classe != "agua")].rename(columns={"cd_fito": "regiao"})
    g = g[["classe", "regiao", "lei_ma", "geometry"]]
    g["geometry"] = shapely.make_valid(g.geometry.values)
    g = g.set_crs(4674, allow_override=True) if g.crs is None else g.to_crs(4674)
    destino = Path(destino)
    tmp = destino.with_suffix(".tmp.parquet")
    g.to_parquet(tmp, write_covering_bbox=True, compression="zstd")
    tmp.replace(destino)
    return {
        "poligonos": int(len(g)),
        "por_classe": {k: int(v) for k, v in g.classe.value_counts().items()},
        "lei_ma": int(g.lei_ma.sum()),
    }


def ler(arquivo: str | Path, caixa=None) -> gpd.GeoDataFrame:
    """Lê o parquet preparado, só na caixa (lon/lat) pedida."""
    try:
        g = gpd.read_parquet(arquivo, bbox=tuple(caixa) if caixa is not None else None)
    except ValueError:  # arquivo sem a coluna de caixa (gravado fora de preparar): lê inteiro e recorta
        g = gpd.read_parquet(arquivo)
        if caixa is not None:
            g = g[g.intersects(shapely.box(*caixa))]
    return g.set_crs(4674) if g.crs is None else g


# --- por imóvel --------------------------------------------------------------------------------------------------


def _amazonia_legal(car4674: gpd.GeoDataFrame, uf: str, rl: dict):
    """Geometria (em 4674) da parte de cada imóvel dentro da Amazônia Legal: tudo, nada ou, no Maranhão, a oeste de
    44º (LC 124/2007)."""
    geoms = car4674.geometry.values
    if uf not in rl["ufs"]:
        return np.array([shapely.Polygon()] * len(geoms), dtype=object)
    if uf != "MA":
        return geoms
    oeste = shapely.box(-180, -90, float(rl["maranhao_meridiano"]), 90)
    return shapely.intersection(geoms, oeste)


def por_imovel(car: gpd.GeoDataFrame, veg: gpd.GeoDataFrame | None, uf: str, regra: dict) -> pd.DataFrame:
    """Hectares de cada classe da reserva por imóvel (dentro da Amazônia Legal), fora dela, na Lei da Mata Atlântica,
    e a área coberta pelo mapa. car: cod_imovel + geometry (qualquer CRS). veg: saída de ler() (None = sem mapa)."""
    rl = regra["reserva_legal"]
    car = car[["cod_imovel", "geometry"]].reset_index(drop=True)
    c4674 = car.to_crs(4674)
    area = gpd.GeoSeries(c4674.geometry, crs=4674).to_crs(CRS_AREA)
    out = pd.DataFrame({"cod_imovel": car.cod_imovel.astype(str).values})
    out["ha_geo"] = area.area.values / 1e4
    amz = gpd.GeoSeries(_amazonia_legal(c4674, uf, rl), crs=4674).to_crs(CRS_AREA)
    amz_ha = np.nan_to_num(amz.area.values / 1e4)
    out["fora_amazonia_legal_ha"] = np.maximum(out.ha_geo.values - amz_ha, 0.0)
    out["maranhao_leste_ha"] = out.fora_amazonia_legal_ha if uf == "MA" else 0.0
    cols = [f"rl_{k}_ha" for k in CLASSES] + ["lei_mata_atlantica_ha", "vegetacao_coberta_ha"]
    if veg is None:
        for k in cols:
            out[k] = np.nan
        return out
    for k in cols:
        out[k] = 0.0
    if not len(veg):
        return out
    v = veg.to_crs(CRS_AREA)
    vg = v.geometry.values
    ib, iv = v.sindex.query(area.values, predicate="intersects")
    if not len(ib):
        return out
    inter = shapely.intersection(area.values[ib], vg[iv])
    ha = shapely.area(inter) / 1e4
    t = pd.DataFrame({"i": ib, "classe": v.classe.values[iv], "lei": v.lei_ma.values[iv].astype(bool), "ha": ha})
    out["vegetacao_coberta_ha"] = t.groupby("i").ha.sum().reindex(range(len(out)), fill_value=0.0).values
    if uf in regra["lei_mata_atlantica"]["ufs"]:
        out["lei_mata_atlantica_ha"] = t[t.lei].groupby("i").ha.sum().reindex(range(len(out)), fill_value=0.0).values
    # dentro da Amazônia Legal: a mesma interseção recortada pela parte do imóvel que está nela
    if uf in rl["ufs"]:
        dentro = shapely.intersection(inter, amz.values[ib]) if uf == "MA" else inter
        t["ha_amz"] = shapely.area(dentro) / 1e4
        p = t.pivot_table(index="i", columns="classe", values="ha_amz", aggfunc="sum")
        for k in CLASSES:
            if k in p:
                out[f"rl_{k}_ha"] = p[k].reindex(range(len(out)), fill_value=0.0).fillna(0.0).values
    return out


def percentuais(m: pd.DataFrame, regra: dict) -> pd.DataFrame:
    """pct_RL_vegetacao e pct_RL_alem_vegetacao (índice ponderado pela área de cada classe, art. 12 §2º).
    A água não entra na ponderação; a parte fora da Amazônia Legal pesa com 20%."""
    rl = regra["reserva_legal"]
    amz = rl["amazonia_legal"]
    idx = {
        "floresta": amz["floresta"],
        "cerrado": amz["cerrado"],
        "campos": amz["campos"],
        "transicao": rl["transicao"],
    }
    alem = dict(idx, floresta=rl["floresta_alem"], transicao=rl["floresta_alem"])
    fora = m.fora_amazonia_legal_ha.fillna(0.0)
    pesos = {k: m[f"rl_{k}_ha"].fillna(0.0) for k in CLASSES}
    tot = sum(pesos.values()) + fora
    num = sum(pesos[k] * idx[k] for k in CLASSES) + fora * rl["fora_amazonia_legal"]
    num_alem = sum(pesos[k] * alem[k] for k in CLASSES) + fora * rl["fora_amazonia_legal"]
    out = pd.DataFrame(index=m.index)
    sem = tot <= 0
    out["pct_RL_vegetacao"] = (num / tot.where(~sem)).round(2)
    out["pct_RL_alem_vegetacao"] = (num_alem / tot.where(~sem)).round(2)
    return out


def deficit(
    im: pd.DataFrame,
    pct: pd.Series,
    pct_alem: pd.Series,
    mb: pd.DataFrame | None = None,
    nao_floresta: pd.Series | None = None,
) -> pd.DataFrame:
    """Mesmas contas do motor (motor/raiz_estado.py, municipio) com o índice pela vegetação.

    O motor mede a vegetação pelo PRODES Amazônia, que não acompanha savana nem campo (é a máscara "não floresta"):
    num imóvel de lavrado ou cerrado o motor tira a savana da base e não vê a savana desmatada. Onde a maior parte do
    imóvel não é floresta (nao_floresta: série booleana) e há MapBiomas do imóvel (mb: mb_pasto/agricultura/
    silvicultura_<ano>_ha), a base é o imóvel inteiro e o remanescente é tudo que não é pasto, lavoura ou silvicultura.
    rl_base_fonte diz qual conta valeu (prodes ou mapbiomas)."""
    ha = im.ha.astype(float)
    eleg = ha - im.nao_floresta_ha.fillna(0.0).astype(float)
    rem = im.floresta_rem_ha.fillna(0.0).astype(float)
    desm = im.desm_total_ha.fillna(0.0).astype(float)
    fonte = pd.Series("prodes", index=im.index)
    if mb is not None and nao_floresta is not None and len(mb):
        anos = sorted({int(c.split("_")[2]) for c in mb.columns if re.fullmatch(r"mb_pasto_\d{4}_ha", c)})
        if anos:
            a = anos[-1]
            usos = [f"mb_{k}_{a}_ha" for k in ("pasto", "agricultura", "silvicultura") if f"mb_{k}_{a}_ha" in mb]
            aberto = mb.reindex(im.index)[usos].sum(axis=1, min_count=1)
            usa = nao_floresta.reindex(im.index).fillna(False).astype(bool) & aberto.notna()
            eleg = eleg.where(~usa, ha)
            rem = rem.where(~usa, (ha - aberto).clip(lower=0))
            desm = desm.where(~usa, aberto.clip(upper=ha))
            fonte = fonte.where(~usa, "mapbiomas")
    out = pd.DataFrame(index=im.index)
    out["deficit_RL_vegetacao_ha"] = (pct / 100 * eleg - rem).clip(lower=0).round(4)
    out["deficit_RL_alem_vegetacao_ha"] = (pct_alem / 100 * eleg - rem).clip(lower=0).round(4)
    alem = (desm - out.deficit_RL_alem_vegetacao_ha).clip(lower=0)
    if "m_fiscal" in im:
        alem = alem.where(~(im.m_fiscal.astype(float) <= 4), desm)  # até 4 módulos: não deve RL (art. 67)
    out["alem_RL_vegetacao_ha"] = alem.where(pct.notna()).round(4)
    for c in ("deficit_RL_vegetacao_ha", "deficit_RL_alem_vegetacao_ha"):
        out[c] = out[c].where(pct.notna())
    out["rl_base_fonte"] = fonte.where(pct.notna())
    return out
