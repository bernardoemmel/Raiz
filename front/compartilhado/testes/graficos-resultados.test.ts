import fs from "node:fs"
import { describe, expect, it } from "vitest"
import { resultadosDemonstracao } from "../pedidos/graficos-demonstracao"
import { FONTES_POR_NATUREZA, lerResultadosGraficos } from "../graficos-resultados"
import { especificacaoFaixas, opcaoContratos } from "../../globo/src/partes/graficos/modelos"

const exemplo = () => JSON.parse(fs.readFileSync(new URL("../../../testes/fixtures/resultados_graficos_sinteticos.json", import.meta.url), "utf8"))
describe("evidências dos gráficos privados", () => {
  it("preserva ausência e zero, descarta campos fora da projeção e mantém a marca sintética", () => {
    const origem = exemplo(); origem.nome_dono = "campo proibido e sintético"
    const dado = lerResultadosGraficos(origem)
    expect(dado).toEqual(exemplo())
    expect(dado.contratos[0].marcos[0].emitido).toBeNull()
    expect(dado.contratos[0].marcos[1].emitido?.valor).toBe(0)
    const opcoes = opcaoContratos(dado.contratos[0])
    expect(opcoes.series[1].data).toEqual([null, 0, 80])
    expect(opcoes.series[1].connectNulls).toBe(false)
  })
  it.each(["classe", "area_base_ha", "area_elegivel_carteira_ha", "escopo_carteira", "metrica", "unidade", "fim"])("rejeita referência divergente em %s", (campo) => {
    const r = exemplo(); r.comparacoes[0].observado.referencia[campo] = campo === "area_base_ha" ? 21 : "incompativel"
    expect(() => lerResultadosGraficos(r)).toThrow(/compatíveis/)
  })
  it.each(["fonte", "cronologia", "futuro", "nao_finito", "quantis", "estimativa", "duplicado"])("rejeita %s sem desenhar", (alvo) => {
    const r = exemplo(), c = r.comparacoes[0]
    if (alvo === "fonte") delete c.observado.fonte.registro_id
    if (alvo === "cronologia") c.previsao.congelada_em = "2026-01-01T00:00:00Z"
    if (alvo === "futuro") c.observado.registrado_em = "2027-01-01T00:00:00Z"
    if (alvo === "nao_finito") c.observado.valor = Infinity
    if (alvo === "quantis") c.previsao.p10 = 200
    if (alvo === "estimativa") r.contratos[0].marcos[0].contratado.natureza = "estimativa"
    if (alvo === "duplicado") r.comparacoes.push(c)
    expect(() => lerResultadosGraficos(r)).toThrow()
  })
  it("o spec usa valores locais exatos, sem URL, expressão recebida ou transformar observado em previsão", () => {
    const dado = lerResultadosGraficos(exemplo())
    const spec = especificacaoFaixas(dado.comparacoes, 320)
    expect(spec.data).toEqual({ values: dado.comparacoes.map((c, i) => ({ id: c.id, rotulo: expect.stringContaining(`${i + 1}`), p10: c.previsao.p10, p50: c.previsao.p50, p90: c.previsao.p90, real: c.observado.valor })) })
    expect(spec.data).not.toHaveProperty("url")
    expect(spec).not.toHaveProperty("transform")
  })
  it.each(["fonte_livre", "origem", "booleano"])("recusa %s e não mistura evidência real com demonstração", (alvo) => {
    const r = exemplo()
    if (alvo === "fonte_livre") r.comparacoes[0].observado.fonte.nome = "fonte livre não autorizada"
    if (alvo === "origem") r.origem = "real"
    if (alvo === "booleano") r.comparacoes[0].observado.valor = true
    expect(() => lerResultadosGraficos(r)).toThrow()
  })
  it("a demonstração acompanha a área, o horizonte e as faixas do documento fictício", () => {
    const demo = resultadosDemonstracao({ area_ha: 4000, escopo_carteira: "titulares", inicio: "2000-01-01", fim: "2025-01-01", creditos: { p10: 800000, p50: 1000000, p90: 1200000 } })
    const r = lerResultadosGraficos(demo)
    expect(r.origem).toBe("demonstracao")
    expect(r.comparacoes[0].previsao.referencia.area_elegivel_carteira_ha).toBe(4000)
    expect(r.comparacoes[0].previsao.referencia.escopo_carteira).toBe("titulares")
    expect(r.comparacoes[0].previsao.referencia.area_base_ha).toBe(4000)
    expect(r.comparacoes[0].previsao.referencia.horizonte_dias).toBe(9132)
    expect(r.comparacoes[0].previsao.p50).toBe(1000000)
  })

  it("por hectare preserva denominador original e escopo; não aceita carteira divergente", () => {
    const d = exemplo()
    for (const c of d.comparacoes) for (const k of ["previsao", "observado"]) Object.assign(c[k].referencia, { escala: "por_hectare", unidade: "tCO2e/ha", area_base_ha: 1 })
    expect(lerResultadosGraficos(d).comparacoes[0].previsao.referencia.area_elegivel_carteira_ha).toBe(20)
    d.comparacoes[0].observado.referencia.area_elegivel_carteira_ha = 30
    expect(() => lerResultadosGraficos(d)).toThrow()
  })

  it.each([
    ["congelamento_antes_corte", ["2024-12-31T10:00:00Z", "2025-01-01T00:00:00+14:00"]],
    ["congelamento_no_dia_observado", ["2026-01-01T01:00:00Z", "2025-12-31T23:00:00-02:00"]],
    ["registro_antes_observacao", ["2025-12-31T10:00:00Z", "2026-01-01T00:00:00+14:00"]],
  ])("a cronologia usa o dia UTC para %s", (alvo, instantes) => {
    for (const instante of instantes) {
      const d = exemplo(), c = d.comparacoes[0]
      if (alvo === "registro_antes_observacao") c.observado.registrado_em = instante
      else c.previsao.congelada_em = instante
      expect(() => lerResultadosGraficos(d)).toThrow()
    }
  })

  it.each(["marco", "fonte"])("limita %s ao dia UTC da geração", alvo => {
    for (const gerado of ["2026-01-02T10:00:00Z", "2026-01-03T00:00:00+14:00"]) {
      const d = exemplo()
      d.gerado_em = gerado
      expect(lerResultadosGraficos(d).gerado_em).toBe(gerado)
      if (alvo === "marco") d.contratos[0].marcos.at(-1).data = "2026-01-03"
      else d.comparacoes[0].observado.fonte.data = "2026-01-03"
      expect(() => lerResultadosGraficos(d)).toThrow()
    }
  })

  it.each(["contratado", "emitido", "entregue"])("não promove previsão do aprendizado a %s", (campo) => {
    const d = exemplo(); d.origem = "real"; d.comparacoes = []
    for (const s of d.contratos) for (const m of s.marcos) for (const k of ["contratado", "emitido", "entregue"]) {
      if (m[k]) m[k].fonte.nome = FONTES_POR_NATUREZA[m[k].natureza][0]
    }
    expect(lerResultadosGraficos(d).origem).toBe("real")
    d.contratos[0].marcos.at(-1)[campo].fonte.nome = "Banco de aprendizado da Raíz"
    expect(() => lerResultadosGraficos(d)).toThrow()
  })

})
