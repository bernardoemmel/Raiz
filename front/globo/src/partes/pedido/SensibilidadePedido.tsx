import { useMemo } from "react"
import { consultarSensibilidadeApi } from "../../../../compartilhado/pedidos/sensibilidade"
import { simularSensibilidade } from "../../../../compartilhado/pedidos/sensibilidade-demonstracao"
import type { Pedido } from "../../../../compartilhado/pedidos/tipos"
import { pedidos } from "../../pedidos"
import { SensibilidadeLote } from "./SensibilidadeLote"

export function SensibilidadePedido({ pedido }: { pedido: Pedido }) {
  const consultar = useMemo(() => pedido.exemplo
    ? async (p: Parameters<typeof simularSensibilidade>[0]) => simularSensibilidade(p)
    : consultarSensibilidadeApi(import.meta.env.VITE_RAIZ_API, pedido.id, () => pedidos.sessao()?.token ?? null, pedido.revisao_lote ?? null),
  [pedido.id, pedido.exemplo, pedido.revisao_lote])
  if (pedido.publicacao) return null
  // A revisão do servidor cobre critérios/composição. O retrato local também invalida exemplos/servidores antigos.
  const retrato = pedido.revisao_lote ?? JSON.stringify([pedido.campos, pedido.versao_modelo, pedido.opcoes])
  return <SensibilidadeLote key={`${pedido.id}:${pedido.revisao_lote ?? "sem-revisao"}:${retrato}`} consultar={consultar} demonstracao={!!pedido.exemplo} />
}
