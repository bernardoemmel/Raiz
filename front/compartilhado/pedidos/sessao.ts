/** Sessão e modo de acesso sem importar o motor de pedidos nem a demonstração. */
import type { Sessao } from "./tipos"

/** localStorage pode não existir (aba anônima, bloqueio): cai na memória e a tela continua funcionando */
export function guarda() {
  const memoria = new Map<string, string>()
  return {
    ler(chave: string): string | null {
      try {
        return localStorage.getItem(chave)
      } catch {
        return memoria.get(chave) ?? null
      }
    },
    gravar(chave: string, valor: string | null) {
      try {
        if (valor === null) localStorage.removeItem(chave)
        else localStorage.setItem(chave, valor)
      } catch {
        if (valor === null) memoria.delete(chave)
        else memoria.set(chave, valor)
      }
    },
  }
}

export const CHAVE_SESSAO = "raiz.sessao"

export function sessaoGuardada(g: ReturnType<typeof guarda>, chave = CHAVE_SESSAO): Sessao | null {
  try {
    const s = JSON.parse(g.ler(chave) ?? "null") as Sessao | null
    return s?.token && s.email ? s : null
  } catch {
    return null
  }
}

export const CHAVE_DEMONSTRACAO = "raiz.demonstracao.sessao"
export type AmbientePedidos = { VITE_RAIZ_API?: string; VITE_RAIZ_DADOS_BASE?: string; BASE_URL?: string }
export type ModoPedidos = "api" | "demonstracao" | "publica"

export function escolherModoPedidos(env: AmbientePedidos): ModoPedidos {
  if (env.VITE_RAIZ_API) return "api"
  if (typeof location !== "undefined" && new URLSearchParams(location.search).get("demonstracao") === "lotes") return "demonstracao"
  return "publica"
}

/** A mesma guarda atende o cabeçalho e a fonte, inclusive quando localStorage está bloqueado. */
export function prepararSessaoPedidos(env: AmbientePedidos) {
  const modo = escolherModoPedidos(env)
  const armazenamento = guarda()
  const chave = modo === "demonstracao" ? CHAVE_DEMONSTRACAO : CHAVE_SESSAO
  return { modo, api: env.VITE_RAIZ_API, armazenamento,
    ler: (): Sessao | null => modo === "publica" ? null : sessaoGuardada(armazenamento, chave) }
}
