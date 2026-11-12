/**
 * O que o satélite diz da fazenda, em palavras: floresta tropical (JRC TMF), causa da perda de floresta
 * (WRI/Google DeepMind), fogo (MapBiomas Fogo) e cobertura do ano (MapBiomas). Os códigos seguem docs/colunas.md;
 * código desconhecido aparece como "classe N", sem quebrar a tela.
 */

import type { Imovel } from "./dados/tipos"
import { FOGO } from "./cores"
import { fmtHa, fmtInt } from "./formato"

export interface Classe {
  rotulo: string
  texto: string
  /** tom para o selo: ok (floresta), conferir (atenção), ruim (perda), neutro */
  tom: "ok" | "conferir" | "ruim" | "neutro"
}

/** JRC Tropical Moist Forest 2025 (tmf_classe). */
export const TMF: Record<number, Classe> = {
  1: { rotulo: "Floresta intacta", texto: "floresta tropical sem sinal de corte ou fogo desde 1990", tom: "ok" },
  2: { rotulo: "Floresta degradada", texto: "continua floresta, mas já teve corte seletivo, fogo ou outra perturbação", tom: "conferir" },
  3: { rotulo: "Desmatada", texto: "era floresta tropical e virou outro uso", tom: "ruim" },
  4: { rotulo: "Floresta em regeneração", texto: "mata que voltou depois de ser desmatada", tom: "ok" },
  5: { rotulo: "Água", texto: "água permanente ou de cheia", tom: "neutro" },
  6: { rotulo: "Outra cobertura", texto: "não era floresta tropical úmida (cerrado, campo, cidade)", tom: "neutro" },
}

/** WRI/Google DeepMind, causas da perda de floresta v1.2, grade de 1 km (causa_perda). */
export const CAUSA_PERDA: Record<number, Classe> = {
  1: { rotulo: "Agricultura permanente", texto: "lavoura, pasto ou plantação que ficou no lugar da floresta", tom: "ruim" },
  2: { rotulo: "Mineração e energia", texto: "commodities minerais e de energia (garimpo, mina, petróleo, linhas)", tom: "ruim" },
  3: { rotulo: "Agricultura itinerante", texto: "roça de corte e queima, que depois deixa a mata voltar", tom: "conferir" },
  4: { rotulo: "Extração de madeira", texto: "corte de madeira", tom: "conferir" },
  5: { rotulo: "Incêndio florestal", texto: "fogo que queimou a floresta", tom: "conferir" },
  6: { rotulo: "Assentamento e infraestrutura", texto: "vila, cidade, estrada ou obra", tom: "ruim" },
  7: { rotulo: "Perturbação natural", texto: "vento, seca, cheia ou outra causa natural", tom: "neutro" },
  255: { rotulo: "Sem perda", texto: "nenhuma perda de floresta registrada na grade", tom: "ok" },
}

/** Legenda do MapBiomas (coleções 10 e 11), as classes que aparecem em imóvel rural. */
export const MAPBIOMAS: Record<number, string> = {
  3: "Formação florestal",
  4: "Formação savânica",
  5: "Mangue",
  6: "Floresta alagável",
  9: "Silvicultura",
  11: "Campo alagado",
  12: "Formação campestre",
  13: "Outra formação não florestal",
  15: "Pastagem",
  18: "Agricultura",
  19: "Lavoura temporária",
  20: "Cana",
  21: "Mosaico de usos",
  22: "Área não vegetada",
  23: "Praia, duna e areal",
  24: "Área urbanizada",
  25: "Outra área não vegetada",
  29: "Afloramento rochoso",
  30: "Mineração",
  31: "Aquicultura",
  33: "Rio, lago e oceano",
  35: "Dendê",
  36: "Lavoura perene",
  39: "Soja",
  40: "Arroz",
  41: "Outras lavouras temporárias",
  46: "Café",
  47: "Citros",
  48: "Outras lavouras perenes",
  49: "Restinga arbórea",
  50: "Restinga herbácea",
  62: "Algodão",
}

const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]

export const nomeMes = (m: number | null) => (m && m >= 1 && m <= 12 ? MESES[m - 1] : null)

export const classeTmf = (c: number | null): Classe | null =>
  c === null ? null : (TMF[c] ?? { rotulo: `Classe ${c}`, texto: "código fora da legenda do TMF", tom: "neutro" })

export const causaPerda = (c: number | null): Classe | null =>
  c === null ? null : (CAUSA_PERDA[c] ?? { rotulo: `Causa ${c}`, texto: "código fora da legenda do WRI", tom: "neutro" })

export const classeMapbiomas = (c: number | null) => (c === null ? null : (MAPBIOMAS[c] ?? `Classe ${c}`))

/** Anos com fogo: do mais claro (1 ano) ao mais escuro (6 ou mais). Usado no mapa e na legenda. */
export const ESCALA_FOGO: [number, string][] = [
  [1, FOGO.poucos],
  [3, FOGO.varios],
  [6, FOGO.muitos],
]

export const PERIODO_FOGO = "1985 a 2024"

export function textoFogo(i: Imovel): { historico: string | null; recente: string | null } {
  const historico =
    i.fogo_anos_max === null
      ? null
      : i.fogo_anos_max < 0.5
        ? `Sem fogo registrado de ${PERIODO_FOGO}.`
        : `O ponto do imóvel que mais queimou pegou fogo em ${fmtInt(i.fogo_anos_max)} ${Math.round(i.fogo_anos_max) === 1 ? "ano" : "anos"}, de ${PERIODO_FOGO}.`
  let recente: string | null = null
  if (i.mb_ano !== null && i.mb_fogo_ha !== null) {
    const mes = nomeMes(i.mb_fogo_mes)
    recente =
      i.mb_fogo_ha > 0
        ? `${fmtHa(i.mb_fogo_ha)} queimados em ${i.mb_ano}${mes ? `, a maior parte em ${mes}` : ""}.`
        : `Sem fogo em ${i.mb_ano}.`
  }
  return { historico, recente }
}
