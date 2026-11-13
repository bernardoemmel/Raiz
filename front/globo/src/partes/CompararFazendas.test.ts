import { describe, expect, it, vi } from "vitest"
vi.mock("../pedidos", () => ({ useSessao: () => null }))
vi.mock("../prospeccao", () => ({ prospeccao: {}, numeroTerra: String, dataTerra: String }))
import { lerCodigosComparacao } from "./CompararFazendas"

const car = (n: number) => `PA-1504950-${String(n).repeat(32)}`
describe("seleção de fichas para comparar", () => {
  it("aceita de duas a cinco fazendas, com normalização do recibo", () => {
    const a = car(1).toLowerCase().replace(/(.{4})/g, "$1.")
    expect(lerCodigosComparacao(`${a}\n${car(2)}`)).toEqual({ codigos: [car(1), car(2)], erro: null })
    expect(lerCodigosComparacao([1, 2, 3, 4, 5].map(car).join("\n")).erro).toBeNull()
  })
  it("duplicar um CAR não conta como outra fazenda", () => {
    expect(lerCodigosComparacao(`${car(1)}\n${car(1)}`).erro).toContain("dois códigos")
    expect(lerCodigosComparacao(`${car(1)};${car(2)};${car(1)}`).codigos).toEqual([car(1), car(2)])
  })
  it("recusa seleção excessiva e código inválido antes de consultar a API", () => {
    expect(lerCodigosComparacao([1, 2, 3, 4, 5, 6].map(car).join("\n")).erro).toContain("cinco")
    expect(lerCodigosComparacao(`${car(1)}\nZZ-1504950-${"A".repeat(32)}`).erro).toContain("Confira")
    expect(lerCodigosComparacao(`${car(1)}\nPA-1504950-123`).erro).toContain("Confira")
  })
})
