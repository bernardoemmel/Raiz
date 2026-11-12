/**
 * Caminho da terra (raiz/terra.py, terra_<mun>.csv, docs/colunas.md): a situação da terra não tira ninguém do
 * funil; cada fazenda segue um caminho com risco. Sem a coluna caminho_terra (amostra antiga), o caminho sai das
 * colunas do motor com a mesma ordem de decisão. Nunca chamar posse de propriedade.
 */

import { n0, num, texto } from "./dados/colunas"
import type { Linha } from "./dados/csv"

export type Caminho =
  | "privada_matricula"
  | "posse_em_titulacao"
  | "assentamento"
  | "publica_concessao"
  | "publica_sem_destinacao"
  | "terra_indigena_ou_tradicional"
export type SituacaoTerra = "pronta_agora" | "em_espera" | "so_mostrar"
export type Risco = "baixo" | "medio" | "alto"

export const CAMINHOS: { id: Caminho; nome: string; curto: string; situacao: SituacaoTerra; dica: string }[] = [
  {
    id: "privada_matricula",
    nome: "Privada com matrícula",
    curto: "matrícula a conferir",
    situacao: "pronta_agora",
    dica: "Matrícula achada no SIGEF em metade do CAR ou mais; a cadeia dominial ainda se confere no cartório.",
  },
  {
    id: "publica_concessao",
    nome: "Pública sob concessão",
    curto: "área pública concedida",
    situacao: "pronta_agora",
    dica: "Dentro de área pública concedida ou em edital de concessão (SFB ou Ideflor-Bio); pronta para o concessionário.",
  },
  {
    id: "posse_em_titulacao",
    nome: "Posse em titulação",
    curto: "posse em titulação",
    situacao: "em_espera",
    dica: "Posse sem matrícula: entra quando o título sair (Iterpa, INCRA ou Terra Legal). Estoque futuro.",
  },
  {
    id: "assentamento",
    nome: "Assentamento",
    curto: "assentamento",
    situacao: "em_espera",
    dica: "Lote de projeto de assentamento do INCRA: depende de aval do INCRA; fora da fase 1 do ProFloresta+.",
  },
  {
    id: "publica_sem_destinacao",
    nome: "Pública sem destinação",
    curto: "terra pública",
    situacao: "so_mostrar",
    dica: "Gleba pública não destinada ou unidade de conservação: não se origina com particular; candidata a concessão.",
  },
  {
    id: "terra_indigena_ou_tradicional",
    nome: "Terra indígena ou tradicional",
    curto: "terra indígena ou tradicional",
    situacao: "so_mostrar",
    dica: "Terra indígena, quilombo ou reserva de comunidade tradicional: fora da originação comercial.",
  },
]

export const SITUACOES: { id: SituacaoTerra; nome: string }[] = [
  { id: "pronta_agora", nome: "Pronta agora" },
  { id: "em_espera", nome: "Em espera" },
  { id: "so_mostrar", nome: "Só mostrar" },
]

export const NOME_RISCO: Record<Risco, string> = { baixo: "baixo", medio: "médio", alto: "alto" }

export const infoCaminho = (c: Caminho) => CAMINHOS.find((x) => x.id === c) ?? CAMINHOS[2]

/** O caminho gravado em terra_<mun>.csv ou, sem ele, o das colunas do motor (mesma ordem da regra). */
export function caminhoDe(l: Linha): Caminho {
  const c = texto(l, "caminho_terra") as Caminho | null
  if (c && CAMINHOS.some((x) => x.id === c)) return c
  const ha = n0(l, "ha") || n0(l, "area")
  const fr = (x: number) => (ha > 0 ? x / ha : 0)
  const trad = Math.max(n0(l, "ti_ha"), n0(l, "ti_funai_ha")) + n0(l, "quilombo_ha")
  if (trad >= 1 && fr(trad) >= 0.05) return "terra_indigena_ou_tradicional"
  if (fr(n0(l, "uc_protecao_integral_ha")) >= 0.5) return "publica_sem_destinacao"
  if ((texto(l, "tipo_imovel") ?? "").toUpperCase() === "AST" || fr(n0(l, "assentamento_ha")) >= 0.5) return "assentamento"
  const mat = num(l, "matricula_ha") ?? (num(l, "f_matricula") ?? 0) * ha
  if (fr(mat) >= 0.5) return "privada_matricula"
  return "posse_em_titulacao"
}

export interface Terra {
  caminho: Caminho
  nome: string
  situacao: SituacaoTerra
  motivo: string | null
  aviso: string | null
  risco: Risco | null
  riscoMotivo: string | null
  concessaoLink: string | null
  concessaoData: string | null
}

export function lerTerra(l: Linha): Terra {
  const caminho = caminhoDe(l)
  const info = infoCaminho(caminho)
  const risco = texto(l, "risco_terra") as Risco | null
  return {
    caminho,
    nome: info.nome,
    situacao: (texto(l, "caminho_terra_situacao") as SituacaoTerra | null) ?? info.situacao,
    motivo: texto(l, "caminho_terra_motivo"),
    aviso: texto(l, "caminho_terra_aviso") ?? (info.situacao === "pronta_agora" ? null : info.dica),
    risco: risco && risco in NOME_RISCO ? risco : null,
    riscoMotivo: texto(l, "risco_terra_motivo"),
    concessaoLink: texto(l, "terra_concessao_link"),
    concessaoData: texto(l, "terra_concessao_data"),
  }
}

/** Barras do funil: quantas fazendas em cada situação (soma exatamente a lista: ninguém some). */
export function porSituacao(lista: { linha: Linha }[]): Record<SituacaoTerra, number> {
  const out: Record<SituacaoTerra, number> = { pronta_agora: 0, em_espera: 0, so_mostrar: 0 }
  for (const i of lista) out[infoCaminho(caminhoDe(i.linha)).situacao] += 1
  return out
}

export const ORIGINAVEIS: Caminho[] = ["privada_matricula", "publica_concessao", "posse_em_titulacao", "assentamento"]
export const PRONTAS: Caminho[] = ["privada_matricula", "publica_concessao"]
