import { describe, expect, it } from "vitest"
import { estadosDaBusca } from "./busca-estados"

describe("busca estadual do topo", () => {
  it("encontra UF e nome sem acento no mesmo catálogo das rotas", () => {
    expect(estadosDaBusca("pa")[0]).toEqual({ uf: "PA", nome: "Pará" })
    expect(estadosDaBusca("PARÁ")[0]).toEqual({ uf: "PA", nome: "Pará" })
    expect(estadosDaBusca("sao paulo")).toEqual([{ uf: "SP", nome: "São Paulo" }])
  })
  it("preserva busca de código do CAR ou IBGE sem produzir estados", () => {
    expect(estadosDaBusca("1507300")).toEqual([])
    expect(estadosDaBusca("PA-1507300-ABC")).toEqual([])
    expect(estadosDaBusca("p")).toEqual([])
  })
})
