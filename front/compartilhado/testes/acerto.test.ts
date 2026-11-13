import { describe, expect, it, vi } from "vitest"
import { ACERTO_AUSENTE, fonteAcerto, lerResumoAcerto } from "../acerto"

export const resumoAcertoTeste = () => ({
  ...ACERTO_AUSENTE, gerado_em: "2026-11-12T12:00:00Z", cod_imovel: "NUNCA-PUBLICAR",
  versoes: [{ modelo: "motor", versao: "v1", alvo: "area_ha", horizonte_dias: 365, tipo: "numero", avaliacao: "ao_vivo", criterio_temporal: "observacao_na_data_alvo", cronologia: "congelada_antes_da_observacao", comparacoes: 10, imoveis_observados: 5, primeiro_corte: "2025-01-01", ultimo_corte: "2025-06-01", ultima_observacao: "2026-06-01", metricas: { ae: 0, eq: 0, segredo: 1200 }, cod_imovel: "NUNCA-PUBLICAR", nomes: ["NUNCA-PUBLICAR"] }],
})
describe("resumo de acerto real", () => {
  it("preserva zero observado e reconstrói somente os agregados permitidos", () => {
    const r = lerResumoAcerto(resumoAcertoTeste())
    expect(r.versoes[0].metricas.ae).toBe(0)
    expect(JSON.stringify(r)).not.toMatch(/NUNCA-PUBLICAR|cod_imovel|segredo|nomes/)
  })
  it("ausência não equivale a erro zero", () => expect(lerResumoAcerto(ACERTO_AUSENTE).versoes).toEqual([]))
  it.each([0, 4, null, NaN])("recusa grupo com %s imóveis", (n) => {
    const r = resumoAcertoTeste(); Object.assign(r.versoes[0], { imoveis_observados: n })
    expect(() => lerResumoAcerto(r)).toThrow(/Grupo/)
  })
  it("recusa métricas nulas ou não finitas e contagem incompatível", () => {
    for (const ae of [null, NaN, Infinity, -1]) {
      const r = resumoAcertoTeste(); Object.assign(r.versoes[0].metricas, { ae })
      expect(() => lerResumoAcerto(r)).toThrow(/Métrica/)
    }
    const r = resumoAcertoTeste(); r.versoes[0].comparacoes = 4
    expect(() => lerResumoAcerto(r)).toThrow(/Grupo/)
  })
  it("recusa estatísticas sem data e formatos internos de aprendizado", () => {
    expect(() => lerResumoAcerto({ ...resumoAcertoTeste(), gerado_em: null })).toThrow(/data/)
    expect(() => lerResumoAcerto({ previsoes: [], campeoes: [] })).toThrow(/Formato/)
  })
  it("reprova datas impossíveis, futuras e horizontes ainda não encerrados", () => {
    for (const mudanca of [{ ultima_observacao: "2026-02-30" }, { ultima_observacao: "2027-01-01" }, { horizonte_dias: 1000 }]) {
      const r = resumoAcertoTeste(); Object.assign(r.versoes[0], mudanca)
      expect(() => lerResumoAcerto(r)).toThrow()
    }
  })
  it("exige a data-alvo e a cronologia declarada na projeção, sem confiar em rótulo ao vivo sozinho", () => {
    for (const mudanca of [{ ultima_observacao: "2026-05-31" }, { ultima_observacao: "2026-06-02" },
      { criterio_temporal: undefined }, { cronologia: undefined }, { cronologia: "backtest_declarado" }]) {
      const r = resumoAcertoTeste(); Object.assign(r.versoes[0], mudanca)
      expect(() => lerResumoAcerto(r)).toThrow()
    }
  })
  it("usa a raiz configurada e a API pública, sem token operacional", async () => {
    const pedir = vi.fn<typeof fetch>(async () => new Response(JSON.stringify(ACERTO_AUSENTE)))
    await fonteAcerto({ base: "/Raiz/", pedir })()
    expect(pedir.mock.calls[0][0]).toBe("/Raiz/acerto/placar.json")
    await fonteAcerto({ api: "https://api.example/", pedir })()
    expect(pedir.mock.calls[1][0]).toBe("https://api.example/acerto/resumo")
    expect(JSON.stringify(pedir.mock.calls)).not.toContain("Authorization")
  })
  it("falha de consulta não vira ausência de observações", async () => {
    await expect(fonteAcerto({ pedir: async () => new Response("", { status: 503 }) })()).rejects.toThrow(/consultar/)
  })
})
