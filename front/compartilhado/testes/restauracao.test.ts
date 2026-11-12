import fs from "node:fs"
import path from "node:path"
import { describe, expect, it } from "vitest"
import { lerCsv } from "../dados/csv"
import { descricaoCenario, fmtFaixa, fmtReais, lerMarcos, lerRestauracao, ordenarFiltrar } from "../restauracao"

const AMOSTRA = path.resolve(__dirname, "../../../dados/amostra")
const linhas = lerCsv(fs.readFileSync(path.join(AMOSTRA, "desenvolvedor_1504950.csv"), "utf8")).linhas

describe("valor para quem restaura", () => {
  it("lê as colunas de desenvolvedor_<mun>.csv em faixa P10 a P90", () => {
    const rs = linhas.map(lerRestauracao).filter((r) => r !== null)
    expect(rs.length).toBe(linhas.length)
    for (const r of rs) {
      for (const f of [r.custoHa, r.capturaHaAno, r.creditoHaAno, r.vplHa, r.tirAlavancadaPct]) {
        expect(f.p10).toBeLessThanOrEqual(f.p50)
        expect(f.p50).toBeLessThanOrEqual(f.p90)
      }
      expect(r.creditoHaAno.p50).toBeLessThanOrEqual(r.capturaHaAno.p50)
    }
    expect(new Set(rs.map((r) => r.modo)).size).toBeGreaterThan(1)
  })

  it("cenário central da rodada 11: descontos em ordem, marcos, dívida e dono", () => {
    const r = lerRestauracao(linhas[0])
    expect(r).not.toBeNull()
    if (!r) return
    expect(r.cenario).toBe("central_r11")
    expect(r.capturaModelo).toBe("curva")
    expect(r.descontos.linhaBase).toBeGreaterThanOrEqual(10)
    expect([r.descontos.vazamento, r.descontos.reserva, r.descontos.incerteza]).toEqual([10, 12, 10])
    expect(r.marcos.map((m) => m.ano)).toEqual([7, 12, 17, 22, 25])
    expect(r.creditoContratoHa?.p50).toBeGreaterThan(0)
    expect(r.divida?.fracao).toBeLessThanOrEqual(0.5)
    expect(r.dono.forma).toBe("participacao")
    expect(descricaoCenario(r.cenario).taxa).toBe("a 9,2% ao ano")
    expect(descricaoCenario("otimista_fundador").financiamento).toBe("80% pelo Fundo Clima")
    expect(lerMarcos({ marco_12_chance_pct: "80", marco_7_chance_pct: "40", outro: "1" })).toEqual([
      { ano: 7, chancePct: 40 },
      { ano: 12, chancePct: 80 },
    ])
  })

  it("sem o cálculo, não inventa número", () => {
    expect(lerRestauracao({ cod_imovel: "X" })).toBeNull()
  })

  it("ordena pelo valor sem cortar ninguém e filtra pelo caminho", () => {
    const lista = linhas.map((l) => ({ linha: l }))
    const ord = ordenarFiltrar([...lista, { linha: { cod_imovel: "SEM" } }], "valor", null)
    expect(ord.length).toBe(lista.length + 1)
    expect(ord[ord.length - 1].linha.cod_imovel).toBe("SEM")
    const v = ord.slice(0, -1).map((x) => Number(x.linha.valor_desenvolvedor_rs))
    expect(v).toEqual([...v].sort((a, b) => b - a))
    const so = ordenarFiltrar(lista, "area", "plantio_total")
    expect(so.every((x) => x.linha.modo_restauracao === "plantio_total")).toBe(true)
  })

  it("dinheiro com 2 algarismos e faixa em palavras", () => {
    expect(fmtReais(14000)).toBe("R$ 14 mil")
    expect(fmtReais(3456)).toBe("R$ 3,5 mil")
    expect(fmtReais(-5922)).toBe("menos R$ 5,9 mil")
    expect(fmtReais(1_250_000)).toBe("R$ 1,3 milhão")
    expect(fmtFaixa({ p10: 1, p50: 2, p90: 3 }, String)).toBe("cerca de 2 (de 1 a 3)")
    expect(fmtFaixa({ p10: 5.5, p50: 7.2, p90: 10.1 }, String, "t por ha por ano")).toBe(
      "cerca de 7.2 t por ha por ano (de 5.5 a 10.1)",
    )
  })
})
