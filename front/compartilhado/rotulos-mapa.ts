/**
 * Nomes por cima das áreas sem imóvel do CAR no mapa (terra indígena e unidade de conservação): um ponto por área,
 * dentro dela, com o nome escrito como gente escreve ("Parque Estadual do Xingu", não "PARQUE ESTADUAL DO XINGU").
 */

import type { Geo } from "./dados"

type Ponto = [number, number]
type Anel = Ponto[]

const MINUSCULAS = new Set(["de", "da", "do", "das", "dos", "e", "a", "o", "em", "na", "no"])

/** "ÁREA DE PROTEÇÃO AMBIENTAL TRIUNFO DO XINGU" → "Área de Proteção Ambiental Triunfo do Xingu". Já escrito certo, fica. */
export function nomeProprio(s: string): string {
  const t = s.trim().replace(/\s+/g, " ")
  if (t !== t.toUpperCase()) return t
  return t
    .toLowerCase()
    .split(" ")
    .map((p, i) => (i > 0 && MINUSCULAS.has(p) ? p : p.replace(/(^|[-/])(\p{L})/gu, (_, a: string, b: string) => a + b.toUpperCase())))
    .join(" ")
}

const areaAnel = (a: Anel) => Math.abs(a.reduce((s, [x, y], i) => s + (a[(i + 1) % a.length][0] - x) * (a[(i + 1) % a.length][1] + y), 0) / 2)

/**
 * Um ponto dentro do polígono (o maior pedaço, quando são vários): corta o pedaço com linhas horizontais e fica no
 * meio do trecho mais largo que cai dentro. Respeita buracos. Sem dependência e rápido o bastante para dezenas de áreas.
 */
export function pontoDentro(geometria: Geo["features"][number]["geometry"]): Ponto | null {
  const poligonos: Anel[][] =
    geometria.type === "Polygon"
      ? [geometria.coordinates as Anel[]]
      : geometria.type === "MultiPolygon"
        ? (geometria.coordinates as Anel[][])
        : []
  if (!poligonos.length) return null
  const maior = poligonos.reduce((a, b) => (areaAnel(b[0]) > areaAnel(a[0]) ? b : a))
  const ys = maior[0].map((p) => p[1])
  const y0 = Math.min(...ys)
  const y1 = Math.max(...ys)
  let melhor: { x: number; y: number; largura: number } | null = null
  for (const f of [0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8]) {
    const y = y0 + (y1 - y0) * f
    const xs: number[] = []
    for (const anel of maior)
      for (let i = 0; i < anel.length - 1; i++) {
        const [ax, ay] = anel[i]
        const [bx, by] = anel[i + 1]
        if (ay > y !== by > y) xs.push(ax + ((y - ay) * (bx - ax)) / (by - ay))
      }
    xs.sort((a, b) => a - b)
    for (let i = 0; i + 1 < xs.length; i += 2) {
      const largura = xs[i + 1] - xs[i]
      if (!melhor || largura > melhor.largura) melhor = { x: (xs[i] + xs[i + 1]) / 2, y, largura }
    }
  }
  return melhor ? [melhor.x, melhor.y] : null
}

/** Pontos com o rótulo de cada terra indígena e unidade de conservação. */
export function rotulosDeAreas(ti: Geo | null | undefined, uc: Geo | null | undefined): Geo {
  const features: Geo["features"] = []
  const juntar = (g: Geo | null | undefined, rotulo: (p: Record<string, unknown>) => string | null) => {
    for (const f of g?.features ?? []) {
      const texto = rotulo(f.properties)
      const ponto = texto ? pontoDentro(f.geometry) : null
      if (texto && ponto) features.push({ type: "Feature", properties: { rotulo: texto }, geometry: { type: "Point", coordinates: ponto } })
    }
  }
  juntar(ti, (p) => (p.nome ? `Terra indígena ${nomeProprio(String(p.nome))}` : "Terra indígena"))
  juntar(uc, (p) => (p.nome ? nomeProprio(String(p.nome)) : "Unidade de conservação"))
  return { type: "FeatureCollection", features }
}
