import { escolherFontePedidos } from "../../compartilhado/pedidos/fonte-pedidos"
import { fonte } from "./dados"
import { sessaoPedidos } from "./sessao"

/** A fonte pesada só entra nas telas de pedidos; sessão e cabeçalho permanecem leves. */
export const pedidos = escolherFontePedidos(import.meta.env, fonte, sessaoPedidos)
export { avisarSessao, useSessao } from "./sessao"
