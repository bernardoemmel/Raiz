/**
 * O que o front usa, já lido pelo nome das colunas do motor (docs/colunas.md). Áreas em hectares, carbono em tCO2
 * por ano. Nada aqui tem nome de pessoa, CPF ou CNPJ.
 */

import type { Linha } from "./csv"

/** Funil de um município: a linha do resumo_<UF>.csv (ou a mesma conta feita a partir dos imóveis). */
export interface FunilMunicipio {
  cod_ibge: string
  municipio: string
  uf: string
  imoveis: number
  sem_problema: number
  aptas_carbono: number
  ha_carbono: number
  tco2_ano_aptas: number
  aptas_com_matricula: number
  ha_carbono_matricula: number
  /** imóveis da frente assentamento_agrupado (lotes do INCRA que entram num projeto agrupado) */
  para_agrupar: number
  /** contagem por frente (colunas frente_*; frente nova do motor aparece aqui sozinha) */
  frentes: Record<string, number>
  /** a linha inteira, inclusive colunas que o front ainda não conhece */
  linha: Linha
  /** de onde veio: o resumo do estado ou a soma dos imóveis */
  origem: "resumo" | "imoveis"
}

export type Categoria = "bloqueio" | "apta_matricula" | "apta_assentamento" | "apta_titulo" | "sem_area"

export interface Imovel {
  cod_imovel: string
  uf: string
  municipio: string
  cod_ibge: string
  status_imovel: string | null
  condicao: string | null
  ha: number
  m_fiscal: number | null
  bioma: string | null
  frente: string | null
  problema: boolean

  // abertura e floresta
  desm_total_ha: number
  desm_pos2008_ha: number | null
  desm_pos2016_ha: number | null
  desm_pos2020_ha: number | null
  floresta_rem_ha: number
  nao_floresta_ha: number
  pasto_ha: number | null
  secundaria_ha: number | null
  pasto_ate1km_ha: number | null

  // bloqueios
  embargo_ha: number
  ti_ha: number
  uc_ha: number
  alerta_pos2020_ha: number
  alerta_ultimo_ano: number | null

  // reserva legal e APP
  pct_RL: number | null
  deficit_RL_ha: number
  alem_RL_ha: number
  app_desmatada_ha: number
  app_recompor_ha: number | null

  // título
  sigef_ha: number
  matricula_ha: number
  assentamento_ha: number
  f_matricula: number

  // frentes
  carbono_ha: number
  carbono_tco2_ano: number
  taxa_tco2_ha_ano: number | null
  regiao_carbono: string | null
  redd_excedente_ha: number
  frigorifico_remocao_ha: number
  cota_reserva: boolean
  eudr_ok: boolean | null
  credito_rural_ok: boolean | null
  compra_arrendamento: boolean | null
  cacau_aptidao: number | null

  // fogo e floresta vistos do satélite (extras_, extras_direto_, mapbiomas_), quando houver
  /** maior número de anos com fogo num ponto do imóvel, 1985 a 2024 (MapBiomas Fogo, extras_) */
  fogo_anos_max: number | null
  /** o ano mais recente do MapBiomas pela API (colunas mb_*_<ano>_*) e o que ele diz */
  mb_ano: number | null
  mb_fogo_ha: number | null
  mb_fogo_mes: number | null
  mb_classe: number | null
  /** JRC TMF: 1 intacta, 2 degradada, 3 desmatada, 4 regeneração, 5 água, 6 outro */
  tmf_classe: number | null
  tmf_floresta_pct: number | null
  tmf_regeneracao_pct: number | null
  /** WRI/Google DeepMind, grade de 1 km: 1 a 7, 255 = sem perda */
  causa_perda: number | null

  // filtros territoriais (filtros_<mun>.csv), quando houver
  filtro_territorial: string | null
  quilombo_ha: number | null
  ti_funai_ha: number | null
  ti_fase: string | null

  // derivados (regras em funil.ts, iguais às do motor)
  apta: boolean
  com_matricula: boolean
  assentamento: boolean
  /** até 4 módulos fiscais: pequena propriedade (Lei 12.651, art. 3º, V) */
  pequena: boolean
  categoria: Categoria

  /** a linha inteira (imóveis + filtros), inclusive colunas que o front ainda não conhece */
  linha: Linha
}

export interface Geo {
  type: "FeatureCollection"
  features: {
    type: "Feature"
    id?: string | number
    properties: Record<string, unknown>
    geometry: { type: string; coordinates: unknown }
  }[]
}

/** terra_publica: glebas públicas não destinadas e UC de uso sustentável de domínio público (só pela API) */
export type CamadaGeo = "municipio" | "imoveis" | "ti" | "uc" | "rios" | "terra_publica"

/**
 * Fazendas aptas (ou aptas com pendência) como ponto, para os agrupamentos no mapa de um estado. Com o contorno da
 * fazenda, um ponto é uma fazenda no lugar dela (n = 1); sem o contorno (município só com o funil, ou sem as
 * geometrias geradas), um ponto soma as fazendas do município no meio dele (n = quantas).
 */
export interface PontoFazenda {
  lon: number
  lat: number
  situacao: "apta" | "pendencia"
  /** hectares que podem voltar a ser mata */
  ha: number
  cod_ibge: string
  /** quantas fazendas o ponto representa */
  n: number
}

/** completo: todos os municípios do estado na lista do IBGE já processados; incompleto: parte; sem_dados: nenhum */
export type SituacaoEstado = "completo" | "incompleto" | "sem_dados"

/** Um estado em GET /estados (no plugin, /amostra/estados.json). */
export interface EstadoDados {
  uf: string
  /** código IBGE do estado (os dois primeiros números do código de cada município) */
  cod: string
  nome: string
  /** municípios do estado na lista do IBGE */
  municipios_ibge: number
  /** quantos deles o motor já processou (funil no resumo ou lista por fazenda) */
  municipios: number
  /** códigos dos municípios com lista por fazenda (imoveis_<cod>.csv) */
  com_lista: string[]
  situacao: SituacaoEstado
  completo: boolean
  /** códigos processados que não estão na lista do IBGE (aviso; não contam em municipios) */
  fora_da_lista: string[]
  /** do estados.json publicado com os dados, quando há: municípios por tabela, versão e quando o estado mudou */
  tabelas?: Record<string, number>
  versao?: string
  atualizado_em?: string
}

export interface Estados {
  /** "amostra" (dados/amostra), "publicada" (com o estados.json do Release dados), "RAIZ_DADOS" ou "api" */
  pasta: string
  /** quando os dados publicados foram montados */
  gerado_em?: string
  /** qual lista do IBGE serviu de régua, por exemplo "DTB 2025 (data base 31/12/2025)" */
  lista_ibge: string
  /** os 27 estados, em ordem de nome */
  estados: EstadoDados[]
}
