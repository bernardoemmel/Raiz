"""
Raíz: funil de fazendas por município/estado (Brasil inteiro: PRODES de todos os biomas + MapBiomas + MapBiomas Alerta).

Uso:
  pip install geopandas pandas requests pyogrio
  python raiz_estado.py PA                 # todos os municípios do Pará
  python raiz_estado.py PA 1507300 1505502 # só estes municípios (códigos IBGE)

Saídas (pasta saida/<UF>/):
  resumo_<UF>.csv           uma linha por município com o funil
  imoveis_<mun>.csv         uma linha por imóvel (sem CPF/CNPJ), com a coluna 'frente'
  certidoes_<mun>.csv       para cada imóvel da frente 'carbono': cartório (CNS) e número
                            da matrícula das parcelas SIGEF, prontos para pedir a certidão
                            no ONR/SAEC (registradores.onr.org.br); quem pede e paga é o investidor
Regeneração viável (opcional, recomendado): coloque em mapbiomas/ os GeoTIFFs exportados do
Earth Engine (raiz_mapbiomas_<UF>*.tif, bandas cob2008, cob_atual, sec_idade). Imóvel da frente
'carbono' sem pasto a até 1 km de floresta (mata não volta sozinha) vira 'carbono_so_plantio'. Sem corte de tamanho.
Projetos de carbono já existentes: coloque na pasta projetos_carbono/ os mapas (KML, GeoJSON,
GPKG ou SHP) dos projetos registrados na Verra/Gold Standard da região (na página de cada
projeto, em documentos). Imóvel com >=10 ha dentro de um projeto sai da frente 'carbono'.
Retoma de onde parou: município com imoveis_<mun>.csv já pronto é pulado.

Funil:
  imoveis            CAR ativo/pendente/suspenso (IRU)
  sem_problema       sem embargo Ibama, terra indígena ou desmatamento PRODES após 2020
  def_RL             déficit de reserva legal >1 ha
  aptas_carbono      área aberta ALÉM da reserva legal (sem corte de tamanho: pequenas se agrupam)
  aptas_com_matricula  idem, com >=50% do CAR coberto por parcela SIGEF particular com matrícula
Regra de reserva: coluna RL80 (80%, floresta na Amazônia Legal) e RL50 (50%, áreas com ZEE).
A área "além da reserva" usa RL50 por padrão (conservador para o lado da oferta); troque em PCT_ALEM.
Ressalvas: CAR atual (não o de 2008); CARs se sobrepõem; hidrografia do PRODES só tem rios maiores.
APP: app_desmatada_ha (30 m) e app_escadinha_ha / app_recompor_ha (art. 61-A e 61-B, regras do GeoCAR, MIT).
"""
import sys, os, io, time, warnings, requests, pandas as pd, geopandas as gpd
from shapely import wkt
import numpy as np
warnings.filterwarnings('ignore')

A = "EPSG:5880"
PCT_ALEM = 50
AMZ = {'AC','AM','AP','MA','MT','PA','RO','RR','TO'}
CAR_WFS = "https://geoserver.car.gov.br/geoserver/sicar/wfs"
TB_WFS = "https://terrabrasilis.dpi.inpe.br/geoserver/ows"
SIGEF_WFS = "https://geoportal.incra.gov.br/geoserver/ows"
IBAMA_CSV = "https://stibamadadosabertosprd.blob.core.windows.net/dados-abertos/dados/TERMOS_DE_EMBARGO/TERMO_EMBARGO/termo_de_embargo.csv"
CACHE = "cache"; os.makedirs(CACHE, exist_ok=True)
PROJ_DIR = "projetos_carbono"


def projetos_carbono():
    """Lê os mapas de projetos de carbono existentes (Verra, Gold Standard) da pasta PROJ_DIR."""
    if not os.path.isdir(PROJ_DIR): return gpd.GeoDataFrame(geometry=[], crs=4674)
    gs = []
    for f in sorted(os.listdir(PROJ_DIR)):
        if f.lower().endswith(('.kml', '.geojson', '.json', '.gpkg', '.shp')):
            try:
                g = gpd.read_file(os.path.join(PROJ_DIR, f)); g['projeto'] = f; gs.append(g[['projeto', 'geometry']])
            except Exception as ex:
                print('  não li', f, ex)
    if not gs: return gpd.GeoDataFrame(geometry=[], crs=4674)
    g = pd.concat(gs); g = g[g.geom_type.isin(['Polygon', 'MultiPolygon'])]
    print(f'  {len(g)} polígonos de projetos de carbono em {PROJ_DIR}/')
    return gpd.GeoDataFrame(g, geometry='geometry', crs=g.crs or 4674)


PROJ = None
MB_DIR = "mapbiomas"
MB = {}


def mapbiomas(uf):
    if uf not in MB:
        import glob, rasterio
        fs = sorted(glob.glob(f'{MB_DIR}/raiz_mapbiomas_{uf}*.tif'))
        MB[uf] = [rasterio.open(f) for f in fs]
        print(f'  MapBiomas {uf}: {len(fs)} arquivo(s)' if fs else f'  sem MapBiomas para {uf} em {MB_DIR}/ (pulando regeneração)')
    return MB[uf]


def regeneracao(c, uf, min_ha=1):
    """Pasto, floresta, secundária e pasto a até 1 km de floresta (MapBiomas) nos imóveis 'carbono'."""
    rs = mapbiomas(uf)
    alvo = c[c.frente.isin(['carbono', 'regularizar_antes', 'assentamento_agrupado'])]
    if not rs or len(alvo) == 0: return c
    import numpy as np
    from rasterio.merge import merge
    from rasterio.features import geometry_mask
    from scipy.ndimage import distance_transform_edt
    pxha, pad = 0.09, 0.012
    g = alvo.to_crs(4326)
    for k in ['pasto_ha', 'secundaria_ha', 'pasto_ate1km_ha']: c[k] = np.nan
    for cod, geom in g.geometry.items():
        x0, y0, x1, y1 = geom.bounds
        bb = (x0 - pad, y0 - pad, x1 + pad, y1 + pad)
        rs_ok = [r for r in rs if not (r.bounds.right < bb[0] or r.bounds.left > bb[2] or r.bounds.top < bb[1] or r.bounds.bottom > bb[3])]
        if not rs_ok: continue
        arr, tr = merge(rs_ok, bounds=bb, indexes=[2, 3])
        cob, sec = arr[0], arr[1]
        m = geometry_mask([geom], out_shape=cob.shape, transform=tr, invert=True)
        forest = (cob == 3) | (cob == 4)
        d = distance_transform_edt(~forest) * 30
        pasto = (cob == 15) & m
        c.loc[cod, 'pasto_ha'] = pasto.sum() * pxha
        c.loc[cod, 'secundaria_ha'] = ((sec > 0) & m).sum() * pxha
        c.loc[cod, 'pasto_ate1km_ha'] = (pasto & (d <= 1000)).sum() * pxha
    c['carbono_ha'] = np.minimum(c.alem_RL_ha, c.pasto_ate1km_ha.fillna(0))  # área além da RL com mata capaz de voltar sozinha
    c.loc[(c.frente == 'carbono') & (c.pasto_ate1km_ha < min_ha), 'frente'] = 'carbono_so_plantio'
    return c


import ssl
from requests.adapters import HTTPAdapter


class LegacyTLS(HTTPAdapter):
    """O servidor do CAR usa TLS antigo; o Python novo recusa sem isto."""
    def init_poolmanager(self, *a, **k):
        ctx = ssl.create_default_context()
        ctx.set_ciphers('DEFAULT:@SECLEVEL=1')
        ctx.options |= getattr(ssl, 'OP_LEGACY_SERVER_CONNECT', 0x4)
        k['ssl_context'] = ctx
        return super().init_poolmanager(*a, **k)

    def proxy_manager_for(self, proxy, **k):
        ctx = ssl.create_default_context()
        ctx.set_ciphers('DEFAULT:@SECLEVEL=1')
        ctx.options |= getattr(ssl, 'OP_LEGACY_SERVER_CONNECT', 0x4)
        k['ssl_context'] = ctx
        return super().proxy_manager_for(proxy, **k)


S = requests.Session(); S.mount('https://', LegacyTLS())


def get(url, params, tries=5, timeout=600):
    for i in range(tries):
        try:
            r = S.get(url, params=params, timeout=timeout)
            r.raise_for_status(); return r
        except Exception as e:
            print('   tentativa', i + 1, 'falhou:', str(e)[:120]); time.sleep((30 if '429' in str(e) else 2) * (2 ** i))
    raise RuntimeError('download falhou: ' + url)


def gj(r):
    g = gpd.read_file(io.BytesIO(r.content))
    return g if len(g) else gpd.GeoDataFrame(geometry=[], crs=4674)


def car_mun(uf, cod):
    out, start = [], 0
    while True:
        r = get(CAR_WFS, dict(service='WFS', version='2.0.0', request='GetFeature',
                typeNames=f'sicar:sicar_imoveis_{uf.lower()}', outputFormat='application/json',
                CQL_FILTER=f'cod_municipio_ibge={cod}', sortBy='cod_imovel', count=10000, startIndex=start))
        g = gj(r); out.append(g)
        if len(g) < 10000: break
        start += 10000
    g = pd.concat(out).drop_duplicates('cod_imovel')
    return g.set_crs(4674, allow_override=True)


def tb(layer, bbox, passo=0.5, ws='prodes-legal-amz'):
    """Baixa em blocos de 0,5 grau alinhados à grade (reaproveitados entre municípios vizinhos, com cache em disco)."""
    import numpy as np, math
    x0, y0, x1, y1 = bbox; partes = []
    os.makedirs(f'{CACHE}/tb', exist_ok=True)
    xs = np.arange(math.floor(x0 / passo) * passo, x1, passo)
    ys = np.arange(math.floor(y0 / passo) * passo, y1, passo)
    for xa in xs:
        for ya in ys:
            b = [round(xa, 4), round(ya, 4), round(xa + passo, 4), round(ya + passo, 4)]
            f = f"{CACHE}/tb/{ws.replace(':','_')}__{layer}__{b[0]}_{b[1]}.parquet"
            if os.path.exists(f):
                partes.append(gpd.read_parquet(f)); continue
            time.sleep(1)
            r = get(TB_WFS, dict(service='WFS', version='1.0.0', request='GetFeature',
                    typeName=f'{ws}:{layer}', outputFormat='application/json',
                    bbox=','.join(map(str, b)) + ',EPSG:4674'))
            g = gj(r)
            try: tmp = f'{f}.{os.getpid()}.tmp'; g.to_parquet(tmp); os.replace(tmp, f)
            except Exception: pass
            partes.append(g)
    g = pd.concat(partes) if partes else gpd.GeoDataFrame(geometry=[], crs=4674)
    if len(g) == 0: return gpd.GeoDataFrame(geometry=[], crs=4674)
    k = 'uuid' if 'uuid' in g else ('fid' if 'fid' in g else None)
    g = g.drop_duplicates(k) if k else g[~g.geometry.to_wkb().duplicated()]
    return gpd.GeoDataFrame(g, geometry='geometry').set_crs(4674, allow_override=True)


def sigef(bbox):
    x0, y0, x1, y1 = bbox; out, start = [], 0
    while True:
        r = get(SIGEF_WFS, dict(service='WFS', version='2.0.0', request='GetFeature',
                typeNames='geonode:sigef_geo', outputFormat='application/json', srsName='EPSG:4674',
                count=5000, startIndex=start, sortBy='parcela_codigo',
                bbox=f'{y0},{x0},{y1},{x1},urn:ogc:def:crs:EPSG::4674'))
        g = gj(r); out.append(g)
        if len(g) < 5000: break
        start += 5000
    g = pd.concat(out)
    return g.drop_duplicates('parcela_codigo') if len(g) else g


def embargos():
    """CSV do Ibama com pedido condicional (rodada 8): guarda o ETag; a cada 20 h pergunta 'mudou?' com
    If-None-Match. 304 = não baixa nada. 200 = baixa, troca o arquivo e grava no changelog quantos termos
    entraram, saíram ou mudaram (pela DAT_ULT_ALTERACAO / DAT_ULT_ALTER_GEOM)."""
    p, pe = f'{CACHE}/termo_de_embargo.csv', f'{CACHE}/termo_de_embargo.etag'
    ler = lambda f: pd.read_csv(f, sep=';', dtype=str, encoding='utf-8-sig', on_bad_lines='skip')
    velho = os.path.exists(p) and time.time() - os.path.getmtime(p) > 20 * 3600
    if not os.path.exists(p) or velho:
        h = {'If-None-Match': open(pe).read().strip()} if (os.path.exists(p) and os.path.exists(pe)) else {}
        try:
            with S.get(IBAMA_CSV, stream=True, timeout=1800, headers=h) as r:
                if r.status_code == 304:
                    os.utime(p); print('embargos do Ibama: sem mudança (304)')
                else:
                    r.raise_for_status(); print('baixando embargos do Ibama (~200 MB)...')
                    tmp = f'{p}.{os.getpid()}.tmp'
                    with open(tmp, 'wb') as f:
                        for ch in r.iter_content(1 << 20): f.write(ch)
                    if os.path.exists(p):
                        try:
                            k = ['SEQ_TAD', 'DAT_ULT_ALTERACAO', 'DAT_ULT_ALTER_GEOM']
                            a, b = ler(p)[k].fillna(''), ler(tmp)[k].fillna('')
                            ia, ib = set(a.SEQ_TAD), set(b.SEQ_TAD)
                            mud = len(set(map(tuple, b.values)) - set(map(tuple, a.values))) - len(ib - ia)
                            linha = f"{time.strftime('%Y-%m-%d %H:%M')},{r.headers.get('ETag','')},{len(ib - ia)},{len(ia - ib)},{mud}\n"
                            novo = not os.path.exists(f'{CACHE}/embargos_changelog.csv')
                            with open(f'{CACHE}/embargos_changelog.csv', 'a') as f:
                                if novo: f.write('data,etag,novos,sumiram,mudaram\n')
                                f.write(linha)
                            print('embargos do Ibama: ' + linha.strip())
                        except Exception as ex: print('changelog embargos falhou:', ex)
                    os.replace(tmp, p)
                    if r.headers.get('ETag'): open(pe, 'w').write(r.headers['ETag'])
        except Exception as ex:
            if not os.path.exists(p): raise
            print('embargos do Ibama: servidor falhou, usando a cópia guardada:', ex)
    return ler(p)


def subdividir(geom, maxv=512):
    """Corta um polígono gigante (ex.: mancha de desmatamento acumulado com 150 mil vértices) em pedaços
    retangulares de até maxv vértices, como o ST_Subdivide do PostGIS. A soma das áreas não muda, mas cada
    interseção com um imóvel fica barata."""
    import shapely
    from shapely.geometry import box
    out, pilha = [], [geom]
    while pilha:
        g = pilha.pop()
        if g.is_empty: continue
        if shapely.get_num_coordinates(g) <= maxv: out.append(g); continue
        x0, y0, x1, y1 = g.bounds
        if x1 - x0 >= y1 - y0: xm = (x0 + x1) / 2; caixas = [box(x0, y0, xm, y1), box(xm, y0, x1, y1)]
        else: ym = (y0 + y1) / 2; caixas = [box(x0, y0, x1, ym), box(x0, ym, x1, y1)]
        pilha += [shapely.intersection(g, b) for b in caixas]
    return out


def fix(g, sub=True):
    """Projeta, conserta só as geometrias inválidas (antes: buffer(0) em todas) e subdivide as gigantes."""
    import shapely
    g = g.to_crs(A)
    if len(g):
        bad = ~g.is_valid
        if bad.any(): g.loc[bad, 'geometry'] = g.loc[bad].buffer(0)
        if sub:
            big = shapely.get_num_coordinates(g.geometry.values) > 512
            if big.any():
                g = g.copy(); g['geometry'] = [subdividir(x) if b else x for x, b in zip(g.geometry.values, big)]
                g = g.explode('geometry', ignore_index=True).set_geometry('geometry').set_crs(A, allow_override=True)
    return g[~g.is_empty]


def ov(base, layer):
    """Hectares de 'layer' dentro de cada imóvel: pares pelo índice espacial + interseção vetorizada
    (mesma conta do gpd.overlay, sem montar a tabela de polígonos; ~5x mais rápido)."""
    import shapely
    if len(layer) == 0 or len(base) == 0: return pd.Series(dtype=float)
    lg = layer.geometry.values
    ib, il = gpd.GeoSeries(lg, crs=A).sindex.query(base.geometry.values, predicate='intersects')
    if len(ib) == 0: return pd.Series(dtype=float)
    a = shapely.area(shapely.intersection(base.geometry.values[ib], lg[il])) / 1e4
    return pd.Series(a).groupby(base.cod_imovel.values[ib]).sum()


# PRODES por bioma (TerraBrasilis): cobre o Brasil inteiro, não só a Amazônia Legal
BIOMA_WS = {
    'Amazônia': ('prodes-amazon-nb', dict(yd='yearly_deforestation_biome', acc='accumulated_deforestation_2007_biome', nf='no_forest_biome',
                                          hy='hydrography_biome', ti='indigenous_area_amazon_biome', uc='conservation_units_amazon_biome')),
    'Cerrado': ('prodes-cerrado-nb', dict(yd='yearly_deforestation', acc='accumulated_deforestation_2000', nf=None, hy='hydrography',
                                         ti='indigenous_area_cerrado_biome', uc='conservation_units_cerrado_biome')),
    'Caatinga': ('prodes-caatinga-nb', dict(yd='yearly_deforestation', acc='accumulated_deforestation_2000', nf=None, hy='hydrography',
                                           ti='indigenous_area_caatinga_biome', uc='conservation_units_caatinga_biome')),
    'Mata Atlântica': ('prodes-mata-atlantica-nb', dict(yd='yearly_deforestation', acc='accumulated_deforestation_2000', nf=None, hy='hydrography',
                                                       ti='indigenous_area_mata_atlantica_biome', uc='conservation_units_mata_atlantica_biome')),
    'Pampa': ('prodes-pampa-nb', dict(yd='yearly_deforestation', acc='accumulated_deforestation_2000', nf=None, hy='hydrography',
                                     ti='indigenous_area_pampa_biome', uc='conservation_units_pampa_biome')),
    'Pantanal': ('prodes-pantanal-nb', dict(yd='yearly_deforestation', acc='accumulated_deforestation_2000', nf=None, hy='hydrography',
                                           ti='indigenous_area_pantanal_biome', uc='conservation_units_pantanal_biome')),
}
AMZ_LEGAL = ('prodes-legal-amz', dict(yd='yearly_deforestation', acc='accumulated_deforestation_2007', nf='no_forest', hy='hydrography',
                                      ti='indigenous_area_legal_amazon', uc='conservation_units_legal_amazon'))
BIOMAS = None


def biomas():
    global BIOMAS
    if BIOMAS is None:
        f = 'cache/biomas_brasil.gpkg'
        if os.path.exists(f):
            BIOMAS = gpd.read_file(f)
        else:
            r = get(TB_WFS, dict(service='WFS', version='1.0.0', request='GetFeature', typeName='prodes-brasil-nb:biomas_brasil',
                                 outputFormat='application/json'))
            BIOMAS = gpd.GeoDataFrame(gj(r), geometry='geometry').set_crs(4674, allow_override=True)[['bioma', 'geometry']]
            BIOMAS.to_file(f)
    return BIOMAS


def camadas(uf, bbox):
    """Baixa PRODES, terras indígenas, UCs, não floresta e hidrografia de todos os biomas que tocam o município."""
    from shapely.geometry import box
    bs = biomas(); toca = bs[bs.intersects(box(*bbox))].bioma.tolist()
    fontes = []
    if uf in AMZ: fontes.append(AMZ_LEGAL)
    fontes += [BIOMA_WS[b] for b in toca if b in BIOMA_WS and not (uf in AMZ and b == 'Amazônia')]
    out = {k: [] for k in ['yd', 'acc', 'nf', 'hy', 'ti', 'uc']}
    for ws, ls in fontes:
        for k, layer in ls.items():
            if layer: out[k].append(tb(layer, bbox, ws=ws))
    vazio = gpd.GeoDataFrame(geometry=[], crs=4674)
    res = {}
    for k, v in out.items():
        v = [x for x in v if len(x)]
        res[k] = gpd.GeoDataFrame(pd.concat(v, ignore_index=True), geometry='geometry', crs=4674) if v else vazio
        if len(res[k]): res[k] = res[k].cx[bbox[0]:bbox[2], bbox[1]:bbox[3]]  # blocos de 0,5 grau passam do município
    return res, toca


def pct_rl(uf, bioma):
    """Reserva legal (Código Florestal, art. 12): Amazônia Legal 80% floresta, 35% cerrado, 20% campos; fora dela 20%."""
    if uf in AMZ:
        return {'Amazônia': 80, 'Cerrado': 35}.get(bioma, 20)
    return 20


# Taxa de acúmulo de carbono da regeneração natural (floresta jovem, < 20 anos), em t C/ha/ano acima do solo.
# Amazônia: Heinrich et al. 2021 (Nature Communications): oeste 3,0; leste 1,3; sudeste 1,8.
# Outros biomas: valores provisórios (a calibrar com Requena Suarez 2019 / IPCC 2019 e Cook-Patton 2020).
TAXA_C = {'amz_oeste': 3.0, 'amz_leste': 1.3, 'amz_sudeste': 1.8,
          'Cerrado': 1.0, 'Mata Atlântica': 2.5, 'Caatinga': 0.6, 'Pantanal': 1.0, 'Pampa': 0.8}
RAIZ_PARTE_AEREA = 0.24   # raízes / parte aérea (IPCC 2019, floresta tropical úmida)


def regiao_carbono(uf, bioma, lat):
    if bioma == 'Amazônia':
        if uf in ('AC', 'AM', 'RR', 'RO'): return 'amz_oeste'
        if uf in ('MT', 'TO') or (uf in ('PA', 'MA') and lat < -5): return 'amz_sudeste'
        return 'amz_leste'
    return bioma


def carbono(c, uf):
    """t CO2 por ha por ano e total por ano em cada imóvel (área de carbono x taxa regional, com raízes).
    Desconto por fogo e por derrubada repetida (Heinrich: fogo corta até metade; 3+ derrubadas, -40%) entra quando
    as camadas extras do Earth Engine (fogo_anos, yb_perdas) estiverem no motor."""
    lat = gpd.GeoSeries(c.geometry, crs=A).representative_point().to_crs(4674).y
    reg = [regiao_carbono(uf, b, y) for b, y in zip(c.get('bioma', pd.Series('', index=c.index)), lat)]
    tc = pd.Series([TAXA_C.get(r, 1.0) for r in reg], index=c.index)
    c['regiao_carbono'] = reg
    c['taxa_tco2_ha_ano'] = (tc * (1 + RAIZ_PARTE_AEREA) * 44 / 12).round(2)
    area = c.carbono_ha if 'carbono_ha' in c else c.alem_RL_ha
    c['carbono_tco2_ano'] = (area * c.taxa_tco2_ha_ano).round(0)
    return c


AL_CACHE = {}


def alertas(uf, bbox):
    # cache/alerta/alerta_<UF>.parquet: arquivo do MapBiomas Alerta (plataforma, download do Brasil) separado por estado
    if uf not in AL_CACHE:
        f = f'cache/alerta/alerta_{uf}.parquet'
        AL_CACHE[uf] = gpd.read_parquet(f) if os.path.exists(f) else gpd.GeoDataFrame(geometry=[], crs=4674)
    a = AL_CACHE[uf]
    return a.cx[bbox[0]:bbox[2], bbox[1]:bbox[3]] if len(a) else a


def municipio(uf, cod, EMB, out='.'):
    global PROJ
    if PROJ is None: PROJ = projetos_carbono()
    car = car_mun(uf, cod)
    nome = car.municipio.iloc[0] if len(car) else str(cod)
    car = car[(car.status_imovel != 'CA') & (car.tipo_imovel == 'IRU')]
    if len(car) == 0: return None, nome
    bbox = [round(v, 4) for v in car.total_bounds]
    print(f'  {nome}: {len(car)} imóveis; baixando PRODES, TI, UC, SIGEF...')
    L, toca = camadas(uf, bbox)
    yd, acc, nf, hy, ti, uc = L['yd'], L['acc'], L['nf'], L['hy'], L['ti'], L['uc']
    sg = sigef(bbox)
    car = fix(car, sub=False); car['ha'] = car.area / 1e4
    base = car[['cod_imovel', 'geometry']]
    yd = fix(yd)
    if 'main_class' in yd: yd = yd[yd.main_class.str.upper() == 'DESMATAMENTO']
    if 'year' not in yd: yd['year'] = pd.Series(dtype=float)  # fora do bioma Amazônia o PRODES desta camada vem vazio
    e = EMB[EMB.COD_MUNICIPIO == str(cod)]
    e = e[(e.SIT_CANCELADO != 'S') & (e.SIT_DESEMBARGO != 'S') & e.GEOM_AREA_EMBARGADA.notna()].copy()
    e['geometry'] = e.GEOM_AREA_EMBARGADA.apply(lambda s: wkt.loads(s) if isinstance(s, str) and s.strip() else None)
    e = gpd.GeoDataFrame(e[e.geometry.notna()], geometry='geometry', crs=4674)
    c = car.set_index('cod_imovel')
    c['desm_pos2008_ha'] = ov(base, yd[yd.year >= 2009])
    c['desm_pos2020_ha'] = ov(base, yd[yd.year >= 2021])
    c['desm_pos2016_ha'] = ov(base, yd[yd.year >= 2016])  # re.green: sem conversão nos 10 anos antes do início
    c['embargo_ha'] = ov(base, fix(e)) if len(e) else 0
    accf, hyf = fix(acc), fix(hy)
    c['ti_ha'] = ov(base, fix(ti)); c['uc_ha'] = ov(base, fix(uc))
    desm = pd.concat([accf[['geometry']], yd[['geometry']]])
    c['desm_total_ha'] = ov(base, desm)
    c['nao_floresta_ha'] = ov(base, pd.concat([fix(nf)[['geometry']], hyf[['geometry']]]))
    if len(sg):
        sg = fix(sg)
        sg['mat'] = sg.registro_matricula.notna() | (sg.situacao_informada == 'REGISTRADA')
        c['sigef_ha'] = ov(base, sg)
        c['matricula_ha'] = ov(base, sg[sg.mat & (sg.natureza == 'Particular')])
        c['assentamento_ha'] = ov(base, sg[sg.natureza.fillna('').str.startswith('Assent')])
    c['projeto_carbono_ha'] = ov(base, fix(PROJ.to_crs(4674))) if len(PROJ) else 0
    # MapBiomas Alerta (desmatamento validado desde 2019, todos os biomas, inclusive mata secundária)
    al = alertas(uf, bbox)
    if len(al):
        al = fix(al)
        c['alerta_ha'] = ov(base, al)
        c['alerta_pos2020_ha'] = ov(base, al[al.ANODETEC >= 2021])
        j = gpd.sjoin(base, al[['ANODETEC', 'geometry']], predicate='intersects')
        c['alerta_ultimo_ano'] = j.groupby('cod_imovel').ANODETEC.max()
    else:
        c['alerta_ha'] = c['alerta_pos2020_ha'] = c['alerta_ultimo_ano'] = 0
    # APP de beira de rio desmatada: faixa de 30 m em volta da hidrografia do PRODES (só rios largos; córregos pequenos ficam de fora)
    if len(hyf) and len(desm):
        import shapely
        fx = hyf.buffer(30).union_all().difference(hyf.union_all())
        dg = desm.geometry.values; dg = dg[shapely.intersects(dg, fx)]
        j = gpd.GeoDataFrame(geometry=shapely.intersection(dg, fx), crs=A)
        j = j[~j.is_empty]
        c['app_desmatada_ha'] = ov(base, j) if len(j) else 0
        # Escadinha do art. 61-A (regras copiadas do GeoCAR, MIT, faixa_rio_consolidada): até 1 MF 5 m, até 2 MF 8 m,
        # até 4 MF 15 m, até 10 MF 20 m (rio até 10 m), acima 30 m. Largura do rio desconhecida: usa o mínimo.
        for w in (5, 8, 15, 20):
            fw = hyf.buffer(w).union_all().difference(hyf.union_all())
            jw = gpd.GeoDataFrame(geometry=shapely.intersection(dg[shapely.intersects(dg, fw)], fw), crs=A)
            jw = jw[~jw.is_empty]
            c[f'_app{w}'] = ov(base, jw) if len(jw) else 0
    else:
        c['app_desmatada_ha'] = 0
    c = c.fillna(0)
    if '_app5' in c:
        mf = c.m_fiscal
        c['app_escadinha_ha'] = np.select([mf <= 1, mf <= 2, mf <= 4, mf <= 10], [c._app5, c._app8, c._app15, c._app20], c.app_desmatada_ha)
        c = c.drop(columns=['_app5', '_app8', '_app15', '_app20'])
    else:
        c['app_escadinha_ha'] = 0.0
    # Art. 61-B: até 2 MF a APP a recompor não passa de 10% do imóvel; de 2 a 4 MF, 20% (GeoCAR limite_61b)
    teto = np.where(c.m_fiscal <= 2, .10 * c.ha, np.where(c.m_fiscal <= 4, .20 * c.ha, np.inf))
    c['app_recompor_ha'] = np.minimum(c.app_escadinha_ha, teto)
    for k in ['sigef_ha', 'matricula_ha', 'assentamento_ha']:
        if k not in c: c[k] = 0.0
    c['desm_total_ha'] = c[['desm_total_ha', 'ha']].min(axis=1)
    c['floresta_rem_ha'] = (c.ha - c.desm_total_ha - c.nao_floresta_ha).clip(lower=0)
    eleg = c.ha - c.nao_floresta_ha
    for p in (80, 50):
        c[f'deficit_RL{p}_ha'] = (p / 100 * eleg - c.floresta_rem_ha).clip(lower=0)
    # bioma de cada imóvel (pelo centro) e reserva legal que vale para ele
    cen = gpd.GeoDataFrame(geometry=c.geometry.representative_point(), index=c.index, crs=A).to_crs(4674)
    jb = gpd.sjoin(cen, biomas(), predicate='within')
    c['bioma'] = jb[~jb.index.duplicated()].bioma.reindex(c.index).fillna(toca[0] if toca else '')
    c['pct_RL'] = c.bioma.map(lambda b: pct_rl(uf, b))
    # Amazônia Legal com floresta: usa PCT_ALEM (50%, art. 12 §4º / ZEE) para a área além da reserva; resto: % do bioma
    c['pct_RL_alem'] = np.where(c.pct_RL == 80, PCT_ALEM, c.pct_RL)
    c['deficit_RL_ha'] = (c.pct_RL / 100 * eleg - c.floresta_rem_ha).clip(lower=0)
    c['deficit_RL_alem_ha'] = (c.pct_RL_alem / 100 * eleg - c.floresta_rem_ha).clip(lower=0)
    c['problema'] = (c.embargo_ha > 1) | (c.ti_ha > 1) | (c.desm_pos2020_ha > 1) | (c.alerta_pos2020_ha > 1)
    c['alem_RL_ha'] = (c.desm_total_ha - c.deficit_RL_alem_ha).clip(lower=0)
    c.loc[c.m_fiscal <= 4, 'alem_RL_ha'] = c.desm_total_ha  # até 4 MF: não deve RL (art. 67)
    c['f_matricula'] = c.matricula_ha / c.ha
    c['frente'] = frentes(c)
    c['cota_reserva'] = (~c.problema) & ((c.floresta_rem_ha - c.pct_RL_alem / 100 * eleg) >= 50)
    # REDD: floresta em pé além da reserva legal (mesma sobra da Cota de Reserva), sem corte de tamanho
    c['redd_excedente_ha'] = (c.floresta_rem_ha - c.pct_RL_alem / 100 * eleg).clip(lower=0).where(~c.problema, 0)
    # Outras frentes (todas sem corte de tamanho)
    limpo = (c.embargo_ha <= 1) & (c.ti_ha <= 1)
    c['frigorifico_remocao_ha'] = c.desm_total_ha.where(~c.problema, 0)  # FLAG: toda área aberta restaurável na fazenda fornecedora (inclui RL e APP; confirmar regra)
    c['compensacao_restauravel_ha'] = c.desm_total_ha.where(~c.problema, 0)  # área que obra/mineradora pode usar para compensar (falta cruzar com ANM/licenças)
    c['eudr_ok'] = limpo & (c.desm_pos2020_ha <= 1)  # sem desmatamento após 2020 (corte da regra europeia; PRODES ano 2021 começa em ago/2020)
    c['credito_rural_ok'] = limpo & (c.uc_ha <= 1)  # sem embargo, TI ou UC (não separa UC de uso sustentável)
    c['compra_arrendamento'] = (~c.problema) & (c.f_matricula >= .5)  # título limpo: pode ser comprada ou arrendada
    # Frentes que dependem de dado novo (preencher quando a fonte entrar)
    for k in ['cacau_aptidao', 'carbono_solo_ha', 'rebanho_cabecas', 'psa_elegivel', 'biodiversidade_score']:
        c[k] = np.nan  # fontes: aptidão Embrapa/ZARC cacau; solo (MapBiomas Solo); GTA Adepará; regras PSA/Floresta+; mapas de espécies
    c = regeneracao(c, uf)
    c = carbono(c, uf)
    if len(sg): certidoes(c, sg).to_csv(f'{out}/certidoes_{cod}.csv', index=False)
    try: gpd.GeoDataFrame({'cod_imovel': c.index}, geometry=c.geometry.values, crs=c.crs).to_parquet(f'{out}/geo_{cod}.parquet')
    except Exception as ex: print('   sem geo:', ex)
    return c.drop(columns='geometry'), nome


def certidoes(c, sg):
    """Cartório (CNS) e matrícula das parcelas SIGEF sobre cada imóvel da frente 'carbono'.
    Certidão de matrícula é registro público (Lei 6.015/73, art. 17): qualquer pessoa pode pedir.
    O nome do dono aparece na certidão: guardar só para o investidor que pagou a reserva."""
    alvo = c[c.frente.isin(['carbono', 'regularizar_antes', 'assentamento_agrupado'])].reset_index()[['cod_imovel', 'geometry']]
    p = sg[sg.registro_matricula.notna() & (sg.natureza == 'Particular')]
    if len(alvo) == 0 or len(p) == 0:
        return pd.DataFrame(columns=['cod_imovel', 'registro_cns', 'registro_matricula', 'ha_sobre_car', 'parcelas'])
    j = gpd.overlay(alvo, p[['parcela_codigo', 'registro_cns', 'registro_matricula', 'geometry']], how='intersection')
    j['ha_sobre_car'] = j.area / 1e4
    j = j[j.ha_sobre_car >= 5]
    t = j.groupby(['cod_imovel', 'registro_cns', 'registro_matricula'], as_index=False).agg(
        ha_sobre_car=('ha_sobre_car', 'sum'), parcelas=('parcela_codigo', 'nunique'))
    t['ha_sobre_car'] = t.ha_sobre_car.round(1)
    return t.sort_values(['cod_imovel', 'ha_sobre_car'], ascending=[True, False])


def frentes(c):
    """Um caminho para cada imóvel (ordem de prioridade). SEM corte de tamanho: pequenas entram agrupadas.
    fora_TI | desbloqueio | carbono | carbono_revisar_desm10anos | ja_tem_projeto | regularizar_antes | assentamento_agrupado | silvipastoril"""
    f = pd.Series('silvipastoril', index=c.index)  # sem área além da reserva: pasto produtivo
    alem = c.alem_RL_ha > 1
    f[alem] = 'regularizar_antes'
    if 'assentamento_ha' in c: f[alem & (c.assentamento_ha / c.ha >= .5)] = 'assentamento_agrupado'
    f[alem & (c.f_matricula >= .5)] = 'carbono'
    if 'desm_pos2016_ha' in c: f[(f == 'carbono') & (c.desm_pos2016_ha > 5)] = 'carbono_revisar_desm10anos'
    if 'projeto_carbono_ha' in c: f[(f == 'carbono') & (c.projeto_carbono_ha >= 10)] = 'ja_tem_projeto'
    f[(c.embargo_ha > 1) | (c.desm_pos2020_ha > 1)] = 'desbloqueio'
    f[c.ti_ha > 1] = 'fora_TI'
    return f


def resumo(c, cod, nome):
    ok = ~c.problema
    cb = c.carbono_ha if 'carbono_ha' in c else c.alem_RL_ha
    apt = ok & (cb > 0) & (c.get('desm_pos2016_ha', 0) <= 5)
    mat = apt & (c.f_matricula >= .5)
    return dict(cod_ibge=cod, municipio=nome, imoveis=len(c), sem_problema=int(ok.sum()),
                def_RL=int((ok & (c.get('deficit_RL_alem_ha', c.deficit_RL50_ha) > 1)).sum()),
                aptas_carbono=int(apt.sum()), ha_carbono=round(cb[apt].sum()),
                tco2_ano_aptas=round(c.get('carbono_tco2_ano', pd.Series(0, index=c.index))[apt].sum()),
                aptas_com_matricula=int(mat.sum()), ha_carbono_matricula=round(cb[mat].sum()),
                cota_reserva=int(c.cota_reserva.sum()),
                redd_imoveis=int((c.redd_excedente_ha > 0).sum()), redd_ha=round(c.redd_excedente_ha.sum()),
                app_imoveis=int((c.app_desmatada_ha > 0).sum()), app_ha=round(c.app_desmatada_ha.sum()),
                frigorifico_imoveis=int((c.frigorifico_remocao_ha > 0).sum()), frigorifico_ha=round(c.frigorifico_remocao_ha.sum()),
                compensacao_ha=round(c.compensacao_restauravel_ha.sum()),
                eudr_ok=int(c.eudr_ok.sum()), credito_rural_ok=int(c.credito_rural_ok.sum()),
                compra_arrendamento=int(c.compra_arrendamento.sum()),
                alerta_pos2020_imoveis=int((c.get('alerta_pos2020_ha', pd.Series(0, index=c.index)) > 1).sum()),
                **{f'frente_{k}': int(v) for k, v in c.frente.value_counts().items()})


COD_UF = dict(RO=11, AC=12, AM=13, RR=14, PA=15, AP=16, TO=17, MA=21, PI=22, CE=23, RN=24, PB=25, PE=26,
              AL=27, SE=28, BA=29, MG=31, ES=32, RJ=33, SP=35, PR=41, SC=42, RS=43, MS=50, MT=51, GO=52, DF=53)


def lista_municipios(uf):
    # lista local (cache/municipios.csv, de github.com/kelvins/municipios-brasileiros); a API do IBGE às vezes cai
    f = 'cache/municipios.csv'
    if os.path.exists(f):
        m = pd.read_csv(f)
        return m[m.codigo_uf == COD_UF[uf]].codigo_ibge.astype(int).tolist()
    return [m['id'] for m in get(f'https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios', {}).json()]


_EMB = None


def _um(args):
    """Roda um município (em processo separado) e devolve a linha do resumo."""
    uf, cod, out = args
    p = f'{out}/imoveis_{cod}.csv'
    try:
        if os.path.exists(p):
            c = pd.read_csv(p, index_col=0); nome = c.municipio.iloc[0] if len(c) else str(cod)
        else:
            t0 = time.time()
            c, nome = municipio(uf, cod, _EMB, out)
            if c is None: return None
            c.to_csv(p)
            print(f'   {cod} {nome}: {len(c)} imóveis em {time.time() - t0:.0f} s', flush=True)
        return resumo(c, cod, nome)
    except Exception as ex:
        print(f'   {cod} ERRO, pulando: {ex}', flush=True); return None


def main():
    """Vários municípios ao mesmo tempo (LANES processos, padrão 3; a máquina tem 4 núcleos)."""
    global _EMB
    import multiprocessing as mp
    uf = sys.argv[1].upper()
    cods = [int(x) for x in sys.argv[2:]] or lista_municipios(uf)
    out = f'saida/{uf}'; os.makedirs(out, exist_ok=True)
    _EMB = embargos()
    lanes = int(os.environ.get('LANES', '3'))
    linhas = []
    with mp.get_context('fork').Pool(lanes, maxtasksperchild=20) as pool:
        for i, r in enumerate(pool.imap_unordered(_um, [(uf, c, out) for c in cods]), 1):
            if r: linhas.append(r)
            print(f'[{i}/{len(cods)}]', flush=True)
            if linhas: pd.DataFrame(linhas).sort_values('cod_ibge').to_csv(f'{out}/resumo_{uf}.csv', index=False)
    t = pd.DataFrame(linhas)
    if len(t): print('\nTOTAL', uf, t.drop(columns=['cod_ibge', 'municipio']).sum().to_dict())


if __name__ == '__main__':
    main()
