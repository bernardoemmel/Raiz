"""
Raíz: acrescenta a APP pela escadinha (art. 61-A) e o teto do art. 61-B aos municípios que rodaram antes dessa regra
entrar no funil (regras do GeoCAR, MIT). Usa o cache de blocos do TerraBrasilis, sem baixar de novo.
Uso: python raiz_app.py PA
Colunas novas em saida/<UF>/imoveis_<mun>.csv: app_escadinha_ha, app_recompor_ha. Pula quem já tem.
"""
import sys, os, glob, warnings, time
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd, geopandas as gpd, shapely
import raiz_estado as R


def app(uf, cod, pasta):
    p = f'{pasta}/imoveis_{cod}.csv'
    c = pd.read_csv(p, index_col=0)
    if 'app_escadinha_ha' in c: return None
    g = gpd.read_parquet(f'{pasta}/geo_{cod}.parquet')
    base = R.fix(g[['cod_imovel', 'geometry']], sub=False)
    bbox = [round(v, 4) for v in g.to_crs(4674).total_bounds]
    L, _ = R.camadas(uf, bbox)
    yd, acc, hy = R.fix(L['yd']), R.fix(L['acc']), R.fix(L['hy'])
    if 'main_class' in yd: yd = yd[yd.main_class.str.upper() == 'DESMATAMENTO']
    r = {}
    if len(hy):
        desm = pd.concat([acc[['geometry']], yd[['geometry']]])
        dg = desm.geometry.values; uh = hy.union_all()
        for w in (5, 8, 15, 20, 30):
            fw = hy.buffer(w).union_all().difference(uh)
            jw = gpd.GeoDataFrame(geometry=shapely.intersection(dg[shapely.intersects(dg, fw)], fw), crs=R.A)
            jw = jw[~jw.is_empty]
            r[w] = R.ov(base, jw).reindex(c.index).fillna(0) if len(jw) else pd.Series(0.0, index=c.index)
    else:
        r = {w: pd.Series(0.0, index=c.index) for w in (5, 8, 15, 20, 30)}
    mf = c.m_fiscal
    c['app_escadinha_ha'] = np.select([mf <= 1, mf <= 2, mf <= 4, mf <= 10], [r[5], r[8], r[15], r[20]], r[30]).round(2)
    teto = np.where(mf <= 2, .10 * c.ha, np.where(mf <= 4, .20 * c.ha, np.inf))
    c['app_recompor_ha'] = np.minimum(c.app_escadinha_ha, teto).round(2)
    c.to_csv(p + '.tmp'); os.replace(p + '.tmp', p)
    return c


def main():
    uf = sys.argv[1].upper(); pasta = f'saida/{uf}'
    cods = sorted(int(os.path.basename(x)[8:-4]) for x in glob.glob(f'{pasta}/imoveis_*.csv'))
    for i, cod in enumerate(cods, 1):
        t = time.time()
        try:
            c = app(uf, cod, pasta)
            if c is not None:
                print(f'[{i}/{len(cods)}] {cod}: APP 30 m {c.app_desmatada_ha.sum():.0f} ha -> escadinha {c.app_escadinha_ha.sum():.0f} ha '
                      f'-> a recompor {c.app_recompor_ha.sum():.0f} ha ({time.time() - t:.0f} s)', flush=True)
        except Exception as ex:
            print(f'[{i}/{len(cods)}] {cod}: ERRO {ex}', flush=True)


if __name__ == '__main__':
    main()
