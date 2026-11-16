import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { gzipSync } from "node:zlib"
import { describe, expect, it } from "vitest"
import type { Geo } from "../dados/tipos"
import { codificarGeometria, decodificarGeometria } from "../geometria-delta"

const geo = (): Geo => ({ type: "FeatureCollection", features: [
  { type: "Feature", properties: { cod_imovel: "PA-1507300-A", sobreposto: true }, geometry: { type: "Polygon", coordinates: [
    [[-51.123456, -3.654321], [-51.123401, -3.654, ], [-51.1229, -3.6551], [-51.123456, -3.654321]],
    [[-51.1232, -3.6542], [-51.1231, -3.6543], [-51.1230, -3.6542], [-51.1232, -3.6542]]] } },
  { type: "Feature", properties: { cod_imovel: "PA-1507300-B" }, geometry: { type: "MultiPolygon", coordinates: [
    [[[10.000001, 0], [10.000002, 0.000001], [10, 0.000003], [10.000001, 0]]],
    [[[-179.999999, 89.999999], [-179.99999, 89.99998], [-179.9999, 89.99999], [-179.999999, 89.999999]]]] } },
] } as unknown as Geo)

describe("geometria em deltas inteiros", () => {
  it("volta exatamente igual ao GeoJSON de origem (polígono com furo e multipolígono)", () => {
    const original = geo()
    const codificado = codificarGeometria(original)
    expect(codificado).not.toBeNull()
    const volta = decodificarGeometria(JSON.parse(JSON.stringify(codificado)))
    expect(volta).toEqual(original)
    expect(volta.features[0].properties).toEqual({ cod_imovel: "PA-1507300-A", sobreposto: true })
  })

  it("não perde nada: valor com mais de 6 casas faz o município sair como GeoJSON comum", () => {
    const g = geo()
    ;(g.features[0].geometry as unknown as { coordinates: number[][][] }).coordinates[0][1] = [-51.1234019, -3.654]
    expect(codificarGeometria(g)).toBeNull()
    const naoPoligono = { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [1, 2] } }] } as unknown as Geo
    expect(codificarGeometria(naoPoligono)).toBeNull()
  })

  it("GeoJSON comum passa direto no leitor, então arquivos antigos continuam abrindo", () => {
    const g = geo()
    expect(decodificarGeometria(g)).toBe(g)
    expect(decodificarGeometria(null)).toBeNull()
  })

  it("comprime menos bytes que o GeoJSON decimal", () => {
    const aneis = (n: number) => Array.from({ length: n }, (_, i) => [-51.1 + Math.sin(i / 7) * 0.01 + i * 0.000013, -3.6 + Math.cos(i / 5) * 0.01 - i * 0.000011])
      .map(([x, y]) => [Math.round(x * 1e6) / 1e6, Math.round(y * 1e6) / 1e6])
    const g = { type: "FeatureCollection", features: Array.from({ length: 150 }, (_, k) => {
      const anel = aneis(60 + (k % 40)).map(([x, y]) => [x + k * 0.0005, y + k * 0.0003].map((v) => Math.round(v * 1e6) / 1e6))
      return { type: "Feature", properties: { cod_imovel: `PA-1507300-${k}` }, geometry: { type: "Polygon", coordinates: [[...anel, anel[0]]] } }
    }) } as unknown as Geo
    const decimal = gzipSync(JSON.stringify(g), { level: 9 }).length
    const delta = gzipSync(JSON.stringify(codificarGeometria(g)), { level: 9 }).length
    expect(delta).toBeLessThan(decimal * 0.85)
    expect(decodificarGeometria(JSON.parse(JSON.stringify(codificarGeometria(g))))).toEqual(g)
  })
})

// Municípios reais do geo.py (front/geo não vai ao git): onde existem, a volta tem de ser exata e o arquivo menor.
const dirGeo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../geo")
describe.skipIf(!fs.existsSync(path.join(dirGeo, "imoveis_1507300.geojson")))("municípios reais", () => {
  it.each(["1504950", "1507300"])("município %s: volta exata e menos bytes comprimidos", (cod) => {
    const bruto = JSON.parse(fs.readFileSync(path.join(dirGeo, `imoveis_${cod}.geojson`), "utf8")) as Geo
    const g = { type: "FeatureCollection", features: bruto.features.filter((f) => f.geometry && "coordinates" in f.geometry).map((f) => ({ type: "Feature", properties: { cod_imovel: f.properties.cod_imovel }, geometry: f.geometry })) } as unknown as Geo
    const codificado = codificarGeometria(g)
    expect(codificado).not.toBeNull()
    expect(decodificarGeometria(JSON.parse(JSON.stringify(codificado)))).toEqual(g)
    const antes = gzipSync(JSON.stringify(g), { level: 6 }).length, depois = gzipSync(JSON.stringify(codificado), { level: 9 }).length
    console.log(`município ${cod}: ${antes} -> ${depois} bytes comprimidos (${Math.round((100 * depois) / antes)}%)`)
    expect(depois).toBeLessThan(antes * 0.85)
  })
})
