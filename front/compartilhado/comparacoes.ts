/**
 * Comparações que dão tamanho aos números grandes.
 *
 * - Concretas: hectares em campos de futebol; tCO2 em metano de bois (gado é a medida de quem vive da terra no Pará).
 * - Locais, por índice, no método do Census Reporter (reescrito aqui em português): o valor da fazenda contra a
 *   média ou a distribuição do município, com frases como "cerca do dobro" e "mais que 9 de cada 10 imóveis".
 */

import { fmtCompacto, fmtInt } from "./formato"

/** Campo de futebol: 105 m × 68 m = 0,714 ha (medida recomendada pela FIFA e usada pela CBF). */
export const HA_POR_CAMPO = (105 * 68) / 10_000

/**
 * Metano de um boi num ano, em tCO2 equivalente: 56 kg de CH4 por cabeça por ano (IPCC 2006, vol. 4, cap. 10,
 * tabela 10.11, América Latina, "outros bovinos") × 27 (potencial de aquecimento em 100 anos do metano não fóssil,
 * IPCC AR6, 2021) = 1,512 tCO2e.
 */
export const TCO2E_POR_BOI_ANO = (56 * 27) / 1000

export function camposDeFutebol(ha: number): string {
  const n = ha / HA_POR_CAMPO
  if (n < 0.75) return "menos de um campo de futebol"
  if (n < 1.5) return "é um campo de futebol"
  return `são ${n >= 10_000 ? fmtCompacto(n) : fmtInt(n)} campos de futebol`
}

export function boisPorAno(tco2: number): string {
  const n = tco2 / TCO2E_POR_BOI_ANO
  if (n < 1.5) return "o metano de um boi em um ano"
  return `o metano de ${n >= 10_000 ? fmtCompacto(n) : fmtInt(n)} bois em um ano`
}

/**
 * Frase por índice (valor ÷ referência × 100), como no Census Reporter. `ref` é o nome feminino da referência,
 * sem artigo, por exemplo "média do município". Devolve null quando não dá para comparar.
 */
export function fraseIndice(valor: number, referencia: number, ref: string): string | null {
  if (!(referencia > 0) || !Number.isFinite(valor)) return null
  const i = (100 * valor) / referencia
  if (i >= 195) {
    const vezes = Math.round(i / 100)
    if (vezes === 2) return `cerca do dobro da ${ref}`
    if (vezes === 3) return `cerca do triplo da ${ref}`
    return `cerca de ${fmtInt(vezes)} vezes a ${ref}`
  }
  if (i >= 175) return `quase o dobro da ${ref}`
  if (i >= 140) return `cerca de uma vez e meia a ${ref}`
  if (i >= 115) return `cerca de ${fmtInt(Math.round((i - 100) / 5) * 5)}% acima da ${ref}`
  if (i >= 105) return `um pouco acima da ${ref}`
  if (i > 95) return `quase igual à ${ref}`
  if (i > 85) return `um pouco abaixo da ${ref}`
  if (i >= 60) return `cerca de ${fmtInt(Math.round((100 - i) / 5) * 5)}% abaixo da ${ref}`
  if (i >= 40) return `cerca da metade da ${ref}`
  if (i >= 28) return `cerca de um terço da ${ref}`
  if (i >= 20) return `cerca de um quarto da ${ref}`
  return `menos de um quinto da ${ref}`
}

/**
 * Posição do valor entre os valores do município: "mais que 9 de cada 10 imóveis de X". Só fala quando a fazenda
 * está bem acima ou bem abaixo; no meio, devolve null (a frase não ajudaria).
 */
export function frasePosicao(valor: number, todos: number[], onde: string): string | null {
  if (todos.length < 10) return null
  const abaixo = todos.filter((v) => v < valor).length / todos.length
  const acima = todos.filter((v) => v > valor).length / todos.length
  if (abaixo >= 0.7) {
    const em10 = Math.floor(abaixo * 10)
    if (abaixo >= 0.99) return `maior que 99 de cada 100 imóveis de ${onde}`
    return `maior que ${em10} de cada 10 imóveis de ${onde}`
  }
  if (acima >= 0.7) return `menor que ${Math.floor(acima * 10)} de cada 10 imóveis de ${onde}`
  return null
}

export function mediana(xs: number[]): number {
  if (!xs.length) return 0
  const s = [...xs].sort((a, b) => a - b)
  const m = s.length >> 1
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2
}
