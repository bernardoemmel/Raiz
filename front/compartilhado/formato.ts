/** Números e códigos no jeito brasileiro: 9.703, 1,9 mil, 4,2 milhões, 63,8 módulos. */

const inteiro = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 })
const umaCasa = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const ateUmaCasa = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 })

export const fmtInt = (n: number) => inteiro.format(Math.round(n))
export const fmt1 = (n: number) => umaCasa.format(n)

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

/** Situação do CAR (status_imovel do SICAR) em palavras. */
export const STATUS_CAR: Record<string, string> = {
  AT: "ativo",
  PE: "pendente",
  SU: "suspenso",
  CA: "cancelado",
}
