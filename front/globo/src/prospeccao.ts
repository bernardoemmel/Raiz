import { fonteProspeccao } from "../../compartilhado/prospeccao"
import { pedidos } from "./pedidos"

/** Nenhum exemplo local concede acesso à ficha ou simula um pagamento. */
export const prospeccao = fonteProspeccao(import.meta.env.VITE_RAIZ_API, () => pedidos.exemplo ? null : pedidos.sessao()?.token ?? null)

export const numeroTerra = (n: number | null | undefined) => n == null ? "Não informado" : n.toLocaleString("pt-BR", { maximumFractionDigits: 2 })
export const dataTerra = (data: string | null | undefined) => {
  if (!data) return "Data não informada"
  if (/^\d{4}$/.test(data)) return data
  const d = new Date(`${data.slice(0, 10)}T12:00:00`)
  return Number.isNaN(d.getTime()) ? "Data não informada" : d.toLocaleDateString("pt-BR")
}
