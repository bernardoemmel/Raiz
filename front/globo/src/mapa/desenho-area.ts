import type { Geo } from "../../../compartilhado/dados"

export function poligonoDesenhado(pontos: readonly [number, number][]): Geo | null {
  if (pontos.length < 3 || new Set(pontos.map(p => p.join(","))).size < 3) return null
  if (pontos.some(p => !p.every(Number.isFinite) || p[0] < -180 || p[0] > 180 || p[1] < -85 || p[1] > 85)) return null
  // Rejeita cantos colineares: o pedido precisa de área, não de uma linha.
  const area = pontos.reduce((a, p, i) => { const q = pontos[(i + 1) % pontos.length]; return a + p[0] * q[1] - q[0] * p[1] }, 0)
  if (Math.abs(area) < 1e-12) return null
  return { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [[...pontos, pontos[0]]] } }] }
}

export function desenhoDePontos(pontos: readonly [number, number][]): Geo {
  const features: Geo["features"] = pontos.map(p => ({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: p } }))
  const area = poligonoDesenhado(pontos)
  if (area) features.push(...area.features)
  else if (pontos.length > 1) features.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: pontos } })
  return { type: "FeatureCollection", features }
}
