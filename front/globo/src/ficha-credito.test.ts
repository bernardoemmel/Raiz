import { describe, expect, it } from "vitest"
import { fichaCreditoIndisponivel, lerFichaCredito, ORIGEM_EVIDENCIA_FICHA } from "../../compartilhado/ficha-credito"
import { fichaCreditoDemonstracao } from "../../compartilhado/pedidos/ficha-credito-demonstracao"

const esperado = { opcao_id: "barata" as const, revisao_lote: null, exemplo: true }
const exemplo = () => fichaCreditoDemonstracao({ id: "barata", creditos: { p10: 100, p50: 200, p90: 300 }, hectares: 100 })
function documentoOperacionalSintetico() {
  const d = exemplo()
  d.exemplo = false
  d.revisao_lote = "a".repeat(64)
  d.documento_versao = "b".repeat(64)
  d.base!.fonte = "Raíz, motor de lotes"
  d.base!.modelo_versao = "pedidos-2026a"
  d.fonte_area = "Raíz, motor de lotes"
  for (const s of Object.values(d.secoes)) s.fonte = "Raíz, revisão técnica"
  d.secoes.metodo.fonte = "Raíz, motor de lotes"
  for (const e of d.exclusoes!) e.fonte = "Raíz, motor de lotes"
  d.resultados = null
  return d
}
const esperadoReal = { ...esperado, revisao_lote: "a".repeat(64), exemplo: false }

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
    d.resultados = null
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

  it.each([
    ["classe", "flag"], ["metrica", "captura_bruta"], ["escopo_carteira", "titulares_e_reservas"],
    ["unidade", "tCO2e/ano"], ["area_elegivel_carteira_ha", 999],
  ])("recusa gráfico internamente coerente de outra base: %s", (campo, valor) => {
    const d = exemplo()
    const refs = [...d.resultados!.contratos.map(s => s.referencia), ...d.resultados!.comparacoes.flatMap(c => [c.previsao.referencia, c.observado.referencia])]
    for (const ref of refs) {
      Object.assign(ref, { [campo]: valor })
      if (campo === "area_elegivel_carteira_ha") ref.area_base_ha = Number(valor)
    }
    expect(lerFichaCredito(d, esperado).estado).toBe("indisponivel")
  })

  it("mantém vínculo da carteira original até quando o gráfico usa um hectare", () => {
    const d = exemplo()
    const refs = [...d.resultados!.contratos.map(s => s.referencia), ...d.resultados!.comparacoes.flatMap(c => [c.previsao.referencia, c.observado.referencia])]
    for (const ref of refs) Object.assign(ref, { escala: "por_hectare", unidade: "tCO2e/ha", area_base_ha: 1 })
    expect(lerFichaCredito(d, esperado).estado).toBe("disponivel")
    for (const ref of refs) ref.area_elegivel_carteira_ha = 999
    expect(lerFichaCredito(d, esperado).estado).toBe("indisponivel")
  })

  it("recusa publicação posterior à ficha, mesmo no mesmo dia", () => {
    const d = exemplo()
    d.resultados!.gerado_em = "2026-11-12T13:00:00Z"
    expect(lerFichaCredito(d, esperado).estado).toBe("indisponivel")
  })

  it("recusa acompanhamento sem calendário ou denominador comprovado", () => {
    const d = exemplo()
    d.base!.inicio = null
    d.base!.fim = null
    expect(lerFichaCredito(d, esperado).estado).toBe("indisponivel")
    const semArea = exemplo()
    semArea.area_elegivel_ha = null
    semArea.creditos_por_ha = null
    expect(lerFichaCredito(semArea, esperado).estado).toBe("indisponivel")
    const outroPeriodo = exemplo()
    outroPeriodo.base!.inicio = "2001-01-01"
    outroPeriodo.base!.fim = "2026-01-01"
    expect(lerFichaCredito(outroPeriodo, esperado).estado).toBe("indisponivel")
  })

  it("barra a regressão exata de futuro FLAG999ha em ficha carbono50ha25anos", () => {
    const d = fichaCreditoDemonstracao({ id: "barata", creditos: { p10: 100, p50: 200, p90: 300 }, hectares: 62.5 })
    d.base!.inicio = "2026-01-01"
    d.base!.fim = "2051-01-01"
    const r = d.resultados!
    r.gerado_em = "2027-01-03T00:00:00Z"
    const refs = [...r.contratos.map(s => s.referencia), ...r.comparacoes.flatMap(c => [c.previsao.referencia, c.observado.referencia])]
    for (const ref of refs) Object.assign(ref, { classe: "flag", area_base_ha: 999, area_elegivel_carteira_ha: 999, inicio: "2026-01-01", fim: "2027-01-01", horizonte_dias: 365 })
    for (const c of r.comparacoes) {
      c.previsao.corte = "2026-01-01"
      c.previsao.congelada_em = "2026-01-01T00:00:00Z"
      c.observado.data = "2027-01-01"
      c.observado.registrado_em = "2027-01-02T00:00:00Z"
    }
    expect(lerFichaCredito(d, esperado).estado).toBe("indisponivel")
  })

  it.each(["verificado", "emitido", "entregue", "validado", "conservador"])("não promove a estimativa do motor para %s", classe => {
    const d = documentoOperacionalSintetico()
    expect(lerFichaCredito(d, esperadoReal).estado).toBe("disponivel")
    d.base!.classe_evidencia = classe as never
    expect(lerFichaCredito(d, esperadoReal).estado).toBe("indisponivel")
  })

  it.each(["verificado", "emitido", "entregue"] as const)("exige origem, Método e data comuns para %s", classe => {
    const d = documentoOperacionalSintetico()
    const [fonte, texto] = ORIGEM_EVIDENCIA_FICHA[classe]
    d.base!.classe_evidencia = classe
    d.base!.fonte = fonte
    d.creditos_lote = { p10: 200, p50: 200, p90: 200 }
    d.creditos_por_ha = { p10: 2.5, p50: 2.5, p90: 2.5 }
    expect(lerFichaCredito(d, esperadoReal).estado).toBe("indisponivel")
    d.secoes.metodo.texto = texto
    d.secoes.metodo.fonte = fonte
    expect(lerFichaCredito(d, esperadoReal).estado).toBe("disponivel")
    d.secoes.metodo.data_referencia = "2026-11-09"
    expect(lerFichaCredito(d, esperadoReal).estado).toBe("indisponivel")
  })

  it.each(["emitido", "entregue"] as const)("não rotula a faixa de previsão como quantidade %s", classe => {
    const d = documentoOperacionalSintetico()
    const [fonte, texto] = ORIGEM_EVIDENCIA_FICHA[classe]
    d.base!.classe_evidencia = classe
    d.base!.fonte = fonte
    d.secoes.metodo.texto = texto
    d.secoes.metodo.fonte = fonte
    expect(lerFichaCredito(d, esperadoReal).estado).toBe("indisponivel")
  })

  it("projeta somente chaves públicas do contrato privado, sem ecoar campos extras", () => {
    const r = lerFichaCredito({ ...exemplo(), dono: "Pessoa Fictícia do Teste", codigo_car: "DEMONSTRACAO-1" }, esperado)
    expect(r.estado).toBe("disponivel")
    expect(JSON.stringify(r)).not.toContain("Pessoa Fictícia")
    expect(JSON.stringify(r)).not.toContain("DEMONSTRACAO-1")
  })
})
