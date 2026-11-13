import { useEffect, useState } from "react"
import { prepararSessaoPedidos } from "../../compartilhado/pedidos/sessao"
import type { Sessao } from "../../compartilhado/pedidos/tipos"

export const sessaoPedidos = prepararSessaoPedidos(import.meta.env)
export const pedidosPublicos = sessaoPedidos.modo === "publica"

const EVENTO = "raiz-sessao"
/** avisa as telas que a pessoa entrou ou saiu */
export const avisarSessao = () => window.dispatchEvent(new Event(EVENTO))

/** a sessão de quem está usando, atualizada quando entra ou sai (inclusive em outra aba) */
export function useSessao(): Sessao | null {
  const [sessao, setSessao] = useState(() => sessaoPedidos.ler())
  useEffect(() => {
    const ler = () => setSessao(sessaoPedidos.ler())
    window.addEventListener(EVENTO, ler)
    window.addEventListener("storage", ler)
    return () => {
      window.removeEventListener(EVENTO, ler)
      window.removeEventListener("storage", ler)
    }
  }, [])
  return sessao
}
