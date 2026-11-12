/**
 * Valor para quem restaura com crédito de carbono (o desenvolvedor), lido das colunas de desenvolvedor_<mun>.csv
 * (docs/colunas.md), que o back-end calcula em raiz/restauracao.py. Tudo é estimativa em faixa P10 a P90: a tela
 * sempre mostra o aviso e a faixa, nunca um número solto.
 */

import { num, texto } from "./dados/colunas"
import type { Linha } from "./dados/csv"

export type Modo = "regeneracao_assistida" | "semeadura_direta" | "plantio_total"

export const MODOS: { id: Modo; nome: string; curto: string }[] = [
  { id: "regeneracao_assistida", nome: "Regeneração assistida", curto: "Regeneração" },
  { id: "semeadura_direta", nome: "Semeadura direta (muvuca)", curto: "Semeadura" },
  { id: "plantio_total", nome: "Plantio total de mudas", curto: "Plantio" },
]

export const AVISO =
  "Estimativa da Raíz para orientar a conversa com o desenvolvedor. Não é orçamento nem promessa de crédito: custos, captura e linha de base são premissas a calibrar com dados reais."

export interface Faixa {
  p10: number
  p50: number
  p90: number
}

export interface Restauracao {
  modo: Modo
  nomeModo: string
  areaHa: number
  porModoHa: Record<Modo, number>
  custoHa: Faixa
  capturaHaAno: Faixa
  creditoHaAno: Faixa
  creditoAno: number
  descontoLinhaBase: number
  descontoLinhaBasePct: number
  regeneraSozinhaPct: number
  linhaBaseFonte: string | null
  vplHa: Faixa
  tirProjetoPct: Faixa
  tirAlavancadaPct: Faixa
  picoCapitalHa: Faixa
  valorDesenvolvedor: number
  lote: {
    id: string
    imoveis: number
    ha: number
    creditosNoPrazo: number
    fechaContrato: boolean
    haParaContrato: number | null
  } | null
  faltou: string[]
  cenario: string
  versao: string | null
}

const TEXTO_FALTOU: Record<string, string> = {
  distancia_mata: "distância do pasto à mata",
  declividade: "declividade",
  chuva: "chuva",
  solo: "solo",
  acesso: "distância da estrada e da cidade",
  fogo: "histórico de fogo",
  idade_pasto: "idade do pasto",
  vigor_pasto: "vigor do pasto",
  linha_base_municipio: "linha de base medida no município",
}

export const textoFaltou = (id: string) => TEXTO_FALTOU[id] ?? id

function faixa(l: Linha, base: string, p50?: string): Faixa | null {
  const m = num(l, p50 ?? `${base}_p50`)
  if (m === null) return null
  const a = num(l, `${base}_p10`) ?? m
  const b = num(l, `${base}_p90`) ?? m
  return { p10: Math.min(a, m), p50: m, p90: Math.max(b, m) }
}

/** null quando o município ainda não tem o cálculo (a ficha mostra o estado vazio). */
export function lerRestauracao(l: Linha): Restauracao | null {
  const modo = texto(l, "modo_restauracao") as Modo | null
  const m = MODOS.find((x) => x.id === modo)
  const custo = faixa(l, "custo_restauracao_ha")
  const captura = faixa(l, "captura_tco2_ha_ano")
  const credito = faixa(l, "credito_liquido_tco2_ha_ano", "credito_liquido_tco2_ha_ano")
  const vpl = faixa(l, "vpl_rs_ha")
  const tirP = faixa(l, "tir_projeto_pct")
  const tirA = faixa(l, "tir_alavancada_pct")
  const pico = faixa(l, "pico_capital_proprio_rs_ha")
  if (!m || !custo || !captura || !credito || !vpl || !tirP || !tirA || !pico) return null
  const grupo = texto(l, "grupo_id")
  return {
    modo: m.id,
    nomeModo: m.nome,
    areaHa: num(l, "restauracao_area_ha") ?? 0,
    porModoHa: Object.fromEntries(MODOS.map((x) => [x.id, num(l, `restauracao_${x.id}_ha`) ?? 0])) as Record<Modo, number>,
    custoHa: custo,
    capturaHaAno: captura,
    creditoHaAno: credito,
    creditoAno: num(l, "credito_liquido_tco2_ano") ?? 0,
    descontoLinhaBase: num(l, "desconto_linha_base") ?? 0,
    descontoLinhaBasePct: num(l, "desconto_linha_base_pct") ?? 0,
    regeneraSozinhaPct: num(l, "linha_base_regenera_pct") ?? 0,
    linhaBaseFonte: texto(l, "linha_base_fonte"),
    vplHa: vpl,
    tirProjetoPct: tirP,
    tirAlavancadaPct: tirA,
    picoCapitalHa: pico,
    valorDesenvolvedor: num(l, "valor_desenvolvedor_rs") ?? 0,
    lote: grupo
      ? {
          id: grupo,
          imoveis: num(l, "grupo_imoveis") ?? 1,
          ha: num(l, "grupo_ha") ?? 0,
          creditosNoPrazo: num(l, "grupo_creditos_prazo") ?? 0,
          fechaContrato: (texto(l, "grupo_fecha_contrato") ?? "").toLowerCase() === "true",
          haParaContrato: num(l, "grupo_ha_para_contrato"),
        }
      : null,
    faltou: (texto(l, "restauracao_faltou") ?? "").split(",").filter(Boolean),
    cenario: texto(l, "restauracao_cenario") ?? "profloresta_55",
    versao: texto(l, "restauracao_versao"),
  }
}

// --- painel do município: ordenar e filtrar pelo valor para quem restaura ---------------------------------------

export type OrdemRestauracao = "area" | "valor" | "vpl_ha" | "tir"

export const ORDENS: { id: OrdemRestauracao; rotulo: string }[] = [
  { id: "area", rotulo: "Área" },
  { id: "valor", rotulo: "Valor para quem restaura" },
  { id: "vpl_ha", rotulo: "Valor por hectare" },
  { id: "tir", rotulo: "Retorno com financiamento" },
]

function chave(r: Restauracao | null, ordem: OrdemRestauracao): number | null {
  if (!r) return null
  if (ordem === "valor") return r.valorDesenvolvedor
  if (ordem === "vpl_ha") return r.vplHa.p50
  if (ordem === "tir") return r.tirAlavancadaPct.p50
  return null
}

/** Ordena (sem cortar ninguém) e filtra pelo modo. Fazenda ainda sem o cálculo vai para o fim. */
export function ordenarFiltrar<T extends { linha: Linha }>(lista: T[], ordem: OrdemRestauracao, modo: Modo | null): T[] {
  const comR = lista.map((i) => ({ i, r: lerRestauracao(i.linha) }))
  const filtrada = modo ? comR.filter((x) => x.r?.modo === modo) : comR
  if (ordem === "area") return filtrada.map((x) => x.i)
  return [...filtrada]
    .sort((a, b) => {
      const ka = chave(a.r, ordem)
      const kb = chave(b.r, ordem)
      if (ka === null && kb === null) return 0
      if (ka === null) return 1
      if (kb === null) return -1
      return kb - ka
    })
    .map((x) => x.i)
}

// --- números -----------------------------------------------------------------------------------------------------

const dois = new Intl.NumberFormat("pt-BR", { maximumSignificantDigits: 2 })
const inteiro = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 })
const umaCasa = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 })

/** R$ com 2 algarismos significativos: "R$ 14 mil", "R$ 3,5 mil", "R$ 1,2 milhão", "menos R$ 5,9 mil". */
export function fmtReais(n: number): string {
  const a = Math.abs(n)
  const sinal = n < 0 ? "menos " : ""
  if (a >= 1e6) return `${sinal}R$ ${dois.format(a / 1e6)} ${a >= 2e6 ? "milhões" : "milhão"}`
  if (a >= 1e3) return `${sinal}R$ ${dois.format(a / 1e3)} mil`
  return `${sinal}R$ ${inteiro.format(a)}`
}

export const fmtNum1 = (n: number) => umaCasa.format(n)
export const fmtPct1 = (n: number) => `${umaCasa.format(n)}%`

/** "cerca de 7,2 t por ha por ano (de 5,5 a 10,1)": a faixa que o analista lê, com a unidade uma vez só. */
export function fmtFaixa(f: Faixa, fmt: (n: number) => string, unidade = ""): string {
  const u = unidade ? ` ${unidade}` : ""
  return `cerca de ${fmt(f.p50)}${u} (de ${fmt(f.p10)} a ${fmt(f.p90)})`
}
