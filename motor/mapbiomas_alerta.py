"""
Raíz: alertas de desmatamento validados do MapBiomas Alerta, por imóvel do CAR (API GraphQL v2).

Precisa das variáveis de ambiente MAPBIOMAS_ALERTA_EMAIL e MAPBIOMAS_ALERTA_SENHA
(conta da plataforma https://plataforma.alerta.mapbiomas.org). Nunca grave a senha no código.

Uso:
  python mapbiomas_alerta.py saida/PA/imoveis_1507300.csv
  -> grava saida/PA/alertas_1507300.csv, uma linha por imóvel:
     cod_imovel, alertas_n, alertas_ha, ultimo_alerta (data de detecção), alertas_ha_10anos, alertas_ha_pos2020

Serve para: (1) filtro de anos sem desmatamento em qualquer bioma (não só onde há PRODES);
(2) vigilância depois do contrato (rodar de novo e comparar).
"""
import os, sys, time, requests, pandas as pd

URL = 'https://plataforma.alerta.mapbiomas.org/api/v2/graphql'
LOTE = 50       # códigos de CAR por consulta
POR_PAGINA = 200


def token():
    email, senha = os.environ.get('MAPBIOMAS_ALERTA_EMAIL'), os.environ.get('MAPBIOMAS_ALERTA_SENHA')
    if not (email and senha):
        sys.exit('Defina MAPBIOMAS_ALERTA_EMAIL e MAPBIOMAS_ALERTA_SENHA no ambiente.')
    q = 'mutation($e:String!,$s:String!){ signIn(email:$e,password:$s){ token } }'
    r = requests.post(URL, json={'query': q, 'variables': {'e': email, 's': senha}}, timeout=60).json()
    if r.get('errors'):
        sys.exit('Login falhou: ' + r['errors'][0]['message'])
    return r['data']['signIn']['token']


Q = '''query($cars:[ID!],$p:Int,$l:Int){
  alerts(propertyCodes:$cars, page:$p, limit:$l){
    collection{ alertCode areaHa detectedAt ruralProperties{ carCode } }
    metadata{ totalPages }
  }
}'''


def consulta(tok, cars):
    linhas, p = [], 1
    while True:
        for t in range(5):
            try:
                r = requests.post(URL, json={'query': Q, 'variables': {'cars': cars, 'p': p, 'l': POR_PAGINA}},
                                  headers={'Authorization': f'Bearer {tok}'}, timeout=120).json()
                break
            except Exception as ex:
                print('   tentativa', t + 1, 'falhou:', ex); time.sleep(5 * (t + 1))
        else:
            raise RuntimeError('API não respondeu')
        if r.get('errors'):
            raise RuntimeError(r['errors'][0]['message'])
        d = r['data']['alerts']
        alvo = set(cars)
        for a in d['collection']:
            for rp in a.get('ruralProperties') or []:
                if rp['carCode'] in alvo:
                    linhas.append(dict(cod_imovel=rp['carCode'], alerta=a['alertCode'],
                                       ha=a['areaHa'], detectado=a['detectedAt']))
        if p >= d['metadata']['totalPages']:
            return linhas
        p += 1


def main(arq):
    cars = pd.read_csv(arq, usecols=['cod_imovel']).cod_imovel.dropna().astype(str).unique().tolist()
    tok = token()
    todas = []
    for i in range(0, len(cars), LOTE):
        todas += consulta(tok, cars[i:i + LOTE])
        print(f'  {min(i + LOTE, len(cars))}/{len(cars)} imóveis, {len(todas)} alertas')
    a = pd.DataFrame(todas, columns=['cod_imovel', 'alerta', 'ha', 'detectado'])
    a['detectado'] = pd.to_datetime(a.detectado, errors='coerce')
    ano = a.detectado.dt.year
    hoje = pd.Timestamp.today().year
    g = a.groupby('cod_imovel')
    res = pd.DataFrame({
        'alertas_n': g.alerta.nunique(),
        'alertas_ha': g.ha.sum().round(1),
        'ultimo_alerta': g.detectado.max().dt.date,
        'alertas_ha_10anos': a[ano >= hoje - 10].groupby('cod_imovel').ha.sum().round(1),
        'alertas_ha_pos2020': a[ano >= 2021].groupby('cod_imovel').ha.sum().round(1),
    }).reindex(cars).fillna({'alertas_n': 0, 'alertas_ha': 0, 'alertas_ha_10anos': 0, 'alertas_ha_pos2020': 0})
    res.index.name = 'cod_imovel'
    out = arq.replace('imoveis_', 'alertas_')
    res.to_csv(out)
    print('gravado', out, '| imóveis com alerta:', int((res.alertas_n > 0).sum()))


if __name__ == '__main__':
    main(sys.argv[1])
