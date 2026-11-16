import { describe, expect, it, vi } from "vitest"
import type { Map } from "maplibre-gl"
import { adicionarSatelitePublico, fonteSatelitePublico, ID_VEU_SATELITE, SATELITE_PUBLICO } from "./satelite-publico"

function mapaFalso() {
  const eventos = new globalThis.Map<string, (v: { sourceId: string; isSourceLoaded?: boolean }) => void>()
  const mapa = {
    on: vi.fn((nome: string, fn: (v: { sourceId: string; isSourceLoaded?: boolean }) => void) => eventos.set(nome, fn)),
    off: vi.fn((nome: string) => eventos.delete(nome)),
    addSource: vi.fn(), addLayer: vi.fn(), getLayer: vi.fn(() => true), setLayoutProperty: vi.fn(),
    getZoom: vi.fn(() => 13),
  }
  return { mapa, eventos }
}

describe("satélite público com ano e licença revisados", () => {
  it("fixa o vintage comercial aberto, adia downloads até o detalhe e preserva overzoom", () => {
    const fonte = fonteSatelitePublico()
    expect(fonte.tiles).toEqual(["https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/GoogleMapsCompatible/{z}/{y}/{x}.jpg"])
    expect(SATELITE_PUBLICO.titulo).toContain("2016/2017 (histórico)")
    expect(SATELITE_PUBLICO.licenca).toBe("CC BY 4.0")
    expect(fonte.minzoom).toBe(12)
    expect(fonte.maxzoom).toBe(14)
    expect(fonte.attribution).toContain("Contains modified Copernicus Sentinel data 2016 &amp; 2017")
  })

  it("anuncia imagem recebida só para a fonte correta e no zoom de detalhe", () => {
    const { mapa, eventos } = mapaFalso(), estado = vi.fn()
    const limpar = adicionarSatelitePublico(mapa as unknown as Map, "municipios", estado)
    eventos.get("sourcedata")?.({ sourceId: "protomaps", isSourceLoaded: true })
    expect(estado.mock.calls).toEqual([["carregando"]])
    mapa.getZoom.mockReturnValue(10)
    eventos.get("sourcedata")?.({ sourceId: SATELITE_PUBLICO.id, isSourceLoaded: true })
    expect(estado.mock.calls).toEqual([["carregando"]])
    mapa.getZoom.mockReturnValue(13)
    eventos.get("sourcedata")?.({ sourceId: SATELITE_PUBLICO.id, isSourceLoaded: true })
    expect(estado).toHaveBeenLastCalledWith("disponivel")
    limpar()
    expect(eventos.size).toBe(0)
  })

  it("retira imagem e véu após falha da fonte sem apagar a base vetorial", () => {
    const { mapa, eventos } = mapaFalso(), estado = vi.fn()
    adicionarSatelitePublico(mapa as unknown as Map, "municipios", estado)
    eventos.get("error")?.({ sourceId: "protomaps" })
    expect(mapa.setLayoutProperty).not.toHaveBeenCalled()
    eventos.get("error")?.({ sourceId: SATELITE_PUBLICO.id })
    expect(mapa.setLayoutProperty.mock.calls).toEqual([[SATELITE_PUBLICO.id, "visibility", "none"], [ID_VEU_SATELITE, "visibility", "none"]])
    expect(estado).toHaveBeenLastCalledWith("indisponivel")
    eventos.get("sourcedata")?.({ sourceId: SATELITE_PUBLICO.id, isSourceLoaded: true })
    expect(estado).toHaveBeenLastCalledWith("indisponivel")
  })
})
