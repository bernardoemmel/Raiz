import type { Geo } from "../../../compartilhado/dados"
import type { CaixaHexagonos, ConsultaHexagonos, ResumoHexagonos } from "./hexagonos"

export type EntradaHexagonos = Geo | string | null
export type RequisicaoHexagonos = { id: number; geracao: number } & (
  | { acao: "carregar"; entrada: EntradaHexagonos }
  | { acao: "autorizar"; geo: Geo | null }
  | { acao: "consultar"; bbox: CaixaHexagonos; zoom: number; destaques?: readonly string[] }
)
export type RespostaHexagonos = { id: number; geracao: number } & (
  | { tipo: "pronto"; resumo: ResumoHexagonos }
  | { tipo: "autorizado" }
  | { tipo: "hexagonos"; consulta: ConsultaHexagonos }
  | { tipo: "erro"; mensagem: string; cancelado?: boolean }
)
