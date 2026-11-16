import { describe, expect, it } from "vitest"
import { ausenteNacional, projetarResumoNacional, recorteDoPedido } from "../pedidos/lote-nacional"
import type { CamposPedido } from "../pedidos/tipos"

const opcao = (fazendas: number | null, sob = "nao_verificada") => ({ fazendas, pequenas: 3, hectares: 900.5,
  creditos: { p10: 800, p50: 1200, p90: 1500 }, fecha_meta: true, sobreposicao: sob })
const recorte = (nome: string, tipo: string, fazendas = 12) => ({ nome, tipo, sobreposicao: "nao_verificada", vazio: !fazendas,
  opcoes: { barata: opcao(fazendas), segura: opcao(fazendas), compacta: opcao(fazendas) },
  terra_em_espera: { incluida_no_pedido: false, fazendas: 40, pequenas: 9, hectares: 5000, creditos_p50: 77000, habilita_venda: false } })
const arquivo = (recortes: unknown[]) => ({ contrato: "publico_lotes_nacional", versao: 1, estado: "publicado", atualizado_em: "2026-11-16T20:00:00Z", aviso: "Aviso.", recortes })
const onde = (p: Partial<CamposPedido["onde"]> = {}): CamposPedido["onde"] => ({ biomas: [], ufs: [], municipios: [], so_fornecedores_cadeia: false, ...p })

describe("resumo público do lote nacional", () => {
  const resumo = projetarResumoNacional(arquivo([recorte("Brasil", "brasil"), recorte("Cerrado", "bioma"), recorte("PA", "uf"), recorte("BA", "uf", 0)]))

  it("arquivo ausente, quebrado ou de outro contrato vira ausente, nunca zero", () => {
    for (const ruim of [null, undefined, {}, "x", { ...arquivo([]), contrato: "outro" }, arquivo([]), { ...arquivo([recorte("PA", "uf")]), estado: "ausente" }])
      expect(projetarResumoNacional(ruim)).toMatchObject({ estado: "ausente", recortes: [] })
    expect(projetarResumoNacional(null)).toEqual(ausenteNacional())
  })

  it("lista positiva: nada além das medidas das três opções, da terra em espera e da sobreposição", () => {
    const sujo = arquivo([{ ...recorte("PA", "uf"), cod_imovel: "CAR-PRIVADO", pacote: "https://privado.invalid/x" }])
    ;(sujo.recortes[0] as { opcoes: { barata: Record<string, unknown> } }).opcoes.barata.caminho = "SEGREDO"
    const texto = JSON.stringify(projetarResumoNacional(sujo))
    expect(texto).not.toMatch(/PRIVADO|privado\.invalid|SEGREDO|cod_imovel/)
  })

  it("sobreposição só é verificada quando a origem disse; texto estranho vira não verificada", () => {
    const r = projetarResumoNacional(arquivo([{ ...recorte("PA", "uf"), sobreposicao: "talvez", opcoes: { barata: opcao(12, "verificada"), segura: opcao(12, "xyz"), compacta: opcao(12) } }]))
    expect(r.recortes[0].sobreposicao).toBe("nao_verificada")
    expect([r.recortes[0].opcoes.barata.sobreposicao, r.recortes[0].opcoes.segura.sobreposicao]).toEqual(["verificada", "nao_verificada"])
  })

  it("valor ausente ou inválido fica desconhecido (null), a terra em espera nunca habilita venda", () => {
    const r = projetarResumoNacional(arquivo([{ ...recorte("PA", "uf"), opcoes: { barata: { fazendas: -1, hectares: "x", creditos: { p10: 5, p50: 1, p90: 9 } }, segura: opcao(1), compacta: opcao(1) },
      terra_em_espera: { fazendas: 4, habilita_venda: true } }]))
    expect(r.recortes[0].opcoes.barata).toMatchObject({ fazendas: null, hectares: null, creditos: null, fecha_meta: null })
    expect(r.recortes[0].terra_em_espera).toMatchObject({ fazendas: 4, hectares: null, habilita_venda: false })
  })

  it("lote vazio é marcado e a terra em espera segue visível", () => {
    const ba = resumo.recortes.find((r) => r.nome === "BA")!
    expect(ba.vazio).toBe(true)
    expect(ba.terra_em_espera.fazendas).toBe(40)
  })

  it("o pedido escolhe o recorte: estado, bioma ou Brasil; município e combinações não têm resumo próprio", () => {
    expect(recorteDoPedido(resumo, onde())?.nome).toBe("Brasil")
    expect(recorteDoPedido(resumo, onde({ ufs: ["PA"] }))?.nome).toBe("PA")
    expect(recorteDoPedido(resumo, onde({ biomas: ["Cerrado"] }))?.nome).toBe("Cerrado")
    expect(recorteDoPedido(resumo, onde({ ufs: ["PA", "BA"] }))).toBeNull()
    expect(recorteDoPedido(resumo, onde({ ufs: ["PA"], biomas: ["Cerrado"] }))).toBeNull()
    expect(recorteDoPedido(resumo, onde({ municipios: ["1504950"] }))).toBeNull()
    expect(recorteDoPedido(resumo, onde({ ufs: ["AM"] }))).toBeNull() // sem consulta publicada
    expect(recorteDoPedido(ausenteNacional(), onde())).toBeNull()
  })
})
