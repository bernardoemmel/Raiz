import { beforeEach, describe, expect, it, vi } from "vitest"
import { fontePedidosApi, escolherFontePedidos } from "../pedidos/fonte-pedidos"
import { fontePedidosSimulada, pedidoDemonstracao } from "../pedidos/simulado"
import { CAMPOS_PADRAO } from "../pedidos/exemplo"
import type { FonteDeDados } from "../dados/fonte"

beforeEach(() => {
  const memoria = new Map<string, string>()
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => memoria.get(k) ?? null,
    setItem: (k: string, v: string) => memoria.set(k, v),
    removeItem: (k: string) => memoria.delete(k),
  })
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("A demonstração não pode consultar a rede.") }))
  vi.stubGlobal("location", { search: "" })
})

describe("demonstração explicitamente fictícia da área logada", () => {
  it("exige entrada, usa o DTO da API e não abre contato, cobrança ou fonte de dados", async () => {
    const f = fontePedidosSimulada()
    expect(f.exemplo).toBe(true)
    expect(f.sessao()).toBeNull()
    await expect(f.pedido("demonstracao")).rejects.toThrow("sessão acabou")
    await f.confirmar("demonstracao")
    const p = await f.criar(structuredClone(CAMPOS_PADRAO))
    expect(p.exemplo).toBe(true)
    expect(p.opcoes).toHaveLength(3)
    for (const o of p.opcoes) {
      expect(o.itens.every((i) => i.cod_imovel.startsWith("DEMONSTRACAO-") && i.geometria)).toBe(true)
      expect(o.destrava?.length).toBeGreaterThan(0)
      expect(o.ficha_credito?.exemplo).toBe(true)
    }
    expect(await f.pedido(p.id)).toEqual(p)
    await expect(f.solicitarInteresse(p.id, "barata")).rejects.toThrow("409")
    await expect(f.reservar(p.id)).rejects.toThrow("409")
    expect(fetch).not.toHaveBeenCalled()
  })

  it("a sessão simulada não autentica na API real e sair revoga a leitura", async () => {
    localStorage.setItem("raiz.sessao", JSON.stringify({ token: "token-real-preservado", email: "real@example.test" }))
    const f = fontePedidosSimulada()
    await f.confirmar("demonstracao")
    expect(fontePedidosApi("https://api.example.test").sessao()?.token).toBe("token-real-preservado")
    expect(f.sessao()?.token).not.toBe("token-real-preservado")
    f.sair()
    expect(f.sessao()).toBeNull()
    expect(fontePedidosApi("https://api.example.test").sessao()?.token).toBe("token-real-preservado")
    await expect(f.pedido("demonstracao")).rejects.toThrow("sessão acabou")
  })

  it("é opt-in e uma API configurada sempre prevalece", () => {
    const fonte = {} as FonteDeDados
    expect(escolherFontePedidos({}, fonte).publica).toBe(true)
    vi.stubGlobal("location", { search: "?demonstracao=lotes" })
    expect(escolherFontePedidos({}, fonte).exemplo).toBe(true)
    expect(escolherFontePedidos({ VITE_RAIZ_API: "https://api.example.test" }, fonte).exemplo).toBe(false)
  })

  it("não distribui identidades reais e mantém as medidas reconciliadas na retirada", async () => {
    const f = fontePedidosSimulada()
    await f.confirmar("demonstracao")
    const inicial = pedidoDemonstracao()
    const opcao = inicial.opcoes[0], item = opcao.itens[1]
    const p = await f.mudarLote(inicial.id, { opcao: "barata", acao: "tirar", cod_imovel: item.cod_imovel })
    expect(p.opcoes[0].fazendas).toBe(1)
    expect(p.opcoes[0].hectares).toBe(opcao.hectares - item.hectares!)
    expect(p.opcoes[0].creditos.p50).toBe(opcao.creditos.p50 - item.creditos!.p50)
    expect(p.opcoes[0].ficha_credito).toBeUndefined()
    const texto = JSON.stringify(p)
    expect(texto).not.toMatch(/[A-Z]{2}-\d{7}-[A-F0-9]{32}/)
    expect(texto).not.toMatch(/"(?:cpf|cnpj|nome_proprietario|telefone)"/)
  })
})
