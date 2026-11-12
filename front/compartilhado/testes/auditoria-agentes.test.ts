import { describe, expect, it } from "vitest"
// @ts-expect-error: script de CI em JavaScript puro, sem tipos
import { conferirAuditoriaAgentes } from "../../scripts/conferir-auditoria-agentes.mjs"

function relatorio() {
  const audits = {
    "llms-txt": { score: 1, scoreDisplayMode: "binary" },
    "agent-accessibility-tree": { score: 1, scoreDisplayMode: "binary" },
    "cumulative-layout-shift": { score: 0.9, scoreDisplayMode: "numeric", numericValue: 0.1 },
    "webmcp-form-coverage": { score: null, scoreDisplayMode: "notApplicable" },
    "ard-schema": { score: null, scoreDisplayMode: "notApplicable" },
  }
  return { audits, categories: { "agentic-browsing": { id: "agentic-browsing", auditRefs: Object.keys(audits).map((id) => ({ id })) } } }
}

describe("portão da auditoria para agentes", () => {
  it("aceita CLS no limite bom e registra WebMCP e ARD como não aplicáveis", () => {
    expect(conferirAuditoriaAgentes(relatorio()).id).toBe("agentic-browsing")
  })

  it("recusa barreira de acessibilidade mesmo com llms aprovado", () => {
    const lhr = relatorio()
    lhr.audits["agent-accessibility-tree"].score = 0
    expect(() => conferirAuditoriaAgentes(lhr)).toThrow(/árvore de acessibilidade/)
  })

  it.each([0.10001, 0.25, 1, Number.NaN])("recusa CLS fora da faixa boa ou não medido: %s", (valor) => {
    const lhr = relatorio()
    lhr.audits["cumulative-layout-shift"].numericValue = valor
    expect(() => conferirAuditoriaAgentes(lhr)).toThrow(/CLS precisa estar na faixa boa/)
  })

  it("recusa nota zero de estabilidade visual", () => {
    const lhr = relatorio()
    lhr.audits["cumulative-layout-shift"].score = 0
    expect(() => conferirAuditoriaAgentes(lhr)).toThrow(/estabilidade visual/)
  })

  it.each(["llms-txt", "agent-accessibility-tree", "cumulative-layout-shift"] as const)("não aceita %s não aplicável como sucesso", (id) => {
    const lhr = relatorio()
    lhr.audits[id].scoreDisplayMode = "notApplicable"
    expect(() => conferirAuditoriaAgentes(lhr)).toThrow(/precisa ser aplicável/)
  })

  it("recusa erro de execução antes de avaliar a nota", () => {
    expect(() => conferirAuditoriaAgentes({ ...relatorio(), runtimeError: { code: "NO_FCP" } })).toThrow(/Lighthouse falhou/)
  })
})
