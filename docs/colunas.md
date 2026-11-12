# Colunas que o motor entrega (contrato com o produto)

Regra: o motor pode **acrescentar** colunas, nunca renomear ou apagar sem aviso. O produto deve ler pelo nome e
ignorar colunas que não conhece. Áreas em hectares (`_ha`), carbono em tCO2 por ano. Nenhum arquivo tem CPF, CNPJ ou nome.

## `saida/<UF>/imoveis_<cod_ibge>.csv` (uma linha por imóvel do CAR, tipo IRU, sem cancelados)

| Coluna | O que é |
|---|---|
| cod_imovel | código do CAR (chave de tudo) |
| id, status_imovel, dat_criacao, data_atualizacao, area, condicao, uf, municipio, cod_municipio_ibge, m_fiscal, tipo_imovel | campos do SICAR (m_fiscal = módulos fiscais) |
| ha | área do polígono do CAR |
| desm_pos2008_ha / desm_pos2016_ha / desm_pos2020_ha | desmatamento PRODES depois de 2008 / 2016 / 2020 |
| desm_total_ha | toda área aberta (desmatamento acumulado + anual do PRODES) |
| nao_floresta_ha | vegetação que não é floresta + água (não conta na reserva de floresta) |
| floresta_rem_ha | floresta que sobrou (ha − aberto − não floresta) |
| embargo_ha | sobreposição com embargo ativo do Ibama |
| ti_ha / uc_ha | sobreposição com terra indígena / unidade de conservação (TerraBrasilis) |
| sigef_ha / matricula_ha / assentamento_ha | parcelas SIGEF (todas / particulares com matrícula / assentamentos) |
| f_matricula | fração do CAR coberta por parcela com matrícula |
| projeto_carbono_ha | sobreposição com projetos de carbono já registrados |
| alerta_ha / alerta_pos2020_ha / alerta_ultimo_ano | MapBiomas Alerta (alertas publicados, do WFS público da plataforma) |
| app_desmatada_ha | beira de rio aberta, faixa fixa de 30 m (cenário integral) |
| app_escadinha_ha | idem pela escadinha do art. 61-A (5/8/15/20/30 m por módulo fiscal) |
| app_recompor_ha | escadinha com o teto do art. 61-B (10% até 2 MF, 20% de 2 a 4 MF) |
| bioma, pct_RL, pct_RL_alem | bioma e % de reserva legal (pct_RL_alem = 50% onde há ZEE na Amazônia) |
| deficit_RL_ha / deficit_RL_alem_ha / deficit_RL80_ha / deficit_RL50_ha | déficit de reserva legal em cada regra |
| alem_RL_ha | área aberta além da reserva legal (até 4 MF: tudo, art. 67) |
| problema | True se embargo, TI, desmatamento ou alerta depois de 2020 (>1 ha) |
| frente | caminho do imóvel: carbono, carbono_so_plantio, carbono_revisar_desm10anos, ja_tem_projeto, regularizar_antes, assentamento_agrupado, silvipastoril, desbloqueio, fora_TI |
| cota_reserva | floresta sobrando ≥50 ha além da reserva (pode emitir Cota de Reserva Ambiental) |
| redd_excedente_ha | floresta em pé além da reserva, sem problema |
| frigorifico_remocao_ha / compensacao_restauravel_ha | área restaurável para meta FLAG / compensação |
| eudr_ok / credito_rural_ok / compra_arrendamento | sem desmatamento pós-2020 (regra europeia) / sem embargo, TI ou UC / matrícula ≥50% |
| pasto_ha, secundaria_ha, pasto_ate1km_ha | MapBiomas: pasto, vegetação secundária, pasto a até 1 km de floresta |
| carbono_ha | área além da reserva onde a mata volta sozinha (pasto perto de floresta) |
| regiao_carbono, taxa_tco2_ha_ano, carbono_tco2_ano | taxa de captura usada e potencial bruto (sem linha de base nem vazamento) |
| cacau_aptidao, carbono_solo_ha, rebanho_cabecas, psa_elegivel, biodiversidade_score | frentes extras (estimativas iniciais) |

## Outros arquivos por município

| Arquivo | Colunas |
|---|---|
| filtros_<mun>.csv | quilombo_ha, ti_funai_ha, ti_fase, uc_protecao_integral_ha, uc_uso_sustentavel_ha, uc_apa_ha, filtro_territorial (bloqueio / atencao / ok) |
| extras_<mun>.csv | histórico exportado UMA vez do Earth Engine (não é mais refeito): idade e perdas da vegetação secundária (YbYrá 1987-2024), anos de fogo (1985-2024), vigor e idade do pasto. O ano novo vem da API (mb_fogo_<ano>_ha, mb_supressao_secundaria_<ano>_ha) |
| extras_direto_<mun>.csv | sem Earth Engine: tmf_classe (JRC TMF 2025: 1 intacta, 2 degradada, 3 desmatada, 4 regeneração, 5 água, 6 outro), tmf_floresta_pct, tmf_regeneracao_pct; causa_perda (WRI/Google DeepMind v1.2, 1 km: 1 agricultura permanente, 2 commodities, 3 agricultura itinerante, 4 madeira, 5 incêndio, 6 assentamento e infraestrutura, 7 perturbação natural; 255 = sem perda) |
| direto_<mun>.csv | lido direto dos arquivos públicos: sec_area_ha, sec_idade_media, sec_nova_ha (YbYrá 2024), gpw_altura_m, gpw_ugpp (Global Pasture Watch 2024). Desde 12/11/2026 a soma por imóvel usa zonal_janela (lê uma janela por grupo de imóveis; respeita o valor sem dado) no lugar do exactextract; gpw_altura_m antiga estava contaminada pelo valor sem dado −32000 |
| mapbiomas_<mun>.csv | MapBiomas pela API da Plataforma, sem Earth Engine (ano 2025): mb_floresta_2025_ha, mb_pasto_2025_ha, mb_agricultura_2025_ha, mb_silvicultura_2025_ha, mb_classe_principal_2025 (cobertura col. 11); mb_supressao_primaria_2025_ha, mb_supressao_secundaria_2025_ha, mb_recuperacao_secundaria_2025_ha, mb_veg_secundaria_2025_ha (desmatamento v5); mb_fogo_2025_ha, mb_fogo_mes_principal_2025 (fogo mensal); mb_pasto_idade_anos_media, mb_pasto_vigor_principal (pastagem) |
| certidoes_<mun>.csv | cartório (CNS) e número de matrícula das parcelas SIGEF de cada imóvel, para pedir certidão |
| geo_<mun>.parquet | polígono de cada imóvel (cod_imovel + geometria) |
| resumo_<UF>.csv | uma linha por município com o funil somado |
| sem_imoveis_<UF>.csv | cod_ibge, municipio, verificado_em: municípios sem nenhum imóvel IRU no CAR (ex.: Uiramutã, RR); contam como prontos |
