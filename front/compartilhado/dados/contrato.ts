/**
 * Colunas que docs/colunas.md documenta. Coluna fora desta lista não quebra nada: a ficha a mostra como
 * "coluna nova" em "Outros dados do motor", para o fundador ver o que o motor passou a entregar.
 */
export const COLUNAS_CONHECIDAS = new Set(
  (
    "cod_imovel id status_imovel dat_criacao data_atualizacao area condicao uf municipio cod_municipio_ibge m_fiscal " +
    "tipo_imovel ha desm_pos2008_ha desm_pos2016_ha desm_pos2020_ha desm_total_ha nao_floresta_ha floresta_rem_ha " +
    "embargo_ha ti_ha uc_ha sigef_ha matricula_ha assentamento_ha f_matricula projeto_carbono_ha alerta_ha " +
    "alerta_pos2020_ha alerta_ultimo_ano app_desmatada_ha app_escadinha_ha app_recompor_ha bioma pct_RL pct_RL_alem " +
    "deficit_RL_ha deficit_RL_alem_ha deficit_RL80_ha deficit_RL50_ha alem_RL_ha problema frente cota_reserva " +
    "redd_excedente_ha frigorifico_remocao_ha compensacao_restauravel_ha eudr_ok credito_rural_ok compra_arrendamento " +
    "pasto_ha secundaria_ha pasto_ate1km_ha carbono_ha regiao_carbono taxa_tco2_ha_ano carbono_tco2_ano cacau_aptidao " +
    "carbono_solo_ha rebanho_cabecas psa_elegivel biodiversidade_score quilombo_ha ti_funai_ha ti_fase " +
    "uc_protecao_integral_ha uc_uso_sustentavel_ha uc_apa_ha filtro_territorial"
  ).split(" "),
)

/** Nomes legíveis das colunas mais usadas (o resto aparece pelo nome técnico). */
export const NOMES_COLUNAS: Record<string, string> = {
  cod_imovel: "Código do CAR",
  status_imovel: "Situação do CAR",
  condicao: "Condição da análise do CAR",
  ha: "Área do polígono (ha)",
  area: "Área declarada no CAR (ha)",
  m_fiscal: "Módulos fiscais",
  bioma: "Bioma",
  frente: "Caminho (frente) do motor",
  desm_total_ha: "Área aberta (ha)",
  floresta_rem_ha: "Floresta que sobrou (ha)",
  nao_floresta_ha: "Vegetação que não é floresta e água (ha)",
  desm_pos2008_ha: "Desmatado depois de 2008 (ha)",
  desm_pos2016_ha: "Desmatado depois de 2016 (ha)",
  desm_pos2020_ha: "Desmatado depois de 2020 (ha)",
  embargo_ha: "Embargo do Ibama (ha)",
  ti_ha: "Em terra indígena (ha)",
  uc_ha: "Em unidade de conservação (ha)",
  sigef_ha: "Parcelas SIGEF (ha)",
  matricula_ha: "Parcelas com matrícula (ha)",
  assentamento_ha: "Em assentamento (ha)",
  f_matricula: "Fração com matrícula",
  alerta_pos2020_ha: "Alertas depois de 2020 (ha)",
  alerta_ultimo_ano: "Ano do último alerta",
  app_desmatada_ha: "APP aberta, faixa de 30 m (ha)",
  app_recompor_ha: "APP a recompor, escadinha (ha)",
  pct_RL: "Reserva legal (%)",
  deficit_RL_ha: "Reserva legal que falta (ha)",
  alem_RL_ha: "Aberto além da reserva legal (ha)",
  pasto_ha: "Pasto (ha)",
  secundaria_ha: "Mata que voltou sozinha (ha)",
  pasto_ate1km_ha: "Pasto a até 1 km de floresta (ha)",
  carbono_ha: "Área de carbono (ha)",
  taxa_tco2_ha_ano: "Taxa de captura (tCO₂/ha/ano)",
  carbono_tco2_ano: "Carbono bruto (tCO₂/ano)",
  regiao_carbono: "Região da taxa de carbono",
  redd_excedente_ha: "Floresta além da reserva (ha)",
  frigorifico_remocao_ha: "Restaurável para meta de empresa (ha)",
  filtro_territorial: "Filtro territorial",
}
