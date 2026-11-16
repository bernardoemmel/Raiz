import { describe, expect, it, vi } from "vitest"
import { createExpression, validateStyleMin } from "@maplibre/maplibre-gl-style-spec"
import { estiloBase } from "./estilo"
import { filtroEstadosProcessados } from "./nacional"

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
  for (const base of [null, "https://raiz.example/geo/base_brasil.pmtiles"]) {
    for (const areas of [{ type: "FeatureCollection" as const, features: [] }, "https://raiz.example/geo/brasil_estados.geojson"]) {
      it(`valida cobertura por UF, base=${Boolean(base)}, fonte=${typeof areas}`, () => {
        const estilo = estiloBase(base, { nacional: true, dadosNacionais: { areas, rotulos: { type: "FeatureCollection", features: [] }, processadas: ["PA", "TO"] } })
        expect(validateStyleMin(estilo)).toEqual([])
      })
    }
  }
  it("muda a cobertura pelos códigos sem exigir o campo s nos contornos", () => {
    for (const ufs of [["PA", "TO"], ["PA", "AM"], []]) {
      const e = createExpression(filtroEstadosProcessados(ufs), "layers.estados-preenchimento.filter")
      expect(e.result).toBe("success")
      if (e.result !== "success") throw new Error("Filtro estadual inválido")
      for (const uf of ["PA", "AM", "TO", "SP"])
        expect(e.value.evaluate({ zoom: 2 }, { type: 3, properties: { uf } })).toBe(ufs.includes(uf))
    }
  })
})
