import { describe, expect, it } from "vitest"
import { hectaresDoRaioX, mailtoContato, raioX } from "../raio-x"

describe("Raio-X do fazendeiro", () => {
  it("hectares inteiros e nunca negativos", () => {
    expect(hectaresDoRaioX(12.4)).toBe(12)
    expect(hectaresDoRaioX(0.4)).toBe(0)
    expect(hectaresDoRaioX(-3)).toBe(0)
  })

  it("sem a conta do dono, a faixa não é inventada", () => {
    const r = raioX(12.4, null)
    expect(r.temValor).toBe(false)
    expect(r.valor).toContain("ainda não foi calculada")
    expect(r.valor).not.toContain("R$")
  })

  it("com a conta do dono, mostra o valor por ano da área de restauração", () => {
    const r = raioX(12.4, { disponivel: true, area_ha: 12.5, pagamento_dono: { rs_ha_ano_medio: 300 } })
    expect(r.temValor).toBe(true)
    // o Intl põe espaço não quebrável entre "R$" e o número
    expect(r.valor.replace(/\u00a0/g, " ")).toContain("R$ 3.750")
    expect(r.valor).toContain("não é promessa")
  })

  it("conta indisponível ou sem mediana continua sem valor", () => {
    expect(raioX(5, { disponivel: false }).temValor).toBe(false)
    expect(raioX(5, { disponivel: true, pagamento_dono: { rs_ha_ano_medio: null } }).temValor).toBe(false)
  })
})

describe("pedido de contato por e-mail", () => {
  const link = mailtoContato("PA-1500107-003027D8E2544FFC9DAE6FEA367D9516", "Abaetetuba", "PA", "contato@raiz.exemplo")

  it("leva o código do CAR e o destinatário, sem CPF nem nome", () => {
    expect(link.startsWith("mailto:contato@raiz.exemplo?")).toBe(true)
    expect(decodeURIComponent(link)).toContain("PA-1500107-003027D8E2544FFC9DAE6FEA367D9516")
    expect(decodeURIComponent(link)).toContain("Abaetetuba (PA)")
    expect(link).not.toMatch(/\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11}/)
  })

  it("sem endereço configurado, abre o e-mail com o destinatário em branco", () => {
    expect(mailtoContato("PA-1", "X", "PA").startsWith("mailto:?subject=")).toBe(true)
  })
})
