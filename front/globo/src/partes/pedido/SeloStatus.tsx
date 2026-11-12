import { rotuloStatus } from "../../../../compartilhado/pedidos/texto"
import type { StatusPedido } from "../../../../compartilhado/pedidos/tipos"

const CLASSE: Record<StatusPedido, string> = {
  lote_montado: "neutro",
  buscando_interesse: "conferir",
  grupo_pronto: "ok",
  faltou: "ruim",
  reservado: "ok",
  contrato: "ok",
  reserva_vencida: "neutro",
}

/** O status do pedido, sempre escrito (nunca só a cor). */
export function SeloStatus({ status, reservadoAte }: { status: StatusPedido; reservadoAte: string | null }) {
  return <span className={`selo ${CLASSE[status]}`}>{rotuloStatus(status, reservadoAte)}</span>
}
