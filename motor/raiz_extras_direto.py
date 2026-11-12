"""
Raíz: as duas camadas que só vinham do Earth Engine e que não são do MapBiomas, agora lidas direto da fonte.

Uso:
  python raiz_extras_direto.py PA          # todos os municípios já rodados em saida/PA/
  python raiz_extras_direto.py PA 1507300  # um município

Fontes (sem chave, sem login):
  JRC Tropical Moist Forest v1.2025 (espelho COG na Source Cooperative, valores idênticos ao JRC; licença aberta do
    JRC/Copernicus, citar a fonte): AnnualChange do último ano, 1 floresta intacta, 2 degradada, 3 desmatada,
    4 em regeneração, 5 água, 6 outro uso. Lido por HTTP Range, só os blocos do município.
  WRI / Google DeepMind, causas da perda de floresta 2001-2024 v1.2, 1 km (Zenodo 15366671, CC BY 4.0): banda 1 =
    causa dominante (1 a 7). Baixado uma vez (295 MB) para cache/drivers/.

O resto das camadas extras não precisa mais do Earth Engine:
  - cobertura, desmatamento, fogo do ano, idade e vigor do pasto: API da Plataforma MapBiomas (raiz_mapbiomas.py);
  - idade e incremento da vegetação secundária, altura e uGPP do pasto: YbYrá e GPW direto (raiz_direto.py);
  - histórico de fogo (1985-2024) e de perdas da secundária (YbYrá 1987-2024): ficam como foram exportados uma vez
    (extras_<mun>.csv); a cada ano novo, o fogo e a supressão de secundária do ano vêm da API (colunas mb_*).
Saída: saida/<UF>/extras_direto_<mun>.csv (cod_imovel, tmf_classe, tmf_floresta_pct, tmf_regeneracao_pct,
  causa_perda). Retoma de onde parou.
"""
import os, sys, glob, ast, warnings
os.environ.update(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_LIST', CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif',
                  GDAL_HTTP_MULTIRANGE='YES', GDAL_HTTP_MERGE_CONSECUTIVE_RANGES='YES', VSI_CACHE='TRUE',
                  GDAL_HTTP_MAX_RETRY='4', GDAL_HTTP_RETRY_DELAY='5')
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd, geopandas as gpd, requests
from raiz_extras import geometria, zonal_janela, limita_memoria

TMF_BASE = 'https://data.source.coop/epoch/jrc-tmf'
TMF_ANO = int(os.environ.get('RAIZ_TMF_ANO', 2025))
DRIVERS_URL = 'https://zenodo.org/api/records/15366671/files/drivers_forest_loss_1km_2001_2024_v1_2.tif/content'
DRIVERS = 'cache/drivers/drivers_forest_loss_1km_2001_2024_v1_2.tif'
CAUSAS = {1: 'agricultura permanente', 2: 'commodities', 3: 'agricultura itinerante', 4: 'extração de madeira',
          5: 'incêndio', 6: 'assentamento e infraestrutura', 7: 'perturbação natural'}


def tmf_tiles():
    f = 'cache/tmf/AnnualChange_stac.parquet'
    if not os.path.exists(f):
        os.makedirs(os.path.dirname(f), exist_ok=True)
        r = requests.get(f'{TMF_BASE}/stac/AnnualChange_stac.parquet', timeout=120); r.raise_for_status()
        open(f + '.tmp', 'wb').write(r.content); os.replace(f + '.tmp', f)
    t = gpd.read_parquet(f)
    t = t[t.id.str.endswith(f'AnnualChange_{TMF_ANO}')].copy()
    a = t.assets.apply(lambda x: ast.literal_eval(x) if isinstance(x, str) else x)
    t['href'] = a.apply(lambda x: x['AnnualChange']['href'])
    return t


def drivers():
    if not os.path.exists(DRIVERS):
        os.makedirs(os.path.dirname(DRIVERS), exist_ok=True)
        with requests.get(DRIVERS_URL, stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(DRIVERS + '.tmp', 'wb') as f:
                for b in r.iter_content(1 << 22): f.write(b)
        os.replace(DRIVERS + '.tmp', DRIVERS)
    return DRIVERS


def tmf(g, tiles):
    """Classe dominante e % de floresta (1+2) e de regeneração (4) do TMF por imóvel; imóvel em dois blocos soma."""
    acc = {}
    caixa = g.union_all().envelope
    for _, tl in tiles[tiles.intersects(caixa)].iterrows():
        b = tl.geometry.bounds
        sub = g.cx[b[0]:b[2], b[1]:b[3]]
        if len(sub) == 0: continue
        d = zonal_janela('/vsicurl/' + tl.href, sub, ('classes',), include_cols=['cod_imovel'])
        for _, row in d.iterrows():
            a = acc.setdefault(row.cod_imovel, np.zeros(7))
            for c in range(1, 7): a[c] += row.get(f'c{c}', 0) or 0
    out = []
    for k, a in acc.items():
        n = a[1:].sum()
        out.append({'cod_imovel': k, 'tmf_classe': int(a[1:].argmax() + 1) if n else np.nan,
                    'tmf_floresta_pct': round(100 * (a[1] + a[2]) / n, 1) if n else np.nan,
                    'tmf_regeneracao_pct': round(100 * a[4] / n, 1) if n else np.nan})
    return pd.DataFrame(out, columns=['cod_imovel', 'tmf_classe', 'tmf_floresta_pct', 'tmf_regeneracao_pct'])


def causa(g, arq):
    d = zonal_janela(arq, g, ('majority',), include_cols=['cod_imovel'])  # banda 1: causa dominante (255 = sem dado)
    col = 'band_1_majority' if 'band_1_majority' in d else 'majority'
    return d[['cod_imovel', col]].rename(columns={col: 'causa_perda'})


def municipio(uf, cod, pasta, tiles, arq):
    g = geometria(uf, cod, pasta).to_crs(4326).reset_index(drop=True)
    t = pd.DataFrame({'cod_imovel': g.cod_imovel.values})
    t = t.merge(tmf(g, tiles), on='cod_imovel', how='left')
    t = t.merge(causa(g, arq), on='cod_imovel', how='left')
    return t


def main():
    limita_memoria()
    uf = sys.argv[1].upper(); pasta = f'saida/{uf}'
    so = [int(x) for x in sys.argv[2:]]
    cods = so or sorted(int(os.path.basename(p)[8:-4]) for p in glob.glob(f'{pasta}/imoveis_*.csv'))
    tiles, arq = tmf_tiles(), drivers()
    print(f'{uf}: {len(cods)} municípios (TMF {TMF_ANO}, causas da perda v1.2)', flush=True)
    for i, cod in enumerate(cods, 1):
        f = f'{pasta}/extras_direto_{cod}.csv'
        if os.path.exists(f) and not so: continue
        try:
            t = municipio(uf, cod, pasta, tiles, arq); t.to_csv(f + '.tmp', index=False); os.replace(f + '.tmp', f)
            print(f'[{i}/{len(cods)}] {cod}: {len(t)} imóveis', flush=True)
        except Exception as ex:
            print(f'[{i}/{len(cods)}] {cod}: ERRO {ex}', flush=True)


if __name__ == '__main__':
    main()
