/**
 * Leitura de colunas pelo nome, tolerante: coluna que não existe vira null (ou o padrão pedido), valor vazio ou
 * "nan" vira null, e colunas que o front não conhece ficam guardadas na linha para quem quiser mostrar.
 */

import { colunaPessoal, mascarar } from "../privacidade"
import type { Linha } from "./csv"

const VAZIOS = new Set(["", "nan", "NaN", "None", "null", "NULL", "NA", "<NA>"])

export function num(l: Linha, coluna: string): number | null {
  const v = l[coluna]
  if (v === undefined || VAZIOS.has(v.trim())) return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

/** Número com padrão quando falta (para somas e comparações). */
export const n0 = (l: Linha, coluna: string, padrao = 0) => num(l, coluna) ?? padrao

export function bool(l: Linha, coluna: string): boolean | null {
  const v = l[coluna]?.trim().toLowerCase()
  if (v === undefined || VAZIOS.has(v)) return null
  if (["true", "1", "sim", "s", "yes"].includes(v)) return true
  if (["false", "0", "não", "nao", "n", "no"].includes(v)) return false
  return null
}

export function texto(l: Linha, coluna: string): string | null {
  const v = l[coluna]
  return v === undefined || VAZIOS.has(v.trim()) ? null : v
}

/** Tira colunas pessoais e mascara CPF/CNPJ em todo valor de texto. Devolve a linha limpa e o que saiu. */
export function limpar(l: Linha): { linha: Linha; removidas: string[] } {
  const linha: Linha = {}
  const removidas: string[] = []
  for (const [c, v] of Object.entries(l)) {
    if (colunaPessoal(c)) removidas.push(c)
    else linha[c] = /\d{11}|\d{3}\.\d{3}/.test(v) ? mascarar(v) : v
  }
  return { linha, removidas }
}

/** Converte um objeto JSON da API em Linha (tudo texto), para passar pelos mesmos leitores do CSV. */
export function comoLinha(obj: Record<string, unknown>): Linha {
  const l: Linha = {}
  for (const [k, v] of Object.entries(obj)) {
    if (v === null || v === undefined) l[k] = ""
    else if (typeof v === "boolean") l[k] = v ? "True" : "False"
    else if (typeof v === "object") continue
    else l[k] = String(v)
  }
  return l
}
