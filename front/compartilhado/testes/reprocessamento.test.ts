import { describe, expect, it } from "vitest"
import { lerReprocessamento, rotuloRegras } from "../dados/reprocessamento"

const doc = {
  escopo: "publico_basico",
  versao_publicacao: 1,
  geracao_vigente: "2026-11-17",
  gerado_em: "2026-11-17T10:00:00+00:00",
  estados: {
    AC: { situacao: "atualizado", geracao: "2026-11-17", prontos: 22, total: 22, atualizado_em: "2026-11-17T09:00:00+00:00" },
    PA: { situacao: "reprocessando", prontos: 40, total: 144, motivo: "tarefa_desatualizada", desde: "2026-11-17T08:00:00+00:00" },
    MG: { situacao: "antigo" },
  },
}

describe("reprocessamento estado por estado", () => {
  it("lê o contrato fechado e recusa qualquer campo a mais", () => {
    expect(lerReprocessamento(doc)?.estados.PA.prontos).toBe(40)
    expect(lerReprocessamento({ ...doc, extra: 1 })).toBeNull()
    expect(lerReprocessamento({ ...doc, estados: { PA: { situacao: "reprocessando", cod_imovel: "PA-1" } } })).toBeNull()
    expect(lerReprocessamento({ ...doc, estados: { XX: { situacao: "antigo" } } })).toBeNull()
    expect(lerReprocessamento({ ...doc, escopo: "privado" })).toBeNull()
  })

  it("só chama de regras novas o que está no ar com a geração vigente", () => {
    const e = lerReprocessamento(doc)!.estados
    expect(rotuloRegras(e.AC, "2026-11-17")).toMatchObject({ tipo: "novas", selo: "Regras novas" })
    expect(rotuloRegras(e.AC, "2026-12-01").tipo).toBe("antigas")
    expect(rotuloRegras(e.PA, "2026-11-17")).toMatchObject({ tipo: "reprocessando", selo: "Reprocessando 40/144" })
    expect(rotuloRegras(e.PA, "2026-11-17").frase).toContain("regras antigas")
    expect(rotuloRegras(e.MG, "2026-11-17").tipo).toBe("antigas")
    expect(rotuloRegras(undefined, "2026-11-17").selo).toBe("Regras antigas")
  })
})
