/**
 * Funil por etapa (guia, item 4.2): quantos imóveis e hectares chegam a cada etapa, divididos por porte, e por que os
 * outros saíram (um motivo só por imóvel, o primeiro que o tirou, na ordem das regras do motor).
 *
 * As etapas e os limites são os do motor (motor/raiz_estado.py, função resumo): o fim do funil bate com as colunas
 * aptas_com_matricula do resumo. Quando o back-end entregar etapa_funil e motivo_saida por imóvel, eles mandam.
 */

import { MOTIVO, PORTE, PORTE_OPACIDADE, SITUACAO } from "./cores"
import { texto } from "./dados/colunas"
import type { FunilMunicipio, Imovel } from "./dados/tipos"

export type Porte = "pequeno" | "medio" | "grande"
export type Situacao = "apta" | "pendencia" | "nao_apta"
export type EtapaId = "car" | "limpos" | "aptas" | "matricula"
export type MotivoId = keyof typeof MOTIVO

/** Lei 8.629/1993: pequena até 4 módulos fiscais, média de 4 a 15, grande acima de 15. */
export function porteDe(i: Imovel): Porte {
  const p = texto(i.linha, "porte")
  if (p === "pequeno" || p === "medio" || p === "grande") return p
  if (p === "médio") return "medio"
  const mf = i.m_fiscal ?? 0
  return mf <= 4 ? "pequeno" : mf <= 15 ? "medio" : "grande"
}

/** Apta: passou no funil e tem matrícula no SIGEF; com pendência: passou, mas o título falta; não apta: o resto. */
export function situacaoDe(i: Imovel): Situacao {
  if (i.com_matricula) return "apta"
  if (i.apta) return "pendencia"
  return "nao_apta"
}

export const SITUACOES: { id: Situacao; rotulo: string; texto: string; cor: string; cruzada?: boolean }[] = [
  { id: "apta", rotulo: "Apta", texto: "passou no funil e tem matrícula no SIGEF", cor: SITUACAO.apta },
  { id: "pendencia", rotulo: "Apta com pendência", texto: "passou no funil, mas falta o título", cor: SITUACAO.pendencia },
  { id: "nao_apta", rotulo: "Não apta", texto: "saiu em alguma etapa do funil", cor: SITUACAO.naoApta, cruzada: true },
]

export const PORTES: { id: Porte; rotulo: string; cor: string; opacidade: number }[] = [
  { id: "grande", rotulo: "Grande (mais de 15 módulos fiscais)", cor: PORTE.grande, opacidade: PORTE_OPACIDADE.grande },
  { id: "medio", rotulo: "Média (4 a 15 módulos)", cor: PORTE.medio, opacidade: PORTE_OPACIDADE.medio },
  { id: "pequeno", rotulo: "Pequena (até 4 módulos, vai para o projeto agrupado)", cor: PORTE.pequeno, opacidade: PORTE_OPACIDADE.pequeno },
]

export const MOTIVOS: Record<MotivoId, { rotulo: string; frase: (n: string) => string; cor: string }> = {
  embargo: { rotulo: "Embargo do Ibama", frase: (n) => `${n} com embargo do Ibama`, cor: MOTIVO.embargo },
  ti: { rotulo: "Terra indígena", frase: (n) => `${n} sobrepõem terra indígena`, cor: MOTIVO.ti },
  desmate: { rotulo: "Desmatamento depois de 2020", frase: (n) => `${n} com desmatamento depois de 2020`, cor: MOTIVO.desmate },
  alerta: { rotulo: "Alerta depois de 2020", frase: (n) => `${n} com alerta de desmatamento depois de 2020`, cor: MOTIVO.alerta },
  sem_area: {
    rotulo: "Sem área para a mata voltar",
    frase: (n) => `${n} sem pasto perto de floresta além da reserva legal`,
    cor: MOTIVO.sem_area,
  },
  desmate10: { rotulo: "Desmate de 2016 a 2020", frase: (n) => `${n} com desmate entre 2016 e 2020`, cor: MOTIVO.desmate10 },
  assentamento: {
    rotulo: "Lote de assentamento",
    frase: (n) => `${n} são lotes de assentamento (vão para o projeto agrupado)`,
    cor: MOTIVO.assentamento,
  },
  posse: { rotulo: "Sem matrícula", frase: (n) => `${n} sem matrícula no SIGEF (posse a regularizar)`, cor: MOTIVO.posse },
}

interface Regra {
  id: EtapaId
  rotulo: string
  dica: string
  entra: (i: Imovel) => boolean
  /** por que saiu, para quem estava na etapa anterior e não entrou nesta */
  motivo?: (i: Imovel) => MotivoId
}

export const REGRAS: Regra[] = [
  { id: "car", rotulo: "No Cadastro Ambiental Rural (CAR)", dica: "Imóveis rurais ativos ou pendentes no CAR.", entra: () => true },
  {
    id: "limpos",
    rotulo: "Sem embargo, terra indígena nem desmate recente",
    dica: "Cada um acima de 1 ha tira o imóvel: embargo do Ibama, terra indígena, desmatamento ou alerta depois de 2020.",
    entra: (i) => !i.problema,
    motivo: (i) =>
      i.embargo_ha > 1 ? "embargo" : i.ti_ha > 1 ? "ti" : (i.desm_pos2020_ha ?? 0) > 1 ? "desmate" : "alerta",
  },
  {
    id: "aptas",
    rotulo: "Com área para a mata voltar",
    dica: "Pasto perto de floresta, além da reserva legal, e no máximo 5 ha desmatados desde 2016.",
    entra: (i) => i.apta,
    motivo: (i) => (i.carbono_ha <= 0 ? "sem_area" : "desmate10"),
  },
  {
    id: "matricula",
    rotulo: "Com matrícula no cartório",
    dica: "Pelo menos metade do CAR coberta por parcela SIGEF particular com matrícula. Ainda se confere no cartório.",
    entra: (i) => i.com_matricula,
    motivo: (i) => (i.assentamento ? "assentamento" : "posse"),
  },
]

export interface Contagem {
  n: number
  ha: number
}
export interface EtapaFunil {
  id: EtapaId
  rotulo: string
  dica: string
  total: Contagem
  /** por porte; vazio quando só há o resumo do município */
  porte: Partial<Record<Porte, Contagem>>
  /** quem saiu nesta etapa, por motivo, do maior para o menor */
  perdas: { motivo: MotivoId; n: number; ha: number }[]
}

const soma = (xs: Imovel[]): Contagem => ({ n: xs.length, ha: xs.reduce((s, i) => s + i.ha, 0) })

export function etapasDoFunil(imoveis: Imovel[]): EtapaFunil[] {
  let anteriores = imoveis
  return REGRAS.map((r) => {
    const dentro = anteriores.filter(r.entra)
    const fora = r.motivo ? anteriores.filter((i) => !r.entra(i)) : []
    const porMotivo = new Map<MotivoId, Imovel[]>()
    for (const i of fora) {
      const m = r.motivo!(i)
      porMotivo.set(m, [...(porMotivo.get(m) ?? []), i])
    }
    const porte: Partial<Record<Porte, Contagem>> = {}
    for (const p of ["grande", "medio", "pequeno"] as Porte[]) porte[p] = soma(dentro.filter((i) => porteDe(i) === p))
    anteriores = dentro
    return {
      id: r.id,
      rotulo: r.rotulo,
      dica: r.dica,
      total: soma(dentro),
      porte,
      perdas: [...porMotivo.entries()]
        .map(([motivo, xs]) => ({ motivo, ...soma(xs) }))
        .sort((a, b) => b.n - a.n),
    }
  })
}

/** Só com o resumo do município (sem a lista por fazenda): os totais de cada etapa, sem porte nem motivos. */
export function etapasDoResumo(f: FunilMunicipio): EtapaFunil[] {
  const n = [f.imoveis, f.sem_problema, f.aptas_carbono, f.aptas_com_matricula]
  return REGRAS.map((r, k) => ({ id: r.id, rotulo: r.rotulo, dica: r.dica, total: { n: n[k], ha: NaN }, porte: {}, perdas: [] }))
}

/** Em que etapa o imóvel parou (a última que alcançou) e, se saiu, por quê. */
export function etapaDe(i: Imovel): { etapa: EtapaId; motivo: MotivoId | null } {
  let ultima: EtapaId = "car"
  for (const r of REGRAS.slice(1)) {
    if (!r.entra(i)) return { etapa: ultima, motivo: r.motivo!(i) }
    ultima = r.id
  }
  return { etapa: ultima, motivo: null }
}

/** Foco do funil no mapa: os que chegaram a uma etapa, ou os que saíram nela. */
export type Foco = { etapa: EtapaId; lado: "dentro" | "fora" } | null

export function noFoco(i: Imovel, foco: Foco): boolean {
  if (!foco) return true
  const k = REGRAS.findIndex((r) => r.id === foco.etapa)
  const chegou = REGRAS.slice(0, k + 1).every((r) => r.entra(i))
  if (foco.lado === "dentro") return chegou
  const chegouAntes = REGRAS.slice(0, k).every((r) => r.entra(i))
  return chegouAntes && !chegou
}

/**
 * Frase do município no lugar da fileira de números (guia, item 4.1), com dado faltando tratado: nunca "{ano}" nem
 * "undefined" na tela.
 */
export function fraseDoMunicipio(f: FunilMunicipio | null, etapas: EtapaFunil[], fmt: (n: number) => string): string {
  if (!f) return "Este município ainda não foi processado pela Raíz."
  const prontos = f.aptas_com_matricula
  const base = `Dos ${fmt(f.imoveis)} imóveis no CAR de ${f.municipio}, ${fmt(prontos)} ${prontos === 1 ? "está pronto" : "estão prontos"} para conversar`
  // a maior perda entre uma etapa e a seguinte
  let maior: { etapa: EtapaFunil; perdeu: number } | null = null
  for (let k = 1; k < etapas.length; k++) {
    const perdeu = etapas[k - 1].total.n - etapas[k].total.n
    if (!maior || perdeu > maior.perdeu) maior = { etapa: etapas[k], perdeu }
  }
  if (!maior || maior.perdeu <= 0) return base + "."
  const onde: Record<EtapaId, string> = {
    car: "",
    limpos: "em embargo, terra indígena ou desmate recente",
    aptas: "na falta de área para a mata voltar",
    matricula: "na falta de matrícula",
  }
  return `${base}; a maior perda está ${onde[maior.etapa.id]}.`
}
