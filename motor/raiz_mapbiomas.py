"""
Raíz: MapBiomas por imóvel SEM Earth Engine, pela API oficial da Plataforma MapBiomas (rodada 9, testada em 12/11/2026).

Uso:
  python raiz_mapbiomas.py PA            # todos os municípios já rodados em saida/PA/
  python raiz_mapbiomas.py PA 1504950    # um município

Como funciona: pede à plataforma, de uma vez, a exportação em GeoTIFF de cada tema para o ESTADO inteiro (sem login;
cabeçalho tenant-id: mapbiomas; estado = categoria 214). São 5 pedidos por estado (135 no Brasil), em vez de 5 por
município (cada pedido leva de segundos a cerca de 15 min na fila deles). Baixa uma vez para cache/mapbiomas/ e soma
por imóvel lendo só a janela de cada grupo de imóveis (raiz_extras.zonal_janela). Cada exportação fica disponível por
1 ano do lado deles.
A idade da vegetação secundária NÃO vem daqui (a exportação falha do lado deles); ela vem do YbYrá (raiz_direto.py).

Saída: saida/<UF>/mapbiomas_<mun>.csv (colunas em docs/colunas.md, prefixo mb_). Retoma de onde parou.
"""
import os, sys, glob, json, time, math, zipfile, io, warnings, unicodedata
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests, numpy as np, pandas as pd
from raiz_extras import geometria, zonal_janela, limita_memoria

API = 'https://prd.plataforma.mapbiomas.org/api/v1/brazil'
H = {'tenant-id': 'mapbiomas', 'User-Agent': 'raiz-motor/1.0'}
CAT_MUNICIPIO = 230
CAT_ESTADO = 214
NOME_UF = {'AC': 'Acre', 'AL': 'Alagoas', 'AP': 'Amapá', 'AM': 'Amazonas', 'BA': 'Bahia', 'CE': 'Ceará',
    'DF': 'Distrito Federal', 'ES': 'Espírito Santo', 'GO': 'Goiás', 'MA': 'Maranhão', 'MT': 'Mato Grosso',
    'MS': 'Mato Grosso do Sul', 'MG': 'Minas Gerais', 'PA': 'Pará', 'PB': 'Paraíba', 'PR': 'Paraná', 'PE': 'Pernambuco',
    'PI': 'Piauí', 'RJ': 'Rio de Janeiro', 'RN': 'Rio Grande do Norte', 'RS': 'Rio Grande do Sul', 'RO': 'Rondônia',
    'RR': 'Roraima', 'SC': 'Santa Catarina', 'SP': 'São Paulo', 'SE': 'Sergipe', 'TO': 'Tocantins'}
ANO = int(os.environ.get('RAIZ_MB_ANO', 2025))
CACHE = 'cache/mapbiomas'
TEMAS = {  # nome: (chave do subtema, ano)
    'cobertura': ('coverage_coverage-30m-droufo', ANO),
    'desmat': ('desmatamento-copia-12xxov_annual-c5i7xj', ANO),
    'fogo': ('fogo-copia-1h7mac_monthly-433exq', ANO),
    'pasto_idade': ('pastagem-copia-0dzt61_idade-da-pastagem-drixus', ANO),
    'pasto_vigor': ('pastagem-copia-0dzt61_condicao-de-vigor-loj9p9', ANO),
}
# Coleção 11, cobertura: grupos de classes
FLORESTA = {3, 4, 5, 6, 49}
PASTO = {15}
AGRICULTURA = {18, 19, 20, 21, 35, 36, 39, 40, 41, 46, 47, 48, 62}
SILVICULTURA = {9}
# desmatamento e vegetação secundária (Col. 11 v5): 1 antrópico, 2 vegetação primária, 3 vegetação secundária,
# 4 supressão de primária, 5 recuperação para secundária, 6 supressão de secundária, 7 outras transições
# (conferido em 12/11/2026 na legenda da própria API, /legends/by/key/deforestation-omgdf4: 4 e 6 são as supressões;
#  no Pará, a classe 4 soma cerca de 190 mil ha em 2025, coerente com o PRODES)


def _get(url, **kw):
    for t in range(5):
        try:
            r = requests.get(url, headers=H, timeout=120, **kw)
            if r.status_code < 500: return r
        except requests.RequestException: pass
        time.sleep(10 * (t + 1))
    raise RuntimeError(f'falhou: {url}')


def territorio(nome, uf, cod):
    """id do município na plataforma (categoria 230), conferindo nome e UF."""
    f = f'{CACHE}/territorios.json'
    tab = json.load(open(f)) if os.path.exists(f) else {}
    if str(cod) in tab: return tab[str(cod)]
    s = unicodedata.normalize('NFKD', nome).encode('ascii', 'ignore').decode()
    for termo in (nome, s):
        r = _get(f'{API}/territories/search/{requests.utils.quote(termo)}').json()
        for t in r.get('territories', []):
            if t['categoryId'] == CAT_MUNICIPIO and t['name'].endswith(f' - {uf}'):
                tab[str(cod)] = t['id']; os.makedirs(CACHE, exist_ok=True); json.dump(tab, open(f, 'w'))
                return t['id']
    raise RuntimeError(f'município {nome}/{uf} não achado na plataforma')


def estado(uf):
    r = _get(f'{API}/territories?categoryId={CAT_ESTADO}&pageSize=40').json()
    for t in r['territories']:
        if t['name'] == NOME_UF[uf]: return t['id']
    raise RuntimeError(f'estado {uf} não achado na plataforma')


def exporta_uf(uf, espera=6 * 3600):
    """Pede todos os temas do estado de uma vez, espera e baixa. Devolve {tema: caminho do GeoTIFF}."""
    arq = {k: f'{CACHE}/{uf}/{uf}_{k}_{ano}.tif' for k, (ch, ano) in TEMAS.items()}
    falta = {k: v for k, v in TEMAS.items() if not os.path.exists(arq[k])}
    if not falta: return arq
    tid = estado(uf); pend = {}
    for k, (ch, ano) in falta.items():
        r = requests.post(f'{API}/maps/exports', headers=H, timeout=120,
                          json={'territoryId': tid, 'subthemeKey': ch, 'years': [ano], 'exportType': 'range'})
        r.raise_for_status(); pend[k] = r.json()['exports'][0]['id']
    t0 = time.time()
    while pend:
        for k, eid in list(pend.items()):
            e = _get(f'{API}/maps/exports/{eid}').json()
            if e['status'] == 'READY':
                b = _get(f'{API}/maps/exports/{eid}/download', allow_redirects=True).content
                if b[:2] == b'PK':  # às vezes vem em ZIP com o .tif dentro
                    z = zipfile.ZipFile(io.BytesIO(b)); b = z.read([n for n in z.namelist() if n.endswith('.tif')][0])
                os.makedirs(os.path.dirname(arq[k]), exist_ok=True)
                open(arq[k] + '.tmp', 'wb').write(b); os.replace(arq[k] + '.tmp', arq[k])
                print(f'  {uf} {k}: pronto em {time.time() - t0:.0f} s, {len(b) / 1e6:.0f} MB', flush=True); del pend[k]
            elif e['status'] in ('FAILED', 'EXPIRED'):
                raise RuntimeError(f'{uf} {k}: {e.get("errorMessage")}')
        if pend:
            if time.time() - t0 > espera: raise RuntimeError(f'{uf}: {list(pend)} passaram de {espera} s na fila')
            time.sleep(30)
    return arq


def ha_pixel(lat, res=0.00026949458523585647):
    m = res * 111320.0
    return m * m * np.cos(np.radians(lat)) / 1e4


def por_imovel(uf, cod, pasta, arq):
    g = geometria(uf, cod, pasta).to_crs(4326).reset_index(drop=True)
    hp = ha_pixel(g.geometry.centroid.y.values)
    t = pd.DataFrame({'cod_imovel': g.cod_imovel.values})
    a = f'_{ANO}'
    c = zonal_janela(arq['cobertura'], g, ('classes', 'majority'))
    soma = lambda cls: sum(c.get(f'c{x}', 0) for x in cls) * hp
    t['mb_floresta' + a + '_ha'] = np.round(soma(FLORESTA), 1)
    t['mb_pasto' + a + '_ha'] = np.round(soma(PASTO), 1)
    t['mb_agricultura' + a + '_ha'] = np.round(soma(AGRICULTURA), 1)
    t['mb_silvicultura' + a + '_ha'] = np.round(soma(SILVICULTURA), 1)
    t['mb_classe_principal' + a] = c['majority']
    d = zonal_janela(arq['desmat'], g, ('classes',))
    for x, n in [(4, 'mb_supressao_primaria'), (6, 'mb_supressao_secundaria'), (5, 'mb_recuperacao_secundaria'), (3, 'mb_veg_secundaria')]:
        t[n + a + '_ha'] = np.round(d.get(f'c{x}', 0) * hp, 1)
    f = zonal_janela(arq['fogo'], g, ('count', 'majority'))
    t['mb_fogo' + a + '_ha'] = np.round(f['count'] * hp, 1); t['mb_fogo_mes_principal' + a] = f['majority']
    p = zonal_janela(arq['pasto_idade'], g, ('mean', 'max'))
    t['mb_pasto_idade_anos_media'] = np.where(p['mean'] >= 200, (p['mean'] - 200).round(1), np.nan)
    v = zonal_janela(arq['pasto_vigor'], g, ('majority',))
    t['mb_pasto_vigor_principal'] = v['majority']
    return t


def main():
    limita_memoria()
    uf = sys.argv[1].upper(); pasta = f'saida/{uf}'
    cods = [int(sys.argv[2])] if len(sys.argv) > 2 else sorted(int(os.path.basename(p)[8:-4]) for p in glob.glob(f'{pasta}/imoveis_*.csv'))
    print(f'{uf}: {len(cods)} municípios, ano {ANO}', flush=True)
    arq = exporta_uf(uf)
    for i, cod in enumerate(cods, 1):
        out = f'{pasta}/mapbiomas_{cod}.csv'
        if os.path.exists(out): continue
        try:
            nome = pd.read_csv(f'{pasta}/imoveis_{cod}.csv', usecols=['municipio'], nrows=1).municipio.iat[0]
            t0 = time.time(); t = por_imovel(uf, cod, pasta, arq)
            t.to_csv(out + '.tmp', index=False); os.replace(out + '.tmp', out)
            print(f'[{i}/{len(cods)}] {cod} {nome}: {len(t)} imóveis, {t.filter(like="mb_supressao_primaria").sum().iat[0]:.0f} ha de supressão de primária em {ANO}, {time.time() - t0:.0f} s', flush=True)
        except Exception as ex:
            print(f'[{i}/{len(cods)}] {cod}: ERRO {ex}', flush=True)


if __name__ == '__main__':
    main()
