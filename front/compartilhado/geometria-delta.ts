/**
 * Geometria dos imóveis do site público em deltas inteiros (micrograus), sem perda.
 *
 * O Pages limita o site a 1 GB e as geometrias dos municípios são quase tudo dele. Cada coordenada vira o inteiro
 * round(x * 1e6) e cada anel guarda o primeiro ponto e as diferenças para o anterior; deltas pequenos comprimem muito
 * melhor que decimais (~25 a 30% menos bytes comprimidos nos municípios reais). A volta é exata: inteiro / 1e6 dá o
 * mesmo número decimal de antes. Se algum valor não fechar exatamente em 6 casas, o município sai como GeoJSON comum.
 *
 * O formato é só de transporte: `decodificarGeometria` devolve o GeoJSON de sempre e também aceita GeoJSON comum.
 */

import type { Geo } from "./dados/tipos"

const ESCALA = 1e6
type Anel = [number, number][]

/** Um anel como [x0, y0, dx1, dy1, ...] em micrograus; null se algum valor não fechar exatamente. */
function anelDelta(anel: Anel): number[] | null {
  const saida: number[] = []
  let ax = 0, ay = 0
  for (const [x, y] of anel) {
    const ix = Math.round(x * ESCALA), iy = Math.round(y * ESCALA)
    if (ix / ESCALA !== x || iy / ESCALA !== y) return null
    saida.push(ix - ax, iy - ay)
    ax = ix
    ay = iy
  }
  return saida
}

const aneisDe = (g: { type: string; coordinates?: unknown }): Anel[][] | null =>
  g.type === "Polygon" ? [g.coordinates as Anel[]] : g.type === "MultiPolygon" ? (g.coordinates as Anel[][]) : null

/** GeoJSON de polígonos → formato em deltas; null quando não dá para guardar sem perder nada. */
export function codificarGeometria(geo: Geo): unknown | null {
  const features = []
  for (const f of geo.features) {
    const g = f.geometry as { type: string; coordinates?: unknown } | null
    const poligonos = g ? aneisDe(g) : null
    if (!g || !poligonos) return null
    const codificados: number[][][] = []
    for (const poligono of poligonos) {
      const aneis: number[][] = []
      for (const anel of poligono) {
        const d = anelDelta(anel)
        if (!d) return null
        aneis.push(d)
      }
      codificados.push(aneis)
    }
    features.push({ type: "Feature", properties: f.properties, geometry: { type: g.type, delta: g.type === "Polygon" ? codificados[0] : codificados } })
  }
  return { type: "FeatureCollection", delta_1e6: true, features }
}

function anelDe(d: number[]): Anel {
  const anel: Anel = []
  let x = 0, y = 0
  for (let i = 0; i + 1 < d.length; i += 2) {
    x += d[i]
    y += d[i + 1]
    anel.push([x / ESCALA, y / ESCALA])
  }
  return anel
}

/** O que o navegador lê: GeoJSON comum passa direto; o formato em deltas volta a ser GeoJSON. */
export function decodificarGeometria(valor: unknown): Geo {
  const v = valor as { delta_1e6?: boolean; features?: { type: string; properties: Record<string, unknown>; geometry: { type: string; delta?: unknown; coordinates?: unknown } }[] }
  if (!v?.delta_1e6 || !Array.isArray(v.features)) return valor as Geo
  return {
    type: "FeatureCollection",
    features: v.features.map((f) => ({
      type: "Feature" as const,
      properties: f.properties,
      geometry: f.geometry.type === "Polygon"
        ? { type: "Polygon", coordinates: (f.geometry.delta as number[][]).map(anelDe) }
        : { type: "MultiPolygon", coordinates: (f.geometry.delta as number[][][]).map((p) => p.map(anelDe)) },
    })),
  } as unknown as Geo
}
