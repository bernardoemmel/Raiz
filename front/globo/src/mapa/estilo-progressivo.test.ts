import { describe, expect, it, vi } from "vitest"
import { validateStyleMin } from "@maplibre/maplibre-gl-style-spec"
import type { LayerSpecification, Map as MapaGL } from "maplibre-gl"
import { cederProcessamento } from "../../../compartilhado/ceder-processamento"
import { estiloBase } from "./estilo"
import { completarEstiloNacional, separarEstiloNacional } from "./estilo-progressivo"

vi.mock("../../../compartilhado/ceder-processamento", () => ({ cederProcessamento: vi.fn(async () => {}) }))
vi.stubGlobal("location", { origin: "https://raiz.example" })

function destino(camadas: LayerSpecification[]): Pick<MapaGL, "addLayer" | "getLayer"> {
  return {
    getLayer: (id: string) => camadas.find(camada => camada.id === id),
    addLayer: (camada: LayerSpecification, antes?: string) => {
      camadas.splice(antes ? camadas.findIndex(c => c.id === antes) : camadas.length, 0, camada)
    },
  } as unknown as Pick<MapaGL, "addLayer" | "getLayer">
}

describe("estilo nacional por classes, com apresentação progressiva", () => {
  it("preserva integralmente fontes, ordem, propriedades e validade do estilo real", async () => {
    const estilo = estiloBase("https://raiz.example/base.pmtiles", { nacional: true, dadosNacionais: {
      areas: "https://raiz.example/brasil_estados.geojson", rotulos: { type: "FeatureCollection", features: [] }, processadas: ["PA"],
    } })
    const plano = separarEstiloNacional(estilo), camadas = [...plano.inicial.layers]
    expect(plano.inicial.sources).toBe(estilo.sources)
    expect(camadas.every(camada => ["fill", "background"].includes(camada.type))).toBe(true)
    expect(validateStyleMin(plano.inicial)).toEqual([])
    expect(await completarEstiloNacional(destino(camadas), plano, () => false)).toBe(true)
    expect(camadas).toEqual(estilo.layers)
    expect(validateStyleMin({ ...plano.inicial, layers: camadas })).toEqual([])
  })

  it.each([0, 1])("navegar na continuação %i impede qualquer instalação tardia", async pausa => {
    const plano = separarEstiloNacional(estiloBase(null, { nacional: true })), camadas = [...plano.inicial.layers]
    let encerrado = false, chamadas = 0
    vi.mocked(cederProcessamento).mockImplementation(async () => { if (chamadas++ === pausa) encerrado = true })
    expect(await completarEstiloNacional(destino(camadas), plano, () => encerrado)).toBe(false)
    expect(camadas.some(camada => camada.type === "symbol")).toBe(false)
    expect(camadas.some(camada => camada.type === "line")).toBe(pausa === 1)
    vi.mocked(cederProcessamento).mockImplementation(async () => {})
  })
})
