"""
Raíz: camadas lidas DIRETO dos arquivos públicos, sem Earth Engine (rodada 8, ideia do Herbie: ler só os blocos
do município por HTTP Range com GDAL /vsicurl).

Uso:
  python raiz_direto.py PA          # todos os municípios já rodados em saida/PA/

Fontes (sem chave):
  YbYrá-BR v8.1 (Source Cooperative): idade e incremento da vegetação secundária, 2024
  Global Pasture Watch (OpenGeoHub): altura da vegetação baixa e uGPP (produtividade do pasto), 2024
  MapBiomas cobertura e Fogo: o bucket público responde 403 (acesso anônimo fechado em 12/11/2026),
  então seguem no Earth Engine.
Saída:
  saida/<UF>/direto_<mun>.csv   cod_imovel, sec_area_ha, sec_idade_media (só onde há vegetação secundária),
                                sec_nova_ha (rebrotou em 2024), gpw_altura_m, gpw_ugpp
Retoma de onde parou. Cerca de 20 s por município.
"""
import os, sys, glob, math, warnings
os.environ.update(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_LIST', CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif',
                  GDAL_HTTP_MULTIRANGE='YES', GDAL_HTTP_MERGE_CONSECUTIVE_RANGES='YES', VSI_CACHE='TRUE',
                  GDAL_HTTP_MAX_RETRY='4', GDAL_HTTP_RETRY_DELAY='5')
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
from raiz_extras import geometria, zonal_janela, limita_memoria

ANO = 2024
YB = 'https://data.source.coop/ybyra-br/secondary-forest/{p}/ybyra_secondary_forest_{p}_brazil_v8_1_{a}.tif'
GPW = 'https://s3.opengeohub.org/gpw/arco/gpw_{p}_30m_s_{a}0101_{a}1231_go_epsg.4326_v1.tif'
U = {'idade': '/vsicurl/' + YB.format(p='age', a=ANO), 'incremento': '/vsicurl/' + YB.format(p='increment', a=ANO),
     'altura': '/vsicurl/' + GPW.format(p='short.veg.height_egbt_m', a=ANO), 'ugpp': '/vsicurl/' + GPW.format(p='ugpp_lue.model_m', a=ANO)}
RES = {'idade': 0.00026949458523585647, 'incremento': 0.00026949458523585647}


def ha_por_pixel(lat, res):
    m = res * 111320.0
    return m * m * math.cos(math.radians(lat)) / 1e4


def direto(g):
    g = g.to_crs(4326).reset_index(drop=True)
    lat = g.geometry.centroid.y.values
    t = pd.DataFrame({'cod_imovel': g.cod_imovel.values})
    for k in ['idade', 'incremento']:
        d = zonal_janela(U[k], g, ('mean', 'count'))  # nodata = 0: só pixels com vegetação secundária
        area = d['count'].values * [ha_por_pixel(x, RES[k]) for x in lat]
        if k == 'idade':
            t['sec_area_ha'] = area.round(1); t['sec_idade_media'] = d['mean'].round(1)
        else:
            t['sec_nova_ha'] = area.round(1)
    for k, c in [('altura', 'gpw_altura_m'), ('ugpp', 'gpw_ugpp')]:
        d = zonal_janela(U[k], g, ('mean',))
        t[c] = d['mean'].round(2)
    return t


def main():
    limita_memoria()
    uf = sys.argv[1].upper(); pasta = f'saida/{uf}'
    cods = sorted(int(os.path.basename(p)[8:-4]) for p in glob.glob(f'{pasta}/imoveis_*.csv'))
    print(f'{uf}: {len(cods)} municípios', flush=True)
    for i, cod in enumerate(cods, 1):
        f = f'{pasta}/direto_{cod}.csv'
        if os.path.exists(f): continue
        try:
            t = direto(geometria(uf, cod, pasta)); t.to_csv(f + '.tmp', index=False); os.replace(f + '.tmp', f)
            print(f'[{i}/{len(cods)}] {cod}: {len(t)} imóveis, {t.sec_area_ha.sum():.0f} ha de vegetação secundária', flush=True)
        except Exception as ex:
            print(f'[{i}/{len(cods)}] {cod}: ERRO {ex}', flush=True)


if __name__ == '__main__':
    main()
