import { useEffect, useState } from "react"
import { fonteAmostra } from "../../compartilhado/dados/fonte-amostra"

/**
 * O mapa aberto lê somente o agregado publicado. VITE_RAIZ_API conecta a prospecção e os pedidos com a sessão do
 * cliente; nunca entrega o token operacional nem abre as rotas internas de dados no navegador.
 */
export const fonte = fonteAmostra(import.meta.env.VITE_RAIZ_DADOS_BASE || import.meta.env.BASE_URL || "/")

export interface Carga<T> {
  dado: T | undefined
  erro: Error | null
  carregando: boolean
}

/** Carrega um dado assíncrono e recarrega quando as dependências mudam (descarta resposta velha). */
export function useCarga<T>(fn: () => Promise<T>, deps: unknown[]): Carga<T> {
  const [estado, setEstado] = useState<Carga<T>>({ dado: undefined, erro: null, carregando: true })
  useEffect(() => {
    let vivo = true
    setEstado((e) => e.carregando && e.erro === null ? e : { dado: e.dado, erro: null, carregando: true })
    fn().then(
      (dado) => vivo && setEstado({ dado, erro: null, carregando: false }),
      (erro: Error) => vivo && setEstado({ dado: undefined, erro, carregando: false }),
    )
    return () => {
      vivo = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return estado
}
