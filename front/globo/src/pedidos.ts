import { useEffect, useState } from "react"
import { escolherFontePedidos } from "../../compartilhado/pedidos/fonte-pedidos"
import type { Sessao } from "../../compartilhado/pedidos/tipos"
import { fonte } from "./dados"

/** Os pedidos de lote: a API se VITE_RAIZ_API estiver no .env; sem ela, a cobertura regional e os critérios salvos no navegador. */
export const pedidos = escolherFontePedidos(import.meta.env, fonte)

const EVENTO = "raiz-sessao"
/** avisa as telas que a pessoa entrou ou saiu */
export const avisarSessao = () => window.dispatchEvent(new Event(EVENTO))

/** a sessão de quem está usando, atualizada quando entra ou sai (inclusive em outra aba) */
export function useSessao(): Sessao | null {
  const [sessao, setSessao] = useState(() => pedidos.sessao())
  useEffect(() => {
    const ler = () => setSessao(pedidos.sessao())
    window.addEventListener(EVENTO, ler)
    window.addEventListener("storage", ler)
    return () => {
      window.removeEventListener(EVENTO, ler)
      window.removeEventListener("storage", ler)
    }
  }, [])
  return sessao
}
