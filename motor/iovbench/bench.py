"""
Teste da rodada 9: interseção imóvel x camada pelo iOverlay (Rust, MIT/Apache) contra o GEOS (shapely), nos mesmos pares.
Uso (de dentro de motor/, depois de rodar o funil do município):
  cargo build --release --manifest-path iovbench/Cargo.toml
  python iovbench/bench.py 1507300                       # PRODES acumulado
Resultado em 12/11/2026 (4 núcleos): São Félix do Xingu 93.447 pares, GEOS 12,2 s, iOverlay 5,7 s (2,1x), mesma área
total (7.563.285,5 ha; maior diferença por par 0,32 m²). Altamira 27.127 pares, 3,1 s contra 1,5 s (2,1x), mesma área.
"""
import sys, glob, json, time, subprocess, os, tempfile
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI))
PARES = os.path.join(tempfile.gettempdir(), 'iov_pares.json')
import geopandas as gpd, pandas as pd, numpy as np, shapely
from raiz_estado import fix, A
cod = sys.argv[1]; camada = sys.argv[2] if len(sys.argv) > 2 else 'accumulated_deforestation_2007'
g = gpd.read_parquet(f'saida/PA/geo_{cod}.parquet')
x0, y0, x1, y1 = g.to_crs(4326).total_bounds
fs = []
for f in glob.glob(f'cache/tb/prodes-legal-amz__{camada}__*.parquet'):
    lx, ly = map(float, f.split('__')[-1][:-8].split('_'))
    if lx + 0.5 >= x0 and lx <= x1 and ly + 0.5 >= y0 and ly <= y1: fs.append(f)
L = pd.concat([gpd.read_parquet(f) for f in fs]); L = L[~L.geometry.isna()]
print(cod, camada, len(g), 'imóveis;', len(fs), 'blocos;', len(L), 'polígonos da camada')
base = fix(g, sub=False); lay = fix(L)
lg = lay.geometry.values
ib, il = gpd.GeoSeries(lg, crs=A).sindex.query(base.geometry.values, predicate='intersects')
print(len(ib), 'pares')
t = time.time(); a_sh = shapely.area(shapely.intersection(base.geometry.values[ib], lg[il])); ts = time.time() - t
print(f'shapely (GEOS): {ts:.2f} s')
def aneis(geo):
    out = []
    for p in (geo.geoms if geo.geom_type == 'MultiPolygon' else [geo]):
        if p.geom_type != 'Polygon': continue
        for r in [p.exterior, *p.interiors]: out.append(np.asarray(r.coords)[:-1].tolist())
    return out
B = base.geometry.values
json.dump([[aneis(B[i]), aneis(lg[j])] for i, j in zip(ib, il)], open(PARES, 'w'))
r = subprocess.run([os.path.join(AQUI, "target/release/iovbench"), PARES], capture_output=True, text=True)
print(r.stderr.strip())
a_io = np.array(json.loads(r.stdout))
d = np.abs(a_io - a_sh)
print(f'área total: GEOS {a_sh.sum()/1e4:,.1f} ha, iOverlay {a_io.sum()/1e4:,.1f} ha; maior diferença por par {d.max():.2f} m²; pares com dif > 1 m²: {(d>1).sum()}')
