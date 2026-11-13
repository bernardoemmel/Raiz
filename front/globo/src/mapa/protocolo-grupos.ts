import type { Geo } from "../../../compartilhado/dados"
import type { GrupoMapa } from "./grupos"

export type CaixaGrupos = [oeste: number, sul: number, leste: number, norte: number]
export type EntradaGrupos = { url: string } | { geo: Geo | null }

export type RequisicaoGrupos = { id: number; geracao: number } & (
  | { acao: "carregar"; entrada: EntradaGrupos }
  | { acao: "consultar"; bbox: CaixaGrupos; zoom: number }
  | { acao: "aproximar"; cluster: number }
)

/** O protocolo de volta não admite GeoJSON, propriedades originais nem folhas de um cluster. */
export type RespostaGrupos = { id: number; geracao: number } & (
  | { tipo: "pronto" }
  | { tipo: "grupos"; grupos: GrupoMapa[] }
  | { tipo: "zoom"; zoom: number }
  | { tipo: "erro"; mensagem: string; cancelado?: boolean }
)
