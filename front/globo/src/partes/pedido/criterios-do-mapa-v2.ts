import type { CamposPedido } from "../../../../compartilhado/pedidos/tipos"

/** Somente critérios de formulário. Nunca composição, CAR, contato, token ou cálculo de lote. */
export interface CriteriosDoMapaV2 {
  meta: CamposPedido["meta"] | null
  ufs: string[]
  precoVenda: number | null
  poligono: [number, number][] | null
  /** Preserva os critérios de um pedido real já autenticado ao editá-lo. */
  campos?: CamposPedido
  origem: "publicacao" | "api"
}

let proximoId = 0
let pendente: (CriteriosDoMapaV2 & { transferencia: number }) | null = null

/** Transferência efêmera entre o mapa e o formulário, sem gravar dados em localStorage. */
export function levarCriteriosDoMapaV2(criterios: CriteriosDoMapaV2) {
  pendente = { ...structuredClone(criterios), transferencia: ++proximoId }
}

/** Leitura sem efeito colateral para continuar correta no StrictMode do React. */
export function lerCriteriosDoMapaV2(): typeof pendente {
  return pendente ? structuredClone(pendente) : null
}

export function confirmarCriteriosDoMapaV2(transferencia: number) {
  if (pendente?.transferencia === transferencia) pendente = null
}

export function aplicarCriteriosDoMapaV2(padrao: CamposPedido, criterios: CriteriosDoMapaV2 | null): CamposPedido {
  const campos = structuredClone(criterios?.campos ?? padrao)
  if (!criterios) return campos
  if (criterios.meta && Number.isFinite(criterios.meta.valor) && criterios.meta.valor > 0) campos.meta = structuredClone(criterios.meta)
  if (!criterios.campos) {
    campos.onde = { ...campos.onde, ufs: [...criterios.ufs], biomas: [], municipios: [], raio: null, so_fornecedores_cadeia: false }
    if (criterios.precoVenda !== null && Number.isFinite(criterios.precoVenda) && criterios.precoVenda >= 0) campos.dinheiro.preco_venda_usd = criterios.precoVenda
  }
  campos.onde.poligono = criterios.poligono ? structuredClone(criterios.poligono) : campos.onde.poligono ?? null
  return campos
}
