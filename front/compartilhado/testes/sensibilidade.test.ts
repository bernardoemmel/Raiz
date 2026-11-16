import { afterEach, describe, expect, it, vi } from "vitest"
import { simularSensibilidade } from "../pedidos/sensibilidade-demonstracao"
import { PARAMETROS_SENSIBILIDADE as p, conferirResultadoSensibilidade, consultarSensibilidadeApi } from "../pedidos/sensibilidade"

afterEach(() => vi.unstubAllGlobals())

describe("sensibilidade: premissas, procedência e resposta completa", () => {
  it("preserva os três exemplos iniciais e a TIR central da demonstração", () => {
    const base = simularSensibilidade(p)
    for (let i = 0; i < 3; i++) {
      expect(base.opcoes[i].creditos).toEqual({ p10: 900_000 + i * 60_000, p50: 1_100_000 + i * 30_000, p90: 1_300_000 + i * 20_000 })
      expect(base.opcoes[i].hectares).toBe(5_000 + i * 100)
      expect(base.opcoes[i].fazendas).toBe(2)
      expect(base.opcoes[i].tir_projeto).toBeCloseTo(0.12 + i / 100, 8)
    }
  })
  it("preço só altera o fluxo financeiro; desconto altera VPL, nunca a TIR do mesmo fluxo", () => {
    const base = simularSensibilidade(p)
    const caro = simularSensibilidade({ ...p, preco_credito_usd: 70 })
    const desconto = simularSensibilidade({ ...p, taxa_desconto: 0.15 })
    for (let i = 0; i < 3; i++) {
      expect(caro.opcoes[i].creditos).toEqual(base.opcoes[i].creditos)
      expect(caro.opcoes[i].tir_projeto!).toBeGreaterThan(base.opcoes[i].tir_projeto!)
      expect(desconto.opcoes[i].vpl_usd!).toBeLessThan(base.opcoes[i].vpl_usd!)
      expect(desconto.opcoes[i].tir_projeto).toBe(base.opcoes[i].tir_projeto)
    }
  })
  it("reserva reduz créditos vendáveis; pessimista reduz retorno e nunca muda composição", () => {
    const base = simularSensibilidade(p)
    const reserva = simularSensibilidade({ ...p, reserva_reversao: 0.4 })
    const pessimista = simularSensibilidade({ ...p, pessimista: true })
    for (let i = 0; i < 3; i++) {
      expect(reserva.opcoes[i].creditos.p50).toBeCloseTo(base.opcoes[i].creditos.p50 * 0.75)
      expect(pessimista.opcoes[i].vpl_usd!).toBeLessThan(base.opcoes[i].vpl_usd!)
      expect(pessimista.opcoes[i].hectares).toBe(base.opcoes[i].hectares)
      expect(pessimista.opcoes[i].fazendas).toBe(base.opcoes[i].fazendas)
    }
    expect(base.exemplo).toBe(true)
    expect(base.modelo_versao).toMatch(/^demonstracao-/)
    expect(base.fonte).toContain("fictícia")
  })
  it("reserva nunca cai abaixo20%, valores não finitos são inválidos e TIR inexistente fica nula", () => {
    expect(() => simularSensibilidade({ ...p, reserva_reversao: 0.19 })).toThrow("20%")
    expect(() => simularSensibilidade({ ...p, preco_credito_usd: NaN })).toThrow()
    expect(() => simularSensibilidade({ ...p, taxa_desconto: Infinity })).toThrow()
    expect(simularSensibilidade({ ...p, preco_credito_usd: 0.01 }).opcoes.every((o) => o.tir_projeto === null)).toBe(true)
  })
  it("sem API não tenta rota no Pages nem atribui o exemplo ao Release", async () => {
    const fetch = vi.fn()
    vi.stubGlobal("fetch", fetch)
    const r = await consultarSensibilidadeApi(undefined, "id", () => null)(p)
    expect(fetch).not.toHaveBeenCalled()
    expect(r.estado).toBe("indisponivel")
    expect(r.opcoes).toEqual([])
    expect(r.exemplo).toBe(false)
    expect(r.atualizado_em).toBeNull()
  })
  it("API recebe credencial por cabeçalho e corpo exato; sem sessão não faz chamada", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...simularSensibilidade(p), revisao_lote: "a".repeat(64) })))
    vi.stubGlobal("fetch", fetch)
    await expect(consultarSensibilidadeApi("https://api.example/v1", "id", () => null)(p)).rejects.toThrow("Entre")
    expect(fetch).not.toHaveBeenCalled()
    await consultarSensibilidadeApi("https://api.example/v1/", "id com espaço", () => "sessao-ficticia", "a".repeat(64))(p)
    expect(fetch).toHaveBeenCalledWith("https://api.example/v1/pedidos/id%20com%20espa%C3%A7o/sensibilidade", expect.objectContaining({
      method: "POST", cache: "no-store", headers: expect.objectContaining({ Authorization: "Bearer sessao-ficticia", "If-Match": `"${"a".repeat(64)}"` }), body: JSON.stringify(p),
    }))
  })
  it("não confunde respostas de outras premissas, parciais, duplicadas ou sem data", () => {
    const base = simularSensibilidade(p)
    expect(() => conferirResultadoSensibilidade(base, { ...p, pessimista: true })).toThrow()
    expect(() => conferirResultadoSensibilidade({ ...base, opcoes: base.opcoes.slice(1) }, p)).toThrow()
    expect(() => conferirResultadoSensibilidade({ ...base, opcoes: [base.opcoes[0], base.opcoes[0], base.opcoes[2]] }, p)).toThrow()
    expect(() => conferirResultadoSensibilidade({ ...base, atualizado_em: null }, p)).toThrow()
    expect(() => conferirResultadoSensibilidade({ ...base, estado: "indisponivel" }, p)).toThrow()
    expect(() => conferirResultadoSensibilidade({ ...base, opcoes: base.opcoes.map((o) => ({ ...o, creditos: { p10: 20, p50: 10, p90: 30 } })) }, p)).toThrow()
  })
  it("ignora detalhes por fazenda e mantém nulo diferente de zero", () => {
    const base = simularSensibilidade(p)
    const r = conferirResultadoSensibilidade({ ...base, cod_imovel: "DEMONSTRACAO-1", opcoes: base.opcoes.map((o) => ({
      ...o, cod_imovel: "DEMONSTRACAO-1", geometria: {}, tir_projeto: null, vpl_usd: 0,
    })) }, p)
    expect(JSON.stringify(r)).not.toContain("cod_imovel")
    expect(JSON.stringify(r)).not.toContain("geometria")
    expect(r.opcoes[0].tir_projeto).toBeNull()
    expect(r.opcoes[0].vpl_usd).toBe(0)
  })
})


describe("revisão da sensibilidade", () => {
  it("recusa resposta em voo de outra composição mesmo com premissas iguais", () => {
    const r = { ...simularSensibilidade(p), exemplo: false, revisao_lote: "a".repeat(64) }
    expect(() => conferirResultadoSensibilidade(r, p, "b".repeat(64))).toThrow(/revisão/)
    expect(conferirResultadoSensibilidade(r, p, "a".repeat(64)).revisao_lote).toBe("a".repeat(64))
  })
  it("recusa pedido sem revisão antes de buscar a API e apresenta rejeição otimista", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response("", { status: 412 }))
    vi.stubGlobal("fetch", fetch)
    await expect(consultarSensibilidadeApi("https://api.example", "id", () => "sessao")(p)).rejects.toThrow(/revisão/)
    expect(fetch).not.toHaveBeenCalled()
    await expect(consultarSensibilidadeApi("https://api.example", "id", () => "sessao", "a".repeat(64))(p)).rejects.toThrow(/lote mudou/)
  })
})
