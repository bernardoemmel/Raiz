import { describe, expect, it } from "vitest"
import { fmtDataHoraBrasilia } from "../formato"

describe("datas de cobertura e processamento no fuso de Brasília", () => {
  it.each([
    ["2026-11-13T12:04:00Z", "13/11/2026, 09:04"],
    ["2026-11-13T01:04:00Z", "12/11/2026, 22:04"],
    ["2017-12-15T12:04:00Z", "15/12/2017, 10:04"],
    ["2026-11-13T09:04:00-03:00", "13/11/2026, 09:04"],
  ])("preserva instante, data civil e regras históricas para %s", (iso, esperado) => {
    expect(fmtDataHoraBrasilia(iso)).toBe(esperado)
  })
  it("preserva o tratamento anterior de data inválida sem lançar erro", () => {
    expect(fmtDataHoraBrasilia("data-inválida")).toBe(new Date("data-inválida").toLocaleString("pt-BR"))
  })
})
