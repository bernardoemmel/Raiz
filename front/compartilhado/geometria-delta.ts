/**
 * Geometria dos imóveis do site público em deltas inteiros (micrograus), sem perda.
 *
 * O Pages limita o site a 1 GB e as geometrias dos municípios são quase tudo dele. Cada coordenada vira o inteiro
 * round(x * 1e6) e cada anel guarda o primeiro ponto e as diferenças para o anterior; deltas pequenos comprimem muito
 * melhor que decimais (~25 a 30% menos bytes comprimidos nos municípios reais). A volta é exata: inteiro / 1e6 dá o
 * mesmo número decimal de antes. Se algum valor não fechar exatamente em 6 casas, o município sai como GeoJSON comum.
 *
 * Primeiro tenta 1e5 (5 casas, o que o geo.py grava desde a v2): números menores, ~20% menos bytes. Se alguma
 * coordenada não fechar em 5 casas, usa 1e6; se nem assim, GeoJSON comum. A volta é sempre exata.
 *
 * O formato é só de transporte: `decodificarGeometria` devolve o GeoJSON de sempre e também aceita GeoJSON comum.
 */

import type { Geo } from "./dados/tipos"

const ESCALAS = [1e5, 1e6] as const
type Anel = [number, number][]

/** Um anel como [x0, y0, dx1, dy1, ...] na escala dada; null se algum valor não fechar exatamente. */
function anelDelta(anel: Anel, escala: number): number[] | null {
  const saida: number[] = []
  let ax = 0, ay = 0
  for (const [x, y] of anel) {
    const ix = Math.round(x * escala), iy = Math.round(y * escala)
    if (ix / escala !== x || iy / escala !== y) return null
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
  for (const escala of ESCALAS) {
    const codificado = codificarNaEscala(geo, escala)
    if (codificado) return codificado
  }
  return null
}

function codificarNaEscala(geo: Geo, escala: number): unknown | null {
  const features = []
  for (const f of geo.features) {
    const g = f.geometry as { type: string; coordinates?: unknown } | null
    const poligonos = g ? aneisDe(g) : null
    if (!g || !poligonos) return null
    const codificados: number[][][] = []
    for (const poligono of poligonos) {
      const aneis: number[][] = []
      for (const anel of poligono) {
        const d = anelDelta(anel, escala)
        if (!d) return null
        aneis.push(d)
      }
      codificados.push(aneis)
    }
    features.push({ type: "Feature", properties: f.properties, geometry: { type: g.type, delta: g.type === "Polygon" ? codificados[0] : codificados } })
  }
  // delta_1e6 continua como antes (sites e caches já publicados); a escala 1e5 vai explícita.
  return escala === 1e6 ? { type: "FeatureCollection", delta_1e6: true, features } : { type: "FeatureCollection", delta_escala: escala, features }
}

function anelDe(d: number[], escala: number): Anel {
  const anel: Anel = []
  let x = 0, y = 0
  for (let i = 0; i + 1 < d.length; i += 2) {
    x += d[i]
    y += d[i + 1]
    anel.push([x / escala, y / escala])
  }
  return anel
}

/** O que o navegador lê: GeoJSON comum passa direto; o formato em deltas volta a ser GeoJSON. */
export function decodificarGeometria(valor: unknown): Geo {
  const v = valor as { delta_1e6?: boolean; delta_escala?: number; features?: { type: string; properties: Record<string, unknown>; geometry: { type: string; delta?: unknown; coordinates?: unknown } }[] }
  const escala = v?.delta_escala === 1e5 ? 1e5 : v?.delta_1e6 ? 1e6 : null
  if (!escala || !Array.isArray(v.features)) return valor as Geo
  const anel = (d: number[]) => anelDe(d, escala)
  return {
    type: "FeatureCollection",
    features: v.features.map((f) => ({
      type: "Feature" as const,
      properties: f.properties,
      geometry: f.geometry.type === "Polygon"
        ? { type: "Polygon", coordinates: (f.geometry.delta as number[][]).map(anel) }
        : { type: "MultiPolygon", coordinates: (f.geometry.delta as number[][][]).map((p) => p.map(anel)) },
    })),
  } as unknown as Geo
}
