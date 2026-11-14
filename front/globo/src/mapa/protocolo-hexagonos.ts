import type { Geo } from "../../../compartilhado/dados"
import type { CaixaHexagonos, ConsultaHexagonos, ResumoHexagonos } from "./hexagonos"

export type EntradaHexagonos = Geo | string | null
/** Os polígonos atravessam a thread em bytes imutáveis. Só os metadados compactos viram objetos na interface. */
export type ConsultaHexagonosSerializada = Omit<ConsultaHexagonos, "geo"> & { geojson: Blob }
export type RequisicaoHexagonos = { id: number; geracao: number } & (
  | { acao: "carregar"; entrada: EntradaHexagonos }
  | { acao: "autorizar"; geo: Geo | null }
  | { acao: "consultar"; bbox: CaixaHexagonos; zoom: number; destaques?: readonly string[] }
)
export type RespostaHexagonos = { id: number; geracao: number } & (
  | { tipo: "pronto"; resumo: ResumoHexagonos }
  | { tipo: "autorizado" }
  | { tipo: "hexagonos"; consulta: ConsultaHexagonosSerializada }
  | { tipo: "erro"; mensagem: string; cancelado?: boolean }
)
