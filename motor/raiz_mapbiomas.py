"""
Raíz: MapBiomas por imóvel SEM Earth Engine, pela API oficial da Plataforma MapBiomas (rodada 9, testada em 12/11/2026).

Uso:
  python raiz_mapbiomas.py PA            # todos os municípios já rodados em saida/PA/
  python raiz_mapbiomas.py PA 1504950    # um município

Como funciona: pede à plataforma a exportação em GeoTIFF de cada tema para o ESTADO inteiro (sem login;
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


def _esperar(segundos, prazo):
    if prazo is not None and time.time() + segundos >= prazo:
        raise RuntimeError('MapBiomas: prazo de espera esgotado; pedidos aceitos ficam guardados para a próxima rodada')
    time.sleep(segundos)


def _pedido(metodo, url, tentativas=8, prazo=None, **kw):
    """Repete só falhas transitórias de transporte/HTTP, dentro do prazo da chamada."""
    ultimo = ''
    for t in range(tentativas):
        restante = prazo - time.time() if prazo is not None else 120
        if restante <= 0:
            raise RuntimeError('MapBiomas: prazo de espera esgotado; pedidos aceitos ficam guardados')
        espera = min(30 * 2 ** t, 600)
        try:
            r = requests.request(metodo, url, headers=H, timeout=min(120, restante), **kw)
            if r.status_code not in (403, 429) and r.status_code < 500: return r
            ra = r.headers.get('Retry-After', '')
            if ra.isdigit(): espera = min(int(ra), 900)
            ultimo = f'HTTP {r.status_code}'
        except requests.RequestException as ex:
            ultimo = type(ex).__name__  # não registra URLs assinadas nem o corpo remoto
        if t < tentativas - 1:
            print(f'  API MapBiomas: tentativa {t + 1}/{tentativas} falhou ({ultimo}); espero {espera} s', flush=True)
            _esperar(espera, prazo)
    raise RuntimeError(f'API MapBiomas não respondeu ({ultimo})')


def _get(url, **kw):
    return _pedido('GET', url, **kw)


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


def estado(uf, prazo=None):
    r = _get(f'{API}/territories?categoryId={CAT_ESTADO}&pageSize=40', prazo=prazo).json()
    for t in r['territories']:
        if t['name'] == NOME_UF[uf]: return t['id']
    raise RuntimeError(f'estado {uf} não achado na plataforma')


def _quota_exportacao(r):
    """422 também pode ser validação: só repetimos quando a resposta indica limite de geração.

    A interface oficial traduz 422 deste endpoint como request_limit, mas isso sozinho não comprova o motivo.
    Não guardamos nem mostramos o corpo, que pode conter detalhes da conta ou identificadores do pedido.
    """
    if r.status_code != 422: return False
    try:
        corpo = r.json()
    except ValueError:
        return False
    def normalizar(valor):
        return unicodedata.normalize('NFKD', str(valor)).encode('ascii', 'ignore').decode().lower().strip()

    def sinal(objeto):
        if not isinstance(objeto, dict): return False
        codigos = {'request_limit', 'export_limit', 'export_limit_exceeded', 'export_quota_exceeded', 'quota_exceeded'}
        for campo, valor in objeto.items():
            if isinstance(valor, dict) and sinal(valor): return True
            if not isinstance(valor, str): continue
            texto = normalizar(valor)
            if campo.lower() in ('code', 'errorcode', 'error_code', 'error') and texto in codigos: return True
            if campo.lower() not in ('message', 'errormessage', 'error', 'description'): continue
            if texto in codigos: return True
            # Quantidade de anos ou campos inválidos não são falta de capacidade do serviço.
            if any(x in texto for x in ('invalid', 'invalido', 'validation', 'must be', 'field', 'years', 'anos')): continue
            if any(x in texto for x in ('request limit reached', 'request limit exceeded',
                                        'export limit reached', 'export limit exceeded',
                                        'export quota exceeded', 'limite de exportacao atingido',
                                        'limite de exportacao excedido')): return True
            if 'too many' in texto and any(x in texto for x in ('exports', 'maps', 'requests')): return True
            if 'muitos mapas' in texto and any(x in texto for x in ('gerados', 'geracao')): return True
        return False

    return sinal(corpo)



def _geotiff(conteudo):
    """Valida um único GeoTIFF (clássico ou BigTIFF), inclusive quando a API o entrega em ZIP."""
    import rasterio
    from rasterio.io import MemoryFile
    if conteudo[:2] == b'PK':
        with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
            nomes = [n for n in z.namelist() if n.lower().endswith(('.tif', '.tiff'))]
            if len(nomes) != 1:
                raise RuntimeError('MapBiomas: ZIP deve conter exatamente um GeoTIFF para o ano solicitado')
            conteudo = z.read(nomes[0])
    if conteudo[:4] not in (b'II\x2a\x00', b'MM\x00\x2a', b'II\x2b\x00', b'MM\x00\x2b'):
        raise RuntimeError('MapBiomas: download não é TIFF nem BigTIFF')
    try:
        with MemoryFile(conteudo) as mem, mem.open() as src:
            if src.driver != 'GTiff' or not src.crs or src.transform.is_identity or not src.count or not src.width or not src.height:
                raise RuntimeError('MapBiomas: GeoTIFF sem georreferência ou bandas válidas')
            # Também verifica o fim do arquivo: o primeiro pixel não detecta TIFF truncado num tile posterior.
            # Janelas limitadas evitam materializar um raster estadual inteiro em memória.
            for banda in src.indexes:
                for linha in range(0, src.height, 512):
                    for coluna in range(0, src.width, 512):
                        src.read(banda, window=((linha, min(linha + 512, src.height)),
                                                (coluna, min(coluna + 512, src.width))))
    except rasterio.errors.RasterioError as ex:
        raise RuntimeError('MapBiomas: GeoTIFF inválido ou incompleto') from ex
    return conteudo


def exporta_uf(uf, espera=6 * 3600, temas=None):
    """Consome pedidos aceitos antes de criar outro; mantém os cinco produtos/anos do catálogo.

    Os IDs persistem em pedidos.json até o GeoTIFF ser validado. Novos pedidos são sequenciais: a geração anterior
    termina antes de usar outra vaga da plataforma. Quota explícita tem no máximo oito tentativas, limitadas também
    por espera e RAIZ_PRAZO. Uma resposta 422 sem sinal de quota falha visivelmente, sem repetição cega.
    """
    T = {k: v for k, v in TEMAS.items() if temas is None or k in temas}
    arq = {k: f'{CACHE}/{uf}/{uf}_{k}_{ano}.tif' for k, (ch, ano) in T.items()}
    falta = {k: v for k, v in T.items() if not os.path.exists(arq[k])}
    if not falta: return arq
    os.makedirs(f'{CACHE}/{uf}', exist_ok=True)
    fp = f'{CACHE}/{uf}/pedidos.json'
    pedidos = json.load(open(fp)) if os.path.exists(fp) else {}
    t0 = time.time()
    prazo_job = float(os.environ.get('RAIZ_PRAZO', 0) or 0)
    limite = min(t0 + espera, prazo_job - 120) if prazo_job else t0 + espera

    def guarda():
        open(fp + '.tmp', 'w').write(json.dumps(pedidos)); os.replace(fp + '.tmp', fp)

    avisados = set()

    def consulta(pend):
        for k, eid in list(pend.items()):
            r = _get(f'{API}/maps/exports/{eid}', prazo=limite)
            if r.status_code == 404:
                pedidos.pop(k, None); guarda()
                raise RuntimeError(f'{uf} {k}: pedido aceito não existe mais; será renovado na próxima rodada')
            if not r.ok:
                raise RuntimeError(f'{uf} {k}: consulta do pedido falhou (HTTP {r.status_code})')
            situacao = r.json().get('status')
            if situacao == 'READY':
                r = _get(f'{API}/maps/exports/{eid}/download', allow_redirects=True, prazo=limite)
                if not r.ok:
                    raise RuntimeError(f'{uf} {k}: download falhou (HTTP {r.status_code}); pedido preservado')
                b = _geotiff(r.content)
                open(arq[k] + '.tmp', 'wb').write(b); os.replace(arq[k] + '.tmp', arq[k])
                pedidos.pop(k, None); guarda(); del pend[k]
                print(f'  {uf} {k}: pronto em {time.time() - t0:.0f} s, {len(b) / 1e6:.0f} MB', flush=True)
            elif situacao in ('FAILED', 'EXPIRED'):
                pedidos.pop(k, None); guarda()
                raise RuntimeError(f'{uf} {k}: geração encerrou como {situacao}; será renovada na próxima rodada')
            elif not isinstance(situacao, str) or not situacao.strip():
                raise RuntimeError(f'{uf} {k}: resposta sem situação de exportação; pedido preservado')
            elif k not in avisados:
                # O catálogo não documenta todos os estados transitórios. Só READY/FAILED/EXPIRED são terminais.
                print(f'  {uf} {k}: pedido ainda não pronto; aguardo até o prazo, com ID preservado', flush=True)
                avisados.add(k)

    pend = {}
    novos = {}
    for k, (ch, ano) in falta.items():
        antigo = pedidos.get(k)
        if antigo and antigo.get('chave') == ch and antigo.get('ano') == ano and antigo.get('id'):
            pend[k] = antigo['id']; print(f'  {uf} {k}: reaproveito o pedido aceito', flush=True)
        else:
            novos[k] = (ch, ano)
    # Primeiro consome TODAS as solicitações anteriores, inclusive a cobertura pronta que antes ficava atrás do 422.
    while pend:
        consulta(pend)
        if pend: _esperar(30, limite)
    tid = None
    for k, (ch, ano) in novos.items():
        if limite <= time.time():
            raise RuntimeError(f'{uf} {k}: prazo esgotado antes de criar exportação')
        if tid is None: tid = estado(uf, prazo=limite)
        for tentativa in range(8):
            r = _pedido('POST', f'{API}/maps/exports', prazo=limite,
                        json={'territoryId': tid, 'subthemeKey': ch, 'years': [ano], 'exportType': 'range'})
            if r.ok: break
            if not _quota_exportacao(r):
                raise RuntimeError(f'{uf} {k}: exportação recusada (HTTP {r.status_code}; quota não confirmada); conferir contrato/payload')
            if tentativa == 7:
                raise RuntimeError(f'{uf} {k}: quota de exportação permaneceu após oito tentativas')
            espera_quota = min(30 * 2 ** tentativa, 300)
            ra = r.headers.get('Retry-After', '')
            if ra.isdigit(): espera_quota = min(max(int(ra), 1), 900)
            print(f'  {uf} {k}: quota de exportação; tentativa {tentativa + 1}/8, espero {espera_quota} s', flush=True)
            _esperar(espera_quota, limite)
        pend[k] = r.json()['exports'][0]['id']
        pedidos[k] = {'id': pend[k], 'chave': ch, 'ano': ano, 'em': time.time()}; guarda()
        while pend:
            consulta(pend)
            if pend: _esperar(30, limite)
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
    falta = [c for c in cods if not os.path.exists(f'{pasta}/mapbiomas_{c}.csv')]
    print(f'{uf}: {len(cods)} municípios, {len(falta)} para fazer, ano {ANO}', flush=True)
    if not falta: return
    arq = exporta_uf(uf)  # só pede ao MapBiomas se algum município ainda não tem o CSV
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
