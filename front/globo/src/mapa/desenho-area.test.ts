import { describe, expect, it } from "vitest"
import { desenhoDePontos, poligonoDesenhado } from "./desenho-area"

describe("área desenhada do pedido", () => {
  it("preserva as coordenadas escolhidas e fecha somente uma área válida", () => {
    const p: [number, number][] = [[-52, -6], [-51, -6], [-51, -5]]
    expect(desenhoDePontos(p.slice(0, 2)).features.map(f => f.geometry.type)).toEqual(["Point", "Point", "LineString"])
    expect(poligonoDesenhado(p)?.features[0].geometry.coordinates).toEqual([[...p, p[0]]])
    expect(poligonoDesenhado(p)?.features[0].properties).toEqual({})
  })
  it("recusa linha, duplicatas sem área e coordenadas inválidas", () => {
    for (const pontos of [[[0, 0], [1, 1], [2, 2]], [[0, 0], [0, 0], [1, 0]], [[NaN, 0], [1, 1], [2, 0]], [[181, 0], [1, 1], [2, 0]]] as [number, number][][])
      expect(poligonoDesenhado(pontos)).toBeNull()
  })
})
