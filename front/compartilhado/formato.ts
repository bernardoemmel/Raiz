/** Números e códigos no jeito brasileiro: 9.703, 1,9 mil, 4,2 milhões, 63,8 módulos. */

const inteiro = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 })
const umaCasa = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const ateUmaCasa = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 })

export const fmtInt = (n: number) => inteiro.format(Math.round(n))
export const fmt1 = (n: number) => umaCasa.format(n)

/** Mantém as datas do painel no fuso de Brasília e reutiliza o formatador entre linhas e renderizações. */
let dataHoraBrasilia: Intl.DateTimeFormat | undefined
export function fmtDataHoraBrasilia(valor: string): string {
  const data = new Date(valor)
  if (!Number.isFinite(data.getTime())) return data.toLocaleString("pt-BR")
  dataHoraBrasilia ??= new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", dateStyle: "short", timeStyle: "short" })
  return dataHoraBrasilia.format(data)
}

/** Hectares: inteiro a partir de 10 ha, uma casa abaixo disso. */
export function fmtHa(n: number, unidade = true): string {
  const v = Math.abs(n) >= 10 || n === 0 ? fmtInt(n) : ateUmaCasa.format(n)
  return unidade ? `${v} ha` : v
}

/** 690 → "690"; 15.900 → "15,9 mil"; 4.226.631 → "4,2 milhões". */
export function fmtCompacto(n: number): string {
  const a = Math.abs(n)
  if (a >= 1e9) return `${ateUmaCasa.format(n / 1e9)} ${a >= 2e9 ? "bilhões" : "bilhão"}`
  if (a >= 1e6) return `${ateUmaCasa.format(n / 1e6)} ${a >= 2e6 ? "milhões" : "milhão"}`
  if (a >= 1e4) return `${ateUmaCasa.format(n / 1e3)} mil`
  return fmtInt(n)
}

/**
 * Destaque de carbono e dinheiro: 2 algarismos significativos, com unidade por extenso no texto
 * (4.417 → "4.400"; 15.900 → "16 mil"; 4.226.631 → "4,2 milhões"). O valor exato fica em "Ver como calculamos".
 */
export function fmtDestaque(n: number): string {
  if (!Number.isFinite(n) || n === 0) return "0"
  const a = Math.abs(n)
  const casas = Math.floor(Math.log10(a)) - 1
  const r = Math.round(n / 10 ** casas) * 10 ** casas
  const ra = Math.abs(r)
  if (ra >= 1e9) return `${ateUmaCasa.format(r / 1e9)} ${ra >= 2e9 ? "bilhões" : "bilhão"}`
  if (ra >= 1e6) return `${ateUmaCasa.format(r / 1e6)} ${ra >= 2e6 ? "milhões" : "milhão"}`
  if (ra >= 1e4) return `${inteiro.format(r / 1e3)} mil`
  return inteiro.format(r)
}

export const fmtPct = (f: number) => `${inteiro.format(Math.round(f * 100))}%`

export const fmtModulos = (m: number) => `${ateUmaCasa.format(m)} ${m >= 2 || m === 0 ? "módulos" : "módulo"}`

export const plural = (n: number, um: string, varios: string) => `${fmtInt(n)} ${Math.round(n) === 1 ? um : varios}`

/** PA-1507300-F293C0...B5FE → "PA-1507300-F293…B5FE": curto para lista, sem perder o começo e o fim. */
export function abreviarCar(cod: string): string {
  const partes = cod.split("-")
  if (partes.length < 3) return cod
  const hash = partes.slice(2).join("-")
  if (hash.length <= 10) return cod
  return `${partes[0]}-${partes[1]}-${hash.slice(0, 4)}…${hash.slice(-4)}`
}

/** Remove acentos e caixa, para busca. */
export const normalizar = (s: string) =>
  s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .trim()

export const UFS: Record<string, string> = {
  AC: "Acre",
  AL: "Alagoas",
  AM: "Amazonas",
  AP: "Amapá",
  BA: "Bahia",
  CE: "Ceará",
  DF: "Distrito Federal",
  ES: "Espírito Santo",
  GO: "Goiás",
  MA: "Maranhão",
  MG: "Minas Gerais",
  MS: "Mato Grosso do Sul",
  MT: "Mato Grosso",
  PA: "Pará",
  PB: "Paraíba",
  PE: "Pernambuco",
  PI: "Piauí",
  PR: "Paraná",
  RJ: "Rio de Janeiro",
  RN: "Rio Grande do Norte",
  RO: "Rondônia",
  RR: "Roraima",
  RS: "Rio Grande do Sul",
  SC: "Santa Catarina",
  SE: "Sergipe",
  SP: "São Paulo",
  TO: "Tocantins",
}

// artigo de cada estado: "do Pará", "da Bahia", "de Goiás" (Mato Grosso e Mato Grosso do Sul sem artigo, como o IBGE)
const DO_ESTADO: Record<string, "do" | "da" | "de"> = {
  AC: "do", AL: "de", AM: "do", AP: "do", BA: "da", CE: "do", DF: "do", ES: "do", GO: "de", MA: "do", MG: "de",
  MS: "de", MT: "de", PA: "do", PB: "da", PE: "de", PI: "do", PR: "do", RJ: "do", RN: "do", RO: "de", RR: "de",
  RS: "do", SC: "de", SE: "de", SP: "de", TO: "do",
}

/** "PA" → "do Pará", "BA" → "da Bahia", "GO" → "de Goiás" */
export const doEstado = (uf: string) => (UFS[uf] ? `${DO_ESTADO[uf] ?? "de"} ${UFS[uf]}` : uf)

/** Os dois primeiros números do código IBGE do município são os do estado (11 é Rondônia, 15 é o Pará...). */
export const UF_POR_CODIGO: Record<string, string> = {
  "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
  "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA",
  "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS",
  "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}

/** "1507300" → "PA"; também aceita o código do CAR ("PA-1507300-…"). Null se não for de estado nenhum. */
export function ufDoCodigo(cod: string): string | null {
  const m = /^(?:[A-Za-z]{2}-?)?(\d{2})\d{5}/.exec(cod.trim())
  return m ? (UF_POR_CODIGO[m[1]] ?? null) : null
}

/** Situação do CAR (status_imovel do SICAR) em palavras. */
export const STATUS_CAR: Record<string, string> = {
  AT: "ativo",
  PE: "pendente",
  SU: "suspenso",
  CA: "cancelado",
}
