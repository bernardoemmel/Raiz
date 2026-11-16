import { describe, expect, it } from "vitest"
// @ts-expect-error: script de CI em JavaScript puro, sem tipos
import { conferirLighthouseCelular, conferirSerieLighthouseCelular } from "../../scripts/conferir-acessibilidade.mjs"
const relatorio = () => ({ categories: { performance: { score: 0.9 }, accessibility: { score: 1 } }, configSettings: { formFactor: "mobile", screenEmulation: { width: 360 }, throttlingMethod: "simulate" } })
describe("portão Lighthouse do celular", () => {
  it("aceita 90 em desempenho e 100 em acessibilidade", () => {
    expect(conferirLighthouseCelular(relatorio())).toEqual({ performance: 90, accessibility: 100 })
  })
  it.each(["performance", "accessibility"] as const)("recusa %s abaixo de 90, ausente ou inválida", (categoria) => {
    for (const score of [0.89, null, undefined, NaN]) {
      const r = relatorio()
      Object.assign(r.categories[categoria], { score })
      expect(() => conferirLighthouseCelular(r)).toThrow(/pelo menos 90|inválida/)
    }
  })
  it("recusa erro de coleta", () => expect(() => conferirLighthouseCelular({ ...relatorio(), runtimeError: { message: "Falhou" } })).toThrow(/não concluiu/))
  it("não deixa trocar celular por desktop nem desligar a rede/CPU simulada", () => {
    for (const mudanca of [{ formFactor: "desktop" }, { screenEmulation: { width: 1440 } }, { throttlingMethod: "provided" }]) {
      const r = relatorio()
      Object.assign(r.configSettings, mudanca)
      expect(() => conferirLighthouseCelular(r)).toThrow()
    }
  })
})

describe("três medições fixas de Lighthouse", () => {
  const amostra = (performance: number, accessibility = 1) => ({ ...relatorio(), categories: { performance: { score: performance }, accessibility: { score: accessibility } } })
  it("usa a mediana, não a maior nota", () => {
    expect(conferirSerieLighthouseCelular([amostra(.96), amostra(.7), amostra(.95)]).performance).toBe(95)
    expect(() => conferirSerieLighthouseCelular([amostra(1), amostra(.89), amostra(.7)])).toThrow(/mediana/)
  })
  it("reprova uma única auditoria de acessibilidade abaixo de 90", () => {
    expect(() => conferirSerieLighthouseCelular([amostra(1), amostra(1, .89), amostra(1)])).toThrow(/todas/)
  })
  it("exige três coletas, sem descartar erro de execução", () => {
    expect(() => conferirSerieLighthouseCelular([amostra(1)])).toThrow(/três/)
    expect(() => conferirSerieLighthouseCelular([amostra(1), { ...amostra(1), runtimeError: { message: "Erro" } }, amostra(1)])).toThrow(/não concluiu/)
  })
})
