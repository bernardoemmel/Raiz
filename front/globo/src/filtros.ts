/**
 * Filtros da tela principal. Cada um usa só colunas do motor (docs/colunas.md) e diz a regra na dica.
 * Nenhum filtro corta por tamanho: fazenda pequena entra e vai para o projeto agrupado.
 */

import type { Imovel } from "../../compartilhado/dados"

export type FrenteId = "carbono" | "empresa" | "agrupar" | "cacau" | "redd" | "cota"
export type TituloId = "matricula" | "assentamento" | "posse"
export type DesmateId = "5" | "10" | "2008"

export interface Filtros {
  frente: FrenteId
  titulos: TituloId[]
  semDesmate: DesmateId | null
}

export const FILTROS_INICIAIS: Filtros = { frente: "carbono", titulos: ["matricula", "assentamento"], semDesmate: "10" }

export interface Frente {
  id: FrenteId
  rotulo: string
  dica: string
  /** a área que a frente oferece em cada imóvel */
  area: (i: Imovel) => number
  /** o que a área é, na frase "1.941 ha ___" */
  sobre: string
  entra: (i: Imovel) => boolean
  /** a frente depende de coluna que o motor ainda não preenche? */
  disponivel: (todos: Imovel[]) => boolean
}

const sempre = () => true

export const FRENTES: Frente[] = [
  {
    id: "carbono",
    rotulo: "Carbono",
    dica: "Apta ao carbono: sem embargo, TI ou desmate recente, com área aberta além da reserva legal onde a mata volta sozinha e até 5 ha desmatados desde 2016 (regra do motor).",
    area: (i) => i.carbono_ha,
    sobre: "para restaurar",
    entra: (i) => i.apta,
    disponivel: sempre,
  },
  {
    id: "empresa",
    rotulo: "Reserva p/ empresa",
    dica: "Área aberta restaurável em imóvel sem problema, para empresa com meta de remoção na cadeia (FLAG) ou compensação.",
    area: (i) => i.frigorifico_remocao_ha,
    sobre: "restauráveis para meta",
    entra: (i) => !i.problema && i.frigorifico_remocao_ha > 1,
    disponivel: sempre,
  },
  {
    id: "agrupar",
    rotulo: "Agrupar",
    dica: "Aptas que entram juntas num projeto agrupado: lote de assentamento do INCRA ou pequena propriedade (até 4 módulos fiscais).",
    area: (i) => i.carbono_ha,
    sobre: "para restaurar em grupo",
    entra: (i) => i.apta && (i.assentamento || i.pequena),
    disponivel: sempre,
  },
  {
    id: "cacau",
    rotulo: "Cacau",
    dica: "Aptidão para cacau (Embrapa/ZARC). O motor ainda não preenche esta coluna; a frente liga sozinha quando ela chegar.",
    area: (i) => i.carbono_ha,
    sobre: "para cacau com floresta",
    entra: (i) => !i.problema && (i.cacau_aptidao ?? 0) > 0,
    disponivel: (todos) => todos.some((i) => i.cacau_aptidao !== null),
  },
  {
    id: "redd",
    rotulo: "REDD",
    dica: "Floresta em pé além da reserva legal, em imóvel sem problema: desmatamento evitado.",
    area: (i) => i.redd_excedente_ha,
    sobre: "de floresta além da reserva",
    entra: (i) => i.redd_excedente_ha > 1,
    disponivel: sempre,
  },
  {
    id: "cota",
    rotulo: "Cota de Reserva",
    dica: "Floresta sobrando, pelo menos 50 ha além da reserva legal: pode emitir Cota de Reserva Ambiental.",
    area: (i) => i.redd_excedente_ha,
    sobre: "para Cota de Reserva",
    entra: (i) => i.cota_reserva,
    disponivel: sempre,
  },
]

export const TITULOS: { id: TituloId; rotulo: string; dica: string }[] = [
  {
    id: "matricula",
    rotulo: "Matrícula no cartório",
    dica: "Pelo menos 50% do CAR coberto por parcela SIGEF particular com matrícula. A matrícula ainda se confere no cartório.",
  },
  {
    id: "assentamento",
    rotulo: "Lote de assentamento (INCRA)",
    dica: "Pelo menos 50% do CAR dentro de assentamento do INCRA.",
  },
  { id: "posse", rotulo: "Posse em terra pública", dica: "Sem parcela SIGEF com matrícula nem assentamento: título a regularizar." },
]

export const DESMATES: { id: DesmateId; rotulo: string; dica: string; ok: (i: Imovel) => boolean }[] = [
  {
    id: "5",
    rotulo: "5 anos",
    dica: "Até 1 ha desmatado e até 1 ha de alerta depois de 2020 (PRODES e MapBiomas Alerta).",
    ok: (i) => (i.desm_pos2020_ha ?? 0) <= 1 && i.alerta_pos2020_ha <= 1,
  },
  {
    id: "10",
    rotulo: "10 anos",
    dica: "Até 5 ha desmatados depois de 2016 (PRODES), o corte que o motor usa para carbono.",
    ok: (i) => (i.desm_pos2016_ha ?? 0) <= 5,
  },
  {
    id: "2008",
    rotulo: "desde 2008",
    dica: "Até 1 ha desmatado depois de 2008 (PRODES), o marco do Código Florestal.",
    ok: (i) => (i.desm_pos2008_ha ?? 0) <= 1,
  },
]

export function tituloDe(i: Imovel): TituloId {
  if (i.f_matricula >= 0.5) return "matricula"
  if (i.assentamento) return "assentamento"
  return "posse"
}

export const frenteDe = (id: FrenteId) => FRENTES.find((f) => f.id === id) ?? FRENTES[0]

export function aplicar(imoveis: Imovel[], f: Filtros): Imovel[] {
  const frente = frenteDe(f.frente)
  const desmate = DESMATES.find((d) => d.id === f.semDesmate)
  return imoveis
    .filter((i) => frente.entra(i) && f.titulos.includes(tituloDe(i)) && (!desmate || desmate.ok(i)))
    .sort((a, b) => frente.area(b) - frente.area(a))
}
