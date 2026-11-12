"""
Raíz: camadas extras por imóvel (idade e perdas da capoeira, fogo, vegetação baixa, vigor e idade do pasto).

Uso:
  pip install exactextract rasterio geopandas pyarrow requests
  python raiz_extras.py PA            # todos os municípios já rodados em saida/PA/

Entradas:
  extras/raiz_extras_<UF>*.tif   GeoTIFFs exportados do Earth Engine (exportar_camadas_extras.js), v1 com 7 bandas uint8
                                 (yb_idade, yb_perdas, fogo_anos, veg_baixa, veg_cresc, pasto_vigor, pasto_idade);
  extras/raiz_extras2_<UF>*.tif  v2 (exportar_camadas_extras_v2.js), 12 bandas, usada no lugar da v1 quando existir
  saida/<UF>/geo_<mun>.parquet   polígonos dos imóveis (gravados pelo raiz_estado.py); se faltar, baixa o CAR de novo.
Saída:
  saida/<UF>/extras_<mun>.csv    uma linha por imóvel com média e máximo de cada banda e a nota de persistência.
Retoma de onde parou.
"""
import sys, os, glob, warnings
import pandas as pd, geopandas as gpd, numpy as np, rasterio
from exactextract import exact_extract as _ee


def exact_extract(r, g, ops, output='pandas', include_cols=None, lote=300):
    """exactextract em lotes; se um lote falhar ('Never get here' com polígono minúsculo/degenerado), roda um a um
    e deixa vazio só o imóvel problemático, em vez de derrubar o município inteiro."""
    import pandas as pd
    g = g.reset_index(drop=True); partes = []
    for i in range(0, len(g), lote):
        s = g.iloc[i:i + lote]
        try:
            partes.append(_ee(r, s, ops, include_cols=include_cols, output='pandas'))
        except RuntimeError:
            for j in range(len(s)):
                try: partes.append(_ee(r, s.iloc[j:j + 1], ops, include_cols=include_cols, output='pandas'))
                except RuntimeError:
                    row = {o: float('nan') for o in ops}
                    if include_cols: row.update({c: s.iloc[j][c] for c in include_cols})
                    partes.append(pd.DataFrame([row]))
    return pd.concat(partes, ignore_index=True)
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BANDAS_V1 = ['yb_idade', 'yb_perdas', 'fogo_anos', 'veg_baixa', 'veg_cresc', 'pasto_vigor', 'pasto_idade']
BANDAS_V2 = ['yb_idade', 'yb_perdas', 'fogo_anos', 'fogo_ultimo', 'veg_baixa', 'veg_cresc', 'pasto_vigor', 'pasto_idade',
             'cultura', 'cultura_anos', 'tmf', 'causa_perda']
CLASSES = {'cultura', 'tmf', 'causa_perda'}  # bandas de classe: vale a classe que mais aparece, não a média
BANDAS = BANDAS_V1


def limpa(g):
    """Conserta polígono inválido (um só já derruba o exactextract/GDAL com 'Never get here' e falha de segmentação)."""
    import shapely
    bad = ~g.is_valid
    if bad.any():
        g = g.copy()
        g.loc[bad, 'geometry'] = [shapely.make_valid(x) for x in g.geometry[bad]]
        g.loc[bad, 'geometry'] = g.geometry[bad].apply(
            lambda x: x if x.geom_type in ('Polygon', 'MultiPolygon') else shapely.MultiPolygon(
                [p for p in getattr(x, 'geoms', []) if p.geom_type == 'Polygon'] +
                [q for p in getattr(x, 'geoms', []) if p.geom_type == 'MultiPolygon' for q in p.geoms]))
    return g[~g.is_empty & g.geometry.notna()]


def geometria(uf, cod, pasta):
    f = f'{pasta}/geo_{cod}.parquet'
    if os.path.exists(f):
        return limpa(gpd.read_parquet(f))
    import raiz_estado as R  # baixa o CAR do município de novo (só o perímetro)
    car = R.car_mun(uf, cod)
    car = car[(car.status_imovel != 'CA') & (car.tipo_imovel == 'IRU')]
    g = gpd.GeoDataFrame({'cod_imovel': car.cod_imovel.values}, geometry=car.geometry.values, crs=car.crs)
    g.to_parquet(f)
    return limpa(g)


def zonal(g, rasters):
    """Média e máximo ponderados por pixels, somando os blocos (tiles) do estado."""
    g = g.to_crs(4326).reset_index(drop=True)
    acc = {}
    for r in rasters:
        b = r.bounds
        sub = g.cx[b.left:b.right, b.bottom:b.top]
        if len(sub) == 0: continue
        ops = ['count', 'sum', 'max'] + (['majority'] if BANDAS is BANDAS_V2 else [])
        res = exact_extract(r, sub, ops, include_cols=['cod_imovel'], output='pandas')
        for _, row in res.iterrows():
            k = row.cod_imovel; d = acc.setdefault(k, {})
            for i, nome in enumerate(BANDAS, 1):
                cnt = row.get(f'band_{i}_count', 0) or 0
                d[f'{nome}_n'] = d.get(f'{nome}_n', 0) + cnt
                d[f'{nome}_s'] = d.get(f'{nome}_s', 0) + (row.get(f'band_{i}_sum', 0) or 0)
                d[f'{nome}_max'] = max(d.get(f'{nome}_max', 0), row.get(f'band_{i}_max', 0) or 0)
                if nome in CLASSES and cnt > d.get(f'{nome}_ncls', -1):  # imóvel em dois blocos: vale o bloco com mais pixels
                    d[f'{nome}_ncls'] = cnt; d[f'{nome}_cls'] = row.get(f'band_{i}_majority', 0)
    out = []
    for k, d in acc.items():
        linha = {'cod_imovel': k}
        for nome in BANDAS:
            n = d.get(f'{nome}_n', 0)
            linha[f'{nome}_media'] = d[f'{nome}_s'] / n if n else np.nan
            linha[f'{nome}_max'] = d.get(f'{nome}_max', np.nan)
            if nome in CLASSES and BANDAS is BANDAS_V2: linha[f'{nome}_principal'] = d.get(f'{nome}_cls', np.nan)
        out.append(linha)
    return pd.DataFrame(out)


def ajustes(t):
    # pasto_idade do MapBiomas vem como 200 + anos (0 = não é pasto): converte o máximo para anos
    t['pasto_idade_anos_max'] = np.where(t.pasto_idade_max >= 200, t.pasto_idade_max - 200, np.nan)
    t = t.drop(columns=['pasto_idade_media', 'pasto_idade_max'])
    if BANDAS is BANDAS_V1:
        # veg_baixa saturou em 255 no export v1 (unidade do GPW já em decímetros): não usar
        return t.drop(columns=['veg_baixa_media', 'veg_baixa_max', 'veg_cresc_media', 'veg_cresc_max'])
    # v2: decímetros para metros; crescimento tira o +100
    t['veg_baixa_m_media'] = t.veg_baixa_media / 10; t['veg_cresc_m_media'] = (t.veg_cresc_media - 100) / 10
    t['fogo_ultimo_ano'] = np.where(t.fogo_ultimo_max > 0, t.fogo_ultimo_max + 1984, np.nan)
    drop = [c for c in t.columns if c.startswith(('veg_baixa_', 'veg_cresc_', 'fogo_ultimo_')) and not c.endswith(('_m_media', '_ano'))]
    drop += [f'{b}_{s}' for b in CLASSES for s in ('media', 'max')]
    return t.drop(columns=[c for c in drop if c in t])


def persistencia(t):
    """Nota de 0 a 100 (maior = mais chance de a capoeira ficar de pé). Regra inicial, a recalibrar pelo Aprendiz."""
    n = 100.0
    n -= 15 * t.yb_perdas_max.clip(upper=4).fillna(0)        # cada derrubada anterior pesa
    n -= 5 * t.fogo_anos_max.clip(upper=6).fillna(0)          # anos com fogo
    n += 1 * t.yb_idade_media.clip(upper=20).fillna(0)        # capoeira mais velha resiste mais
    return n.clip(0, 100).round(0)


def main():
    uf = sys.argv[1].upper()
    pasta = f'saida/{uf}'
    global BANDAS
    fs = sorted(glob.glob(f'extras/raiz_extras2_{uf}*.tif'))  # v2 (12 bandas) tem preferência
    BANDAS = BANDAS_V2 if fs else BANDAS_V1
    if not fs: fs = sorted(glob.glob(f'extras/raiz_extras_{uf}*.tif'))
    if not fs:
        print(f'sem extras para {uf} em extras/'); return
    rasters = [rasterio.open(f) for f in fs]
    for f in glob.glob(f'{pasta}/extras_*.csv'):
        cab = open(f).readline()
        if 'veg_baixa_media' in cab or (BANDAS is BANDAS_V2 and 'cultura_principal' not in cab): os.remove(f)  # refaz formato antigo
    cods = sorted(int(os.path.basename(p)[8:-4]) for p in glob.glob(f'{pasta}/imoveis_*.csv'))
    print(f'{uf}: {len(fs)} arquivo(s) de extras, {len(cods)} municípios')
    for i, cod in enumerate(cods, 1):
        f = f'{pasta}/extras_{cod}.csv'
        if os.path.exists(f): continue
        try:
            g = geometria(uf, cod, pasta)
            t = zonal(g, rasters)
            if len(t): t = ajustes(t); t['persistencia_nota'] = persistencia(t)
            t.to_csv(f, index=False)
            print(f'[{i}/{len(cods)}] {cod}: {len(t)} imóveis')
        except Exception as ex:
            print(f'[{i}/{len(cods)}] {cod}: ERRO {ex}')


if __name__ == '__main__':
    main()
