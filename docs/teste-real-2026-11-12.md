# Teste com dado real, 12/11/2026 (Nova Esperança do Piriá, PA, 1504950)

Sequência rodada com a rede aberta: `raiz coleta fontes`, `raiz coleta checar`, `raiz coleta car PA --municipio
1504950`, `raiz coleta ibama`, `raiz funil rodar PA 1504950 --tarefas funil,filtros,direto,carga`.

## Coleta

| Passo | Resultado |
|---|---|
| checar | os 8 arquivos do manifesto respondem (Ibama 214 MB, YbYrá, GPW, geobr) |
| CAR | 945 imóveis no espelho (todos os tipos e situações; o motor filtra os 880 IRU ativos), assinatura `945|2026-11-11T19:38`, depois só o delta pela data e, sem mudança, só a verificação (~3 s) |
| SIGEF | 1.330 parcelas no retângulo do município, no espelho e no histórico |
| Ibama | 117.197 termos, 4.040 municípios no espelho em 5 min 41 s; saíram na entrada NOME_EMBARGADO, CPF_CNPJ_EMBARGADO e NOME_IMOVEL; CSV limpo no cache do motor |
| Histórico | bruto.car_imovel (945) e bruto.sigef_parcela (1.330), views vigentes |

O dado real mostrou quatro problemas que os servidores falsos não mostravam, todos corrigidos com teste de regressão:
nulo primeiro na ordenação decrescente do GeoServer do CAR; erro 500 do mesmo servidor com parênteses no CQL; nulos
do pandas 3 no hash do histórico e na geometria; histórico que ficava para trás depois de uma falha.

## Funil (motor sem edição, CAR e SIGEF lidos do espelho pela ponte)

1 min 52 s, nenhuma falha; 880 imóveis, os mesmos da amostra.

| Coluna | Amostra | Real | Imóveis diferentes |
|---|---|---|---|
| ha, m_fiscal, desm_total_ha, desm_pos2008/2020_ha, floresta_rem_ha | iguais | iguais | 0 |
| deficit_RL_ha, alem_RL_ha, embargo_ha, sigef_ha, matricula_ha, f_matricula, app_desmatada_ha | iguais | iguais | 0 |
| frente | | | 0 de 880 |
| filtro_territorial | | | 0 de 880 |
| problema | | | 20 (alerta do MapBiomas Alerta) |
| compra_arrendamento | | | 2 (depende de problema) |
| carbono_tco2_ano | 222.694 | 443.546 | 789 |

Diferenças, todas de entrada que faltou aqui, não do produto:

1. **MapBiomas Alerta**: o motor lê `cache/alerta/alerta_<UF>.parquet`, arquivo baixado à mão da plataforma. Sem ele,
   20 imóveis com alerta depois de 2020 perdem a marca de problema.
2. **Regeneração (pasto a até 1 km de floresta)**: `regeneracao()` do motor ainda lê GeoTIFFs do Earth Engine em
   `mapbiomas/raiz_mapbiomas_<UF>*.tif` (bandas cob2008, cob_atual, sec_idade). Sem eles, não há `pasto_ha`,
   `secundaria_ha`, `pasto_ate1km_ha` nem `carbono_ha`, e o carbono usa a área além da reserva inteira (o dobro).
   O `raiz_mapbiomas.py` novo entrega as colunas `mb_*`, mas não a distância à floresta que a regeneração usa.
   Decisão do motor (não editado aqui).

   **Resolvido no PR #5 do motor (sem Earth Engine)**, rodado de novo aqui no mesmo dia: a regeneração lê cobertura e
   desmatamento v5 da API da Plataforma MapBiomas. Resultado em 1504950: carbono 209.708 tCO2/ano (antes 443.546;
   amostra, ainda da exportação do Earth Engine, 222.694). As frentes ficam iguais nos 880 imóveis. A diferença de
   5,8% vem da área de pasto (37.736 ha pela API, coleção 11 de 2025, contra 40.325 ha na exportação antiga), não
   do cálculo. TMF e causa da perda (`extras_direto_1504950.csv`) batem com a amostra em 880 de 880 imóveis.

Colunas novas no real: app_escadinha_ha e app_recompor_ha (a amostra é anterior à escadinha).
