/**
 * Regras do funil, iguais às de motor/raiz_estado.py (função resumo). Se o motor mudar a regra, muda aqui também:
 * o teste em compartilhado/testes confere que a soma dos imóveis da amostra bate com o resumo_PA.csv.
 *
 *   sem_problema  = não problema (embargo, TI, desmatamento ou alerta depois de 2020, cada um acima de 1 ha)
 *   apta          = sem problema, área de carbono > 0 e no máximo 5 ha desmatados depois de 2016
 *                   (área de carbono = carbono_ha; sem essa coluna, alem_RL_ha, como no motor)
 *   com matrícula = apta e pelo menos 50% do CAR coberto por parcela SIGEF particular com matrícula
 */

import { bool, limpar, n0, num, texto } from "./colunas"
import type { Linha } from "./csv"
import type { Categoria, FunilMunicipio, Imovel } from "./tipos"

/**
 * Um imóvel a partir da linha de imoveis_<mun>.csv e das linhas dos arquivos que o completam (filtros_, extras_,
 * direto_, mapbiomas_), todas pela coluna cod_imovel. A linha principal ganha em caso de coluna repetida.
 */
export function lerImovel(bruta: Linha, complementos: Linha[] = []): Imovel {
  const { linha } = limpar(Object.assign({}, ...complementos, bruta))
  const l = linha
  const ha = n0(l, "ha", n0(l, "area"))
  const temCarbono = "carbono_ha" in l
  const carbono_ha = temCarbono ? n0(l, "carbono_ha") : n0(l, "alem_RL_ha")
  const problema =
    bool(l, "problema") ??
    (n0(l, "embargo_ha") > 1 || n0(l, "ti_ha") > 1 || n0(l, "desm_pos2020_ha") > 1 || n0(l, "alerta_pos2020_ha") > 1)
  const desm_pos2016_ha = num(l, "desm_pos2016_ha")
  const f_matricula = num(l, "f_matricula") ?? (ha > 0 ? n0(l, "matricula_ha") / ha : 0)
  const assentamento_ha = n0(l, "assentamento_ha")
  const m_fiscal = num(l, "m_fiscal")
  const frente = texto(l, "frente")

  const apta = !problema && carbono_ha > 0 && (desm_pos2016_ha ?? 0) <= 5
  const com_matricula = apta && f_matricula >= 0.5
  const assentamento = frente === "assentamento_agrupado" || (ha > 0 && assentamento_ha / ha >= 0.5)

  // MapBiomas pela API: o ano mais recente que vier nas colunas mb_fogo_<ano>_ha
  const anos = Object.keys(l)
    .map((c) => /^mb_fogo_(\d{4})_ha$/.exec(c)?.[1])
    .filter((a): a is string => !!a)
    .sort()
  const mb = anos.length ? anos[anos.length - 1] : null
  const inteiro = (c: string) => {
    const v = num(l, c)
    return v === null ? null : Math.round(v)
  }

  const imovel: Imovel = {
    cod_imovel: l.cod_imovel,
    uf: texto(l, "uf") ?? l.cod_imovel?.slice(0, 2) ?? "",
    municipio: texto(l, "municipio") ?? "",
    cod_ibge: texto(l, "cod_municipio_ibge") ?? "",
    status_imovel: texto(l, "status_imovel"),
    condicao: texto(l, "condicao"),
    ha,
    m_fiscal,
    bioma: texto(l, "bioma"),
    frente,
    problema,
    desm_total_ha: n0(l, "desm_total_ha"),
    desm_pos2008_ha: num(l, "desm_pos2008_ha"),
    desm_pos2016_ha,
    desm_pos2020_ha: num(l, "desm_pos2020_ha"),
    floresta_rem_ha: n0(l, "floresta_rem_ha"),
    nao_floresta_ha: n0(l, "nao_floresta_ha"),
    pasto_ha: num(l, "pasto_ha"),
    secundaria_ha: num(l, "secundaria_ha"),
    pasto_ate1km_ha: num(l, "pasto_ate1km_ha"),
    embargo_ha: n0(l, "embargo_ha"),
    ti_ha: n0(l, "ti_ha"),
    uc_ha: n0(l, "uc_ha"),
    alerta_pos2020_ha: n0(l, "alerta_pos2020_ha"),
    alerta_ultimo_ano: num(l, "alerta_ultimo_ano") || null,
    pct_RL: num(l, "pct_RL"),
    deficit_RL_ha: n0(l, "deficit_RL_ha"),
    alem_RL_ha: n0(l, "alem_RL_ha"),
    app_desmatada_ha: n0(l, "app_desmatada_ha"),
    app_recompor_ha: num(l, "app_recompor_ha"),
    sigef_ha: n0(l, "sigef_ha"),
    matricula_ha: n0(l, "matricula_ha"),
    assentamento_ha,
    f_matricula,
    carbono_ha,
    carbono_tco2_ano: n0(l, "carbono_tco2_ano"),
    taxa_tco2_ha_ano: num(l, "taxa_tco2_ha_ano"),
    regiao_carbono: texto(l, "regiao_carbono"),
    redd_excedente_ha: n0(l, "redd_excedente_ha"),
    frigorifico_remocao_ha: n0(l, "frigorifico_remocao_ha"),
    cota_reserva: bool(l, "cota_reserva") ?? false,
    eudr_ok: bool(l, "eudr_ok"),
    credito_rural_ok: bool(l, "credito_rural_ok"),
    compra_arrendamento: bool(l, "compra_arrendamento"),
    cacau_aptidao: num(l, "cacau_aptidao"),
    fogo_anos_max: num(l, "fogo_anos_max"),
    mb_ano: mb ? Number(mb) : null,
    mb_fogo_ha: mb ? num(l, `mb_fogo_${mb}_ha`) : null,
    mb_fogo_mes: mb ? inteiro(`mb_fogo_mes_principal_${mb}`) : null,
    mb_classe: mb ? inteiro(`mb_classe_principal_${mb}`) : null,
    tmf_classe: inteiro("tmf_classe"),
    tmf_floresta_pct: num(l, "tmf_floresta_pct"),
    tmf_regeneracao_pct: num(l, "tmf_regeneracao_pct"),
    causa_perda: inteiro("causa_perda"),
    filtro_territorial: texto(l, "filtro_territorial"),
    quilombo_ha: num(l, "quilombo_ha"),
    ti_funai_ha: num(l, "ti_funai_ha"),
    ti_fase: texto(l, "ti_fase"),
    apta,
    com_matricula,
    assentamento,
    pequena: m_fiscal !== null && m_fiscal <= 4,
    categoria: "sem_area",
    linha: l,
  }
  imovel.categoria = categoria(imovel)
  return imovel
}

/** Uma cor por imóvel no mapa, na ordem de prioridade. */
export function categoria(i: Pick<Imovel, "problema" | "apta" | "com_matricula" | "assentamento">): Categoria {
  if (i.problema) return "bloqueio"
  if (i.com_matricula) return "apta_matricula"
  if (i.apta && i.assentamento) return "apta_assentamento"
  if (i.apta) return "apta_titulo"
  return "sem_area"
}

export const CATEGORIAS: { id: Categoria; rotulo: string; cor: string }[] = [
  { id: "apta_matricula", rotulo: "Apta, com matrícula", cor: "#1d5a39" },
  { id: "apta_titulo", rotulo: "Apta, título a conferir", cor: "#6fae7b" },
  { id: "apta_assentamento", rotulo: "Apta, assentamento para agrupar", cor: "#d18b2c" },
  { id: "sem_area", rotulo: "Sem área apta agora", cor: "#a7aea6" },
  { id: "bloqueio", rotulo: "Embargo, TI ou desmate recente", cor: "#b5483a" },
]

/** O funil de um município somado a partir dos imóveis: a mesma conta do motor.resumo. */
export function funilDosImoveis(imoveis: Imovel[], cod_ibge: string, municipio: string, uf: string): FunilMunicipio {
  const ok = imoveis.filter((i) => !i.problema)
  const apt = imoveis.filter((i) => i.apta)
  const mat = apt.filter((i) => i.com_matricula)
  const frentes: Record<string, number> = {}
  for (const i of imoveis) if (i.frente) frentes[i.frente] = (frentes[i.frente] ?? 0) + 1
  const soma = (xs: Imovel[], f: (i: Imovel) => number) => Math.round(xs.reduce((s, i) => s + f(i), 0))
  return {
    cod_ibge,
    municipio,
    uf,
    imoveis: imoveis.length,
    sem_problema: ok.length,
    aptas_carbono: apt.length,
    ha_carbono: soma(apt, (i) => i.carbono_ha),
    tco2_ano_aptas: soma(apt, (i) => i.carbono_tco2_ano),
    aptas_com_matricula: mat.length,
    ha_carbono_matricula: soma(mat, (i) => i.carbono_ha),
    para_agrupar: frentes.assentamento_agrupado ?? 0,
    frentes,
    linha: {},
    origem: "imoveis",
  }
}

/** Uma linha do resumo_<UF>.csv, lida pelo nome das colunas. */
export function lerFunil(bruta: Linha, uf: string): FunilMunicipio {
  const { linha: l } = limpar(bruta)
  const frentes: Record<string, number> = {}
  for (const c of Object.keys(l)) if (c.startsWith("frente_")) frentes[c.slice(7)] = n0(l, c)
  return {
    cod_ibge: l.cod_ibge,
    municipio: l.municipio,
    uf,
    imoveis: n0(l, "imoveis"),
    sem_problema: n0(l, "sem_problema"),
    aptas_carbono: n0(l, "aptas_carbono"),
    ha_carbono: n0(l, "ha_carbono"),
    tco2_ano_aptas: n0(l, "tco2_ano_aptas"),
    aptas_com_matricula: n0(l, "aptas_com_matricula"),
    ha_carbono_matricula: n0(l, "ha_carbono_matricula"),
    para_agrupar: frentes.assentamento_agrupado ?? 0,
    frentes,
    linha: l,
    origem: "resumo",
  }
}
