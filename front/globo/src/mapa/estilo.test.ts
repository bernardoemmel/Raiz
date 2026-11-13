import { describe, expect, it, vi } from "vitest"
import { validateStyleMin } from "@maplibre/maplibre-gl-style-spec"
import { estiloBase } from "./estilo"

vi.stubGlobal("location", { origin: "https://raiz.example" })

describe("estilos internos validados antes de publicar", () => {
  for (const base of [null, "https://raiz.example/geo/base_brasil.pmtiles"]) {
    for (const nacional of [false, true]) {
      for (const rotulos of [false, true]) {
        it(`aceita base=${Boolean(base)}, nacional=${nacional}, rótulos=${rotulos}`, () => {
          expect(validateStyleMin(estiloBase(base, { nacional, rotulos }))).toEqual([])
        })
      }
    }
  }
})
