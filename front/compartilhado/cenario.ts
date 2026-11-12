/**
 * Caixa de fatos da fazenda, no formato das "fact boxes" de comunicação de risco: base fixa (cada 100 ha do imóvel)
 * e prazo fixo (10 anos), com três colunas fixas: o que se mede, "não fazer nada" e "restaurar a área apta". Base
 * fixa deixa uma fazenda de 20 ha e uma de 5.000 ha lado a lado; "não fazer nada" é sempre a comparação.
 *
 * Tudo sai das colunas do motor (docs/colunas.md). Linha que depende de coluna que ainda não existe some sozinha e
 * aparece quando o motor entregar a coluna (ex.: rebanho_cabecas, e a conta de dinheiro da etapa E3).
 */

import type { Imovel } from "./dados/tipos"

export const PRAZO_ANOS = 10
export const BASE_HA = 100

export interface LinhaDeFato {
  id: string
  rotulo: string
  unidade: string
  nada: number
  restaurar: number
  /** hectares ou tCO2, para escolher a comparação concreta */
  tipo: "ha" | "tco2" | "cabecas" | "reais"
  nota?: string
}

export interface CaixaDeFatos {
  linhas: LinhaDeFato[]
  notas: string[]
  /** hectares restauráveis a cada 100 ha do imóvel */
  restauravel: number
}

export function caixaDeFatos(i: Imovel): CaixaDeFatos {
  const k = i.ha > 0 ? BASE_HA / i.ha : 0
  const floresta = i.floresta_rem_ha * k
  const aberta = i.desm_total_ha * k
  const restauravel = i.apta ? Math.min(i.carbono_ha * k, aberta) : 0
  const taxa = i.taxa_tco2_ha_ano ?? 0
  const linhas: LinhaDeFato[] = [
    {
      id: "floresta",
      rotulo: "Floresta em pé",
      unidade: "ha",
      nada: floresta,
      restaurar: floresta + restauravel,
      tipo: "ha",
    },
    {
      id: "aberta",
      rotulo: "Pasto e área aberta",
      unidade: "ha",
      nada: aberta,
      restaurar: aberta - restauravel,
      tipo: "ha",
    },
    {
      id: "carbono",
      rotulo: `Carbono tirado do ar em ${PRAZO_ANOS} anos`,
      unidade: "tCO₂",
      nada: 0,
      restaurar: restauravel * taxa * PRAZO_ANOS,
      tipo: "tco2",
      nota: "bruto, antes de descontar linha de base e vazamento",
    },
  ]
  if (i.deficit_RL_ha > 1) {
    const d = i.deficit_RL_ha * k
    linhas.push({
      id: "reserva",
      rotulo: "Reserva legal que falta",
      unidade: "ha",
      nada: d,
      restaurar: d,
      tipo: "ha",
      nota: "a área de carbono fica além da reserva legal; o que falta da reserva se resolve à parte",
    })
  }
  const rebanho = Number(i.linha.rebanho_cabecas)
  if (i.linha.rebanho_cabecas && Number.isFinite(rebanho) && rebanho > 0 && aberta > 0) {
    const g = rebanho * k
    linhas.push({
      id: "gado",
      rotulo: "Gado que a área sustenta",
      unidade: "cabeças",
      nada: g,
      restaurar: (g * (aberta - restauravel)) / aberta,
      tipo: "cabecas",
    })
  }
  const notas = [
    `A cada ${BASE_HA} ha do imóvel, em ${PRAZO_ANOS} anos. "Não fazer nada" supõe que o uso de hoje continua, sem desmatar mais.`,
  ]
  if (taxa)
    notas.push(
      `Captura de ${String(taxa).replace(".", ",")} tCO₂ por hectare por ano (região ${i.regiao_carbono ?? "—"}), a taxa que o motor usa para mata que volta sozinha.`,
    )
  if (!i.apta)
    notas.push(
      i.problema
        ? "Sem área apta agora: há embargo, terra indígena ou desmatamento recente no imóvel."
        : "Sem área apta agora: não sobra área aberta além da reserva legal onde a mata volte sozinha.",
    )
  notas.push("Renda do carbono entra aqui quando a conta de dinheiro (etapa E3) estiver no motor.")
  return { linhas, notas, restauravel }
}
