"""
Raíz: filtros territoriais extras por imóvel (territórios quilombolas, terras indígenas da FUNAI em todas as fases,
unidades de conservação do CNUC por grupo). Complementa o funil (raiz_estado.py), que usa TI e UC do TerraBrasilis.

Uso:
  python raiz_filtros.py PA          # todos os municípios já rodados em saida/PA/

Fontes (Ipea/geobr, sem chave, baixadas uma vez para cache/):
  quilombolalands_202605.parquet     territórios quilombolas reconhecidos pelo INCRA (mai/2026)
  indigenouslands_2025.parquet       terras indígenas da FUNAI (regularizada, homologada, declarada, delimitada, em estudo)
  conservationunits_202503.parquet   CNUC/MMA (mar/2025), com grupo (Proteção Integral ou Uso Sustentável) e categoria
Saída:
  saida/<UF>/filtros_<mun>.csv       cod_imovel, quilombo_ha, ti_funai_ha, ti_fase, uc_protecao_integral_ha,
                                     uc_uso_sustentavel_ha, uc_apa_ha, filtro_territorial
filtro_territorial:
  bloqueio   >1 ha em quilombo, TI (qualquer fase) ou UC de proteção integral: fora da vitrine de carbono
  atencao    >1 ha em UC de uso sustentável que não seja APA (RESEX, RDS, FLONA): depende do plano de manejo
  ok         resto (APA não impede restauração privada, só entra como informação)
Retoma de onde parou.
"""
import sys, os, glob, time, warnings, requests
import pandas as pd, geopandas as gpd
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import raiz_estado as R
from raiz_extras import geometria

BASE = 'https://www.ipea.gov.br/geobr/data_v2.0.0/'
ARQ = {'quilombo': 'quilombolalands_202605.parquet', 'ti': 'indigenouslands_2025.parquet', 'uc': 'conservationunits_202503.parquet'}
CAMADAS = {}


def baixar(k, tentativas=6):
    """Baixa uma vez para cache/ o arquivo do geobr, com espera crescente se o servidor do Ipea recusar."""
    f = f'cache/{ARQ[k]}'
    if os.path.exists(f): return f
    os.makedirs('cache', exist_ok=True)
    for i in range(tentativas):
        try:
            print('baixando', ARQ[k], flush=True)
            with requests.get(BASE + ARQ[k], stream=True, timeout=1800) as r, open(f + '.tmp', 'wb') as o:
                r.raise_for_status()
                for ch in r.iter_content(1 << 20): o.write(ch)
            os.replace(f + '.tmp', f); return f
        except Exception as ex:
            if i == tentativas - 1: raise
            print(f'   geobr {ARQ[k]}: tentativa {i + 1} falhou ({str(ex)[:120]}); espero {30 * 2 ** i} s', flush=True)
            time.sleep(30 * 2 ** i)


def camada(k):
    if k not in CAMADAS:
        CAMADAS[k] = gpd.read_parquet(baixar(k)).to_crs(4674)
    return CAMADAS[k]


def filtros(g):
    g = g.to_crs(4674)
    x0, y0, x1, y1 = g.total_bounds
    base = R.fix(g[['cod_imovel', 'geometry']], sub=False)
    t = pd.DataFrame({'cod_imovel': g.cod_imovel.values}).set_index('cod_imovel')
    q = camada('quilombo').cx[x0:x1, y0:y1]
    ti = camada('ti').cx[x0:x1, y0:y1]
    uc = camada('uc').cx[x0:x1, y0:y1]
    t['quilombo_ha'] = R.ov(base, R.fix(q)) if len(q) else 0
    t['ti_funai_ha'] = R.ov(base, R.fix(ti)) if len(ti) else 0
    if len(ti):
        j = gpd.sjoin(base, ti[['fase_ti', 'geometry']].to_crs(R.A), predicate='intersects')
        t['ti_fase'] = j.groupby('cod_imovel').fase_ti.first()
    else:
        t['ti_fase'] = ''
    pi = uc[uc.grupo == 'Proteção Integral']
    apa = uc[uc.categoria == 'Área de Proteção Ambiental']
    us = uc[(uc.grupo == 'Uso Sustentável') & (uc.categoria != 'Área de Proteção Ambiental')]
    t['uc_protecao_integral_ha'] = R.ov(base, R.fix(pi)) if len(pi) else 0
    t['uc_uso_sustentavel_ha'] = R.ov(base, R.fix(us)) if len(us) else 0
    t['uc_apa_ha'] = R.ov(base, R.fix(apa)) if len(apa) else 0
    t = t.fillna({'quilombo_ha': 0, 'ti_funai_ha': 0, 'uc_protecao_integral_ha': 0, 'uc_uso_sustentavel_ha': 0, 'uc_apa_ha': 0, 'ti_fase': ''})
    bloq = (t.quilombo_ha > 1) | (t.ti_funai_ha > 1) | (t.uc_protecao_integral_ha > 1)
    t['filtro_territorial'] = 'ok'
    t.loc[t.uc_uso_sustentavel_ha > 1, 'filtro_territorial'] = 'atencao'
    t.loc[bloq, 'filtro_territorial'] = 'bloqueio'
    for c in ['quilombo_ha', 'ti_funai_ha', 'uc_protecao_integral_ha', 'uc_uso_sustentavel_ha', 'uc_apa_ha']:
        t[c] = t[c].round(1)
    return t.reset_index()


def main():
    uf = sys.argv[1].upper()
    pasta = f'saida/{uf}'
    cods = sorted(int(os.path.basename(p)[8:-4]) for p in glob.glob(f'{pasta}/imoveis_*.csv'))
    print(f'{uf}: {len(cods)} municípios')
    for i, cod in enumerate(cods, 1):
        f = f'{pasta}/filtros_{cod}.csv'
        if os.path.exists(f): continue
        try:
            t = filtros(geometria(uf, cod, pasta))
            t.to_csv(f + '.tmp', index=False); os.replace(f + '.tmp', f)
            print(f'[{i}/{len(cods)}] {cod}: {len(t)} imóveis, {int((t.filtro_territorial == "bloqueio").sum())} bloqueio, '
                  f'{int((t.filtro_territorial == "atencao").sum())} atenção', flush=True)
        except Exception as ex:
            print(f'[{i}/{len(cods)}] {cod}: ERRO {ex}', flush=True)


if __name__ == '__main__':
    main()
