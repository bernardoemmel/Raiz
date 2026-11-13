import { describe, expect, it } from "vitest"
import { fichaCreditoIndisponivel, lerFichaCredito } from "../../compartilhado/ficha-credito"
import { fichaCreditoDemonstracao } from "../../compartilhado/pedidos/ficha-credito-demonstracao"

const esperado = { opcao_id: "barata" as const, revisao_lote: null, exemplo: true }
const exemplo = () => fichaCreditoDemonstracao({ id: "barata", creditos: { p10: 100, p50: 200, p90: 300 }, hectares: 100 })

describe("ficha de crédito com base comum", () => {
  it("preserva total, divide pela área elegível documentada e mantém revisão ausente", () => {
    const r = lerFichaCredito(exemplo(), esperado)
    expect(r.estado).toBe("disponivel")
    expect(r.creditos_por_ha).toEqual({ p10: 1.25, p50: 2.5, p90: 3.75 })
    expect(r.area_elegivel_ha).toBe(80)
    expect(r.area_total_ha).toBe(100)
    expect(r.secoes.garantias.revisado_em).toBeNull()
    expect(r.resultados?.origem).toBe("demonstracao")
  })

  it("não promove legado ou ausência a números", () => {
    for (const v of [undefined, null, {}, { creditos: { p50: 200 }, hectares: 100 }, fichaCreditoIndisponivel("barata")]) {
      const r = lerFichaCredito(v, esperado)
      expect(r.estado).toBe("indisponivel")
      expect(r.creditos_lote).toBeNull()
      expect(r.creditos_por_ha).toBeNull()
      expect(r.exclusoes).toBeNull()
    }
  })

  it("retém o total quando a área elegível continua desconhecida", () => {
    const d = exemplo()
    d.area_elegivel_ha = null
    d.creditos_por_ha = null
    const r = lerFichaCredito(d, esperado)
    expect(r.estado).toBe("disponivel")
    expect(r.creditos_lote?.p50).toBe(200)
    expect(r.creditos_por_ha).toBeNull()
  })

  it.each([
    (d: ReturnType<typeof exemplo>) => { d.revisao_lote = "b".repeat(64) },
    (d: ReturnType<typeof exemplo>) => { d.opcao_id = "segura" },
    (d: ReturnType<typeof exemplo>) => { d.exemplo = false },
    (d: ReturnType<typeof exemplo>) => { d.base!.fim = "2024-01-01" },
    (d: ReturnType<typeof exemplo>) => { d.base!.horizonte_anos = 0 },
    (d: ReturnType<typeof exemplo>) => { d.base!.inicio = null },
    (d: ReturnType<typeof exemplo>) => { d.base!.escopo_carteira = undefined as never },
    (d: ReturnType<typeof exemplo>) => { d.base!.classe_ativo = "flag"; d.base!.classe_evidencia = "emitido" },
    (d: ReturnType<typeof exemplo>) => { d.creditos_por_ha!.p50 = 2 },
    (d: ReturnType<typeof exemplo>) => { d.area_elegivel_ha = 0 },
    (d: ReturnType<typeof exemplo>) => { d.area_elegivel_ha = 1e-320 },
    (d: ReturnType<typeof exemplo>) => { d.area_elegivel_ha = 101 },
    (d: ReturnType<typeof exemplo>) => { d.area_elegivel_ha = Number.NaN },
    (d: ReturnType<typeof exemplo>) => { d.evidencia_area_id = null },
    (d: ReturnType<typeof exemplo>) => { d.secoes.titulo.revisado_em = "2099-01-01" },
    (d: ReturnType<typeof exemplo>) => { d.secoes.titulo.revisado_em = "2026-11-01" },
    (d: ReturnType<typeof exemplo>) => { d.base!.fonte = "Pessoa Fictícia do Teste" },
    (d: ReturnType<typeof exemplo>) => { d.secoes.titulo.texto = "Pessoa Fictícia do Teste" },
    (d: ReturnType<typeof exemplo>) => { d.resultados!.origem = "real" },
  ])("recusa base, evidência, revisão ou demonstração incompatível", mudar => {
    const d = exemplo()
    mudar(d)
    expect(lerFichaCredito(d, esperado).estado).toBe("indisponivel")
  })

  it("nunca usa a demonstração como ficha de pedido real", () => {
    expect(lerFichaCredito(exemplo(), { ...esperado, exemplo: false, revisao_lote: "a".repeat(64) }).estado).toBe("indisponivel")
  })

  it("projeta somente chaves públicas do contrato privado, sem ecoar campos extras", () => {
    const r = lerFichaCredito({ ...exemplo(), dono: "Pessoa Fictícia do Teste", codigo_car: "DEMONSTRACAO-1" }, esperado)
    expect(r.estado).toBe("disponivel")
    expect(JSON.stringify(r)).not.toContain("Pessoa Fictícia")
    expect(JSON.stringify(r)).not.toContain("DEMONSTRACAO-1")
  })
})
