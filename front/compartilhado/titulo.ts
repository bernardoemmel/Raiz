/**
 * Situação do título da terra de um imóvel, a partir do cruzamento do CAR com o SIGEF que o motor faz.
 *
 * O SIGEF diz se a parcela tem matrícula, mas não confere a matrícula: isso só a certidão do cartório faz (etapa E5).
 * Por isso, enquanto ninguém conferiu, toda matrícula vem com o selo "matrícula a conferir". Quando o back-end
 * entregar a coluna `matricula_conferida` (True/False), o selo muda sozinho.
 */

import { bool } from "./dados/colunas"
import type { Imovel } from "./dados/tipos"
import { fmtPct } from "./formato"

export type SeloTitulo = "matricula_conferida" | "matricula_a_conferir" | "assentamento" | "sem_matricula"

export interface SituacaoTitulo {
  selo: SeloTitulo
  rotulo: string
  /** classe visual: ok, conferir, neutro, ruim */
  tom: "ok" | "conferir" | "neutro" | "ruim"
  texto: string
}

export function situacaoTitulo(i: Imovel): SituacaoTitulo {
  const conferida = bool(i.linha, "matricula_conferida")
  const pct = fmtPct(i.f_matricula)
  if (i.f_matricula > 0.001 && conferida === true)
    return {
      selo: "matricula_conferida",
      rotulo: "Matrícula conferida",
      tom: "ok",
      texto: `${pct} do CAR coberto por parcela com matrícula, conferida no cartório.`,
    }
  if (i.f_matricula >= 0.5)
    return {
      selo: "matricula_a_conferir",
      rotulo: "Matrícula a conferir",
      tom: "conferir",
      texto: `${pct} do CAR coberto por parcela SIGEF particular com matrícula. Falta conferir a matrícula no cartório (certidão de inteiro teor).`,
    }
  if (i.f_matricula > 0.001)
    return {
      selo: "matricula_a_conferir",
      rotulo: "Matrícula a conferir",
      tom: "conferir",
      texto: `Só ${pct} do CAR tem parcela SIGEF com matrícula; o resto pode ser posse. Conferir no cartório e com o dono.`,
    }
  if (i.assentamento)
    return {
      selo: "assentamento",
      rotulo: "Lote de assentamento",
      tom: "neutro",
      texto: `${fmtPct(i.ha > 0 ? i.assentamento_ha / i.ha : 0)} do CAR dentro de assentamento do INCRA: entra em projeto agrupado, com o INCRA.`,
    }
  return {
    selo: "sem_matricula",
    rotulo: "Sem matrícula no SIGEF",
    tom: "ruim",
    texto: "Nenhuma parcela SIGEF com matrícula no CAR: posse ou terra pública, título a regularizar antes do contrato.",
  }
}
