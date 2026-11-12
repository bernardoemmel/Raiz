import { useEffect, useState } from "react"
import { escolherFonte } from "../../compartilhado/dados"

/** A fonte de dados do painel: a amostra do motor, ou a API se VITE_RAIZ_API estiver definida no .env. */
export const fonte = escolherFonte(import.meta.env)

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
    setEstado((e) => ({ dado: e.dado, erro: null, carregando: true }))
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
