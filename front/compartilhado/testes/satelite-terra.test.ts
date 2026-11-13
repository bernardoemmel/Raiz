import { describe, expect, it } from "vitest"
import { legendaCenaSatelite } from "../satelite-terra"

describe("data e método do Sentinel-2", () => {
  it("preserva as duas datas da composição mediana", () => {
    expect(legendaCenaSatelite({ data_cena: "2026-09-06 a 2026-10-23", metodo: "mediana", satelite: "Sentinel-2" }))
      .toBe("Composição mediana de cenas Sentinel-2 de 06/09/2026 a 23/10/2026")
  })
  it("identifica a data e a plataforma de uma única cena", () => {
    expect(legendaCenaSatelite({ data_cena: "2026-10-10", metodo: "cena", satelite: "Sentinel-2B" }))
      .toBe("Sentinel-2B em 10/10/2026")
  })
})
