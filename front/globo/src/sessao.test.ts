import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { escolherFontePedidos, fontePedidosApi } from "../../compartilhado/pedidos/fonte-pedidos"
import type { FonteDeDados } from "../../compartilhado/dados/fonte"
import { CHAVE_SESSAO } from "../../compartilhado/pedidos/sessao"

const fonte = {} as FonteDeDados
const sessaoReal = { token: "teste-sessao-compartilhada", email: "teste@example.invalid" }

beforeEach(() => {
  vi.resetModules()
  vi.stubEnv("VITE_RAIZ_API", "")
  vi.stubGlobal("location", { search: "" })
  vi.stubGlobal("localStorage", {
    getItem: () => { throw new Error("Armazenamento bloqueado") },
    setItem: () => { throw new Error("Armazenamento bloqueado") },
    removeItem: () => { throw new Error("Armazenamento bloqueado") },
  })
})
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs() })

async function abrirSessao() {
  const modulo = await import("./sessao")
  function LeituraDoCabecalho() { return createElement("span", null, modulo.useSessao()?.token ?? "sem-sessao") }
  return { ...modulo, lerHook: () => renderToStaticMarkup(createElement(LeituraDoCabecalho)) }
}

describe("sessão leve compartilhada com a fonte carregada depois", () => {
  it("login, leitura do cabeçalho e logout usam a mesma memória com storage bloqueado", async () => {
    vi.stubEnv("VITE_RAIZ_API", "https://api.example.invalid/")
    const transporte = vi.fn<typeof fetch>(async () => new Response(JSON.stringify(sessaoReal)))
    vi.stubGlobal("fetch", transporte)
    const s = await abrirSessao()
    expect(s.lerHook()).toContain("sem-sessao")
    const pedidos = escolherFontePedidos(import.meta.env, fonte, s.sessaoPedidos)
    expect(pedidos.publica).not.toBe(true)
    await pedidos.confirmar("link-de-teste")
    expect(s.lerHook()).toContain(sessaoReal.token)
    await pedidos.listar()
    expect(transporte.mock.calls.at(-1)?.[1]).toMatchObject({ headers: { Authorization: `Bearer ${sessaoReal.token}` } })
    pedidos.sair()
    expect(s.lerHook()).toContain("sem-sessao")
    expect(pedidos.sessao()).toBeNull()
  })

  it("uma resposta 401 limpa também a sessão que o cabeçalho lê da memória", async () => {
    vi.stubEnv("VITE_RAIZ_API", "https://api.example.invalid/")
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 401 })))
    const s = await abrirSessao()
    s.sessaoPedidos.armazenamento.gravar(CHAVE_SESSAO, JSON.stringify(sessaoReal))
    const pedidos = escolherFontePedidos(import.meta.env, fonte, s.sessaoPedidos)
    expect(s.lerHook()).toContain(sessaoReal.token)
    await expect(pedidos.listar()).rejects.toThrow("A sessão acabou")
    expect(s.lerHook()).toContain("sem-sessao")
  })

  it("demonstração compartilha sua memória com o hook, sem autenticar ou apagar a sessão real", async () => {
    vi.stubGlobal("location", { search: "?demonstracao=lotes" })
    vi.stubGlobal("fetch", vi.fn(() => { throw new Error("Demonstração não consulta rede") }))
    const s = await abrirSessao()
    s.sessaoPedidos.armazenamento.gravar(CHAVE_SESSAO, JSON.stringify(sessaoReal))
    const pedidos = escolherFontePedidos(import.meta.env, fonte, s.sessaoPedidos)
    const api = fontePedidosApi("https://api.example.invalid/", { armazenamento: s.sessaoPedidos.armazenamento })
    expect(s.pedidosPublicos).toBe(false)
    expect(s.lerHook()).toContain("sem-sessao")
    const demonstracao = await pedidos.confirmar("demonstracao")
    expect(s.lerHook()).toContain(demonstracao.token)
    expect(api.sessao()).toEqual(sessaoReal)
    pedidos.sair()
    expect(s.lerHook()).toContain("sem-sessao")
    expect(api.sessao()).toEqual(sessaoReal)
    expect(fetch).not.toHaveBeenCalled()
  })

  it("público ignora sessão anterior e preserva o modo escolhido antes de carregar a fonte", async () => {
    const s = await abrirSessao()
    s.sessaoPedidos.armazenamento.gravar(CHAVE_SESSAO, JSON.stringify(sessaoReal))
    vi.stubGlobal("location", { search: "?demonstracao=lotes" })
    const pedidos = escolherFontePedidos(import.meta.env, fonte, s.sessaoPedidos)
    expect(s.pedidosPublicos).toBe(true)
    expect(pedidos.publica).toBe(true)
    expect(s.lerHook()).toContain("sem-sessao")
    expect(pedidos.sessao()).toBeNull()
  })

  it("API configurada prevalece sobre demonstração desde o primeiro cabeçalho", async () => {
    vi.stubEnv("VITE_RAIZ_API", "https://api.example.invalid/")
    vi.stubGlobal("location", { search: "?demonstracao=lotes" })
    const s = await abrirSessao()
    s.sessaoPedidos.armazenamento.gravar(CHAVE_SESSAO, JSON.stringify(sessaoReal))
    expect(s.sessaoPedidos.modo).toBe("api")
    expect(s.pedidosPublicos).toBe(false)
    expect(s.lerHook()).toContain(sessaoReal.token)
    expect(escolherFontePedidos(import.meta.env, fonte, s.sessaoPedidos).exemplo).toBe(false)
  })
})
