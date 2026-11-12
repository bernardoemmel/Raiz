"""
Raíz: ajustes por cima da saída do motor (raiz_estado.py), sem rodar de novo.
Vêm da rodada 2 de pesquisa (analise_melhorias_motor_v1.txt).

Uso:  python raiz_ajustes.py <pasta com imoveis_*.csv> [<pasta> ...]
Grava ajustes_<mun>.csv ao lado de cada imoveis_<mun>.csv e resumo_ajustes.csv na pasta.

O que entra:
 1. Carbono em três cenários (tCO2/ano):
    - conservador: na Amazônia, Elias et al. 2022 (1,2 tC/ha/ano, leste do PA, 28 parcelas); fora dela, igual ao central
    - central: Heinrich 2021 na Amazônia (taxa já calculada pelo motor); Inventário Nacional fora dela
    - inventário: fator oficial do 4º Inventário Nacional (ex-pasto), por bioma
    - líquido prévio = central × (1 − 12% reserva mínima NPRT v5.0) × (1 − 10% incerteza ex-ante VM0047)
      AINDA SEM linha de base dinâmica (VM0047 Ap. 1) e SEM vazamento (VMD0054): valor máximo, não promessa.
 2. APP pela escadinha (Lei 12.651, art. 61-A) em área consolidada:
    até 1 módulo 5 m, 1 a 2: 8 m, 2 a 4: 15 m, 4 a 10: 20 m, acima de 10: metade da largura do rio, mínimo 30 m (Decreto 7.830, art. 19).
    O motor mediu APP com faixa de 30 m; aqui a obrigatória é aproximada por proporção da largura.
    Imóvel sem desmatamento depois de 2008 é tratado como consolidado (aproximação).
 3. Avisos de título:
    - Pará: matrícula declarada precisa conferir cancelamento (Provimentos CGJ-PA 13/2006 e 02/2010).
    - 101 ha ou mais sem georreferenciamento no SIGEF: amarelo forte (Decreto 12.689/2025).
    - Lote de assentamento: título do INCRA com cláusula resolutiva; liberar ou parecer jurídico.
"""
import sys, glob, os
import pandas as pd

C2CO2 = 44 / 12
INVENTARIO_TC = {'Amazônia': 3.03, 'Cerrado': 2.85, 'Mata Atlântica': 1.66, 'Caatinga': 0.64}
# Pampa e Pantanal: a nota do SEEG tem valores próprios que ainda não lemos; ficam com o provisório do motor
ELIAS_TC = 1.2
RAIZ = 0.24
RESERVA_NPRT = 0.12
INCERTEZA_EXANTE = 0.10


def faixa_escadinha(mf):
    # Lei 12.651 art. 61-A + Decreto 7.830 art. 19 §4: acima de 4 até 10 módulos, 20 m (rio até 10 m de largura);
    # acima de 10 módulos, metade da largura do rio, mínimo 30 m (sem largura do rio, usa o mínimo)
    if pd.isna(mf): return 20
    return 5 if mf <= 1 else 8 if mf <= 2 else 15 if mf <= 4 else 20 if mf <= 10 else 30


def ajusta(arq):
    d = pd.read_csv(arq, low_memory=False)
    o = pd.DataFrame({'cod_imovel': d.cod_imovel, 'uf': d.uf, 'municipio': d.municipio})
    bioma = d.get('bioma', pd.Series('Amazônia', index=d.index)).fillna('Amazônia')
    area_c = d.carbono_ha.fillna(0) if 'carbono_ha' in d else d.alem_RL_ha.fillna(0)

    # 1. carbono
    if 'taxa_tco2_ha_ano' in d:
        heinrich = d.taxa_tco2_ha_ano
    else:  # saída antiga (SFX): Heinrich sudeste do Pará
        heinrich = pd.Series(1.8 * (1 + RAIZ) * C2CO2, index=d.index)
    inv = bioma.map(INVENTARIO_TC) * C2CO2          # já é o acúmulo total do inventário: sem multiplicar raiz
    amz = bioma.eq('Amazônia')
    central = heinrich.where(amz, inv.fillna(heinrich))
    conserv = pd.Series(ELIAS_TC * (1 + RAIZ) * C2CO2, index=d.index).where(amz, central)
    o['tco2_ha_ano_conservador'] = conserv.round(2)
    o['tco2_ha_ano_central'] = central.round(2)
    o['tco2_ha_ano_inventario'] = inv.round(2)
    o['tco2_ano_conservador'] = (area_c * conserv).round(0)
    o['tco2_ano_central'] = (area_c * central).round(0)
    o['tco2_ano_liquido_previo'] = (area_c * central * (1 - RESERVA_NPRT) * (1 - INCERTEZA_EXANTE)).round(0)
    o['falta_no_liquido'] = 'linha de base dinâmica VM0047 e vazamento VMD0054'

    # 2. APP escadinha
    app30 = d.app_desmatada_ha.fillna(0)
    consolidado = d.desm_pos2008_ha.fillna(0) <= 0
    faixa = d.m_fiscal.map(faixa_escadinha)
    obrig = (app30 * faixa / 30).where(consolidado, app30)
    o['app_faixa_m'] = faixa.where(consolidado, 30)
    o['app_obrigatoria_ha'] = obrig.round(2)
    o['app_voluntaria_ha'] = (app30 - obrig).round(2)   # pode somar ao carbono (restauração além da lei)

    # 3. título
    ha = d.ha.fillna(0)
    avisos = []
    for i in d.index:
        a = []
        if d.uf[i] == 'PA' and d.matricula_ha.fillna(0)[i] > 0:
            a.append('matrícula a conferir: cancelamentos do Pará')
        if ha[i] >= 101 and d.sigef_ha.fillna(0)[i] < 0.5 * ha[i]:
            a.append('101 ha ou mais sem SIGEF certificado')
        if str(d.tipo_imovel[i]).upper() == 'AST' or d.assentamento_ha.fillna(0)[i] > 0.5 * ha[i]:
            a.append('título do INCRA: liberar cláusula ou parecer')
        avisos.append('; '.join(a))
    o['avisos_titulo'] = avisos
    o['titulo_cor'] = ['amarelo' if x else 'verde' for x in avisos]

    out = arq.replace('imoveis_', 'ajustes_')
    o.to_csv(out, index=False)
    apta = d.frente.astype(str).str.startswith('carbono') if 'frente' in d else area_c > 0
    return dict(arquivo=os.path.basename(arq), imoveis=len(d),
                tco2_ano_conservador_aptas=o.tco2_ano_conservador[apta].sum(),
                tco2_ano_central_aptas=o.tco2_ano_central[apta].sum(),
                tco2_ano_liquido_previo_aptas=o.tco2_ano_liquido_previo[apta].sum(),
                app_30m_ha=round(app30.sum(), 1), app_obrigatoria_ha=round(obrig.sum(), 1),
                app_voluntaria_ha=round((app30 - obrig).sum(), 1),
                aviso_matricula_PA=sum('cancelamentos' in x for x in avisos),
                aviso_sigef_101ha=sum('SIGEF' in x for x in avisos),
                aviso_incra=sum('INCRA' in x for x in avisos))


if __name__ == '__main__':
    for pasta in sys.argv[1:]:
        res = [ajusta(f) for f in sorted(glob.glob(os.path.join(pasta, 'imoveis_*.csv')))]
        if res:
            r = pd.DataFrame(res)
            r.to_csv(os.path.join(pasta, 'resumo_ajustes.csv'), index=False)
            print(pasta, r.drop(columns='arquivo').sum(numeric_only=True).round(0).to_dict())
