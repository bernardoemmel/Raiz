import { describe, expect, it } from "vitest"
import { malhasPublicas, urlMalhaIbge } from "../dados/malhas-mapa"

const mt = { fonte: "IBGE", ano: 2025, sha256: "a".repeat(64) }

describe("proveniência pública das malhas territoriais", () => {
  it("mantém a edição por UF e forma a origem oficial sem URL arbitrária", () => {
    expect(malhasPublicas({ MT: mt })).toEqual({ MT: mt })
    expect(malhasPublicas(undefined)).toEqual({})
    expect(urlMalhaIbge("MT", 2025)).toBe("https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/municipio_2025/UFs/MT/MT_Municipios_2025.zip")
  })

  it.each([
    { ZZ: mt }, { MT: { ...mt, contato: "privado" } }, { MT: { ...mt, url: "https://fora.invalid/" } },
    { MT: { ...mt, fonte: "qualquer" } }, { MT: { ...mt, ano: 2025.5 } }, { MT: { ...mt, ano: 1999 } },
    { MT: { ...mt, ano: 9999 } }, { MT: { ...mt, sha256: "incompleto" } }, { MT: null }, [], null,
  ])("recusa campos livres, fonte desconhecida e metadados inválidos", valor => {
    expect(() => malhasPublicas(valor)).toThrow()
  })
})
