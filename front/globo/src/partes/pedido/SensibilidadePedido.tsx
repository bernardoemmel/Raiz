import { useMemo } from "react"
import { consultarSensibilidadeApi } from "../../../../compartilhado/pedidos/sensibilidade"
import { simularSensibilidade } from "../../../../compartilhado/pedidos/sensibilidade-demonstracao"
import type { Pedido } from "../../../../compartilhado/pedidos/tipos"
import { pedidos } from "../../pedidos"
import { SensibilidadeLote } from "./SensibilidadeLote"

export function SensibilidadePedido({ pedido }: { pedido: Pedido }) {
  const consultar = useMemo(() => pedido.exemplo
    ? async (p: Parameters<typeof simularSensibilidade>[0]) => simularSensibilidade(p)
    : consultarSensibilidadeApi(import.meta.env.VITE_RAIZ_API, pedido.id, () => pedidos.sessao()?.token ?? null),
  [pedido.id, pedido.exemplo])
  if (pedido.publicacao) return null
  return <SensibilidadeLote key={pedido.id} consultar={consultar} demonstracao={!!pedido.exemplo} />
}
