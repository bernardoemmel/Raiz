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
  it("preserva a versão oficial modelo|prompt do leitor, mantendo grupos pequenos e datas inválidas fora", () => {
    const r = resumoAcertoTeste()
    r.versoes[0].modelo = "leitor_certidao"; r.versoes[0].versao = "claude-haiku-4-5-20251001|certidao-v1.abcdef1234"
    expect(lerResumoAcerto(r).versoes[0].versao).toBe(r.versoes[0].versao)
    expect(JSON.stringify(lerResumoAcerto(r))).not.toContain("NUNCA-PUBLICAR")
    for (const mudanca of [{ imoveis_observados: 4 }, { ultima_observacao: "2026-05-31" }, { modelo: "motor" }]) {
      expect(() => lerResumoAcerto({ ...r, versoes: [{ ...r.versoes[0], ...mudanca }] })).toThrow()
    }
  })
  it.each(["modelo|", "|prompt", "modelo||prompt", "modelo|prompt|outro", "modelo|texto livre", "modelo|prompt\n", "modelo|<script>", "modelo|" + "p".repeat(114)])("recusa versão documental inválida %j", (versao) => {
    const r = resumoAcertoTeste(); Object.assign(r.versoes[0], { modelo: "leitor_certidao", versao })
    expect(() => lerResumoAcerto(r)).toThrow(/Grupo/)
  })
})

it("rejeita documento civil usado como identificador de modelo ou versão", () => {
  const cpf = ["123", "456", "789"].join("") + "09"
  const cnpj = ["11", "222", "333", "0001", "81"].join("")
  for (const documento of [cpf, cnpj, `${cpf.slice(0, 3)}.${cpf.slice(3, 6)}.${cpf.slice(6, 9)}-${cpf.slice(9)}`]) {
    for (const campo of ["modelo", "versao", "alvo"]) {
      const r = resumoAcertoTeste(); Object.assign(r.versoes[0], { [campo]: `modelo-${documento}` })
      expect(() => lerResumoAcerto(r)).toThrow(/Grupo/)
    }
  }
})
