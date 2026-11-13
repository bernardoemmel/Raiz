import type { Geo } from "./tipos"

export interface PotencialMapa {
  geo: Geo
  metadados: { resolucao: number; dominio_ha: number[]; atualizado_em: string | null; fonte: string; metodo: string; aviso: string }
}
const registro = (v: unknown): Record<string, unknown> => v && typeof v === "object" && !Array.isArray(v) ? v as Record<string, unknown> : {}

/** Não reconstrói potencial por imóvel. Só aceita células previamente agregadas com pelo menos cinco fazendas. */
export function lerPotencialMapa(valor: unknown): PotencialMapa | null {
  const v = registro(valor), m = registro(v.metadados)
  if (v.type !== "FeatureCollection" || !Array.isArray(v.features) || m.contrato !== "potencial_h3" || m.versao !== 1 || m.resolucao !== 5 || m.minimo_contribuintes !== 5 || m.cobertura !== "parcial" || m.metodo !== "ponto_interior_estatistico") return null
  const porH3 = new Map<string, Geo["features"][number]>()
  for (const item of v.features) {
    const f = registro(item), p = registro(f.properties), g = registro(f.geometry)
    if (f.type !== "Feature" || typeof p.h3 !== "string" || !/^[0-9a-f]{15}$/.test(p.h3)
      || !Number.isInteger(p.fazendas) || Number(p.fazendas) < 5 || g.type !== "Polygon" || !Array.isArray(g.coordinates)) continue
    const potencial = typeof p.potencial_ha === "number" && Number.isFinite(p.potencial_ha) && p.potencial_ha >= 0 ? p.potencial_ha : null
    porH3.set(p.h3, { type: "Feature", properties: { h3: p.h3, potencial_ha: potencial, fazendas: p.fazendas }, geometry: g as unknown as Geo["features"][number]["geometry"] })
  }
  return { geo: { type: "FeatureCollection", features: [...porH3.values()] }, metadados: {
    resolucao: typeof m.resolucao === "number" ? m.resolucao : 5, dominio_ha: [0, 100, 1000, 10000, 50000],
    atualizado_em: typeof m.atualizado_em === "string" && Number.isFinite(Date.parse(m.atualizado_em)) ? m.atualizado_em : null,
    fonte: typeof m.fonte === "string" ? m.fonte : "Motor da Raíz, projeção agregada",
    metodo: "ponto_interior_estatistico", aviso: "Potencial conhecido, com cobertura parcial: agrega somente áreas conhecidas e sem sobreposição, em células com pelo menos cinco contribuintes. Fazendas sem medida ou com sobreposição permanecem no cadastro, fora desta soma. A posição da célula não desenha a área que pode virar mata. Ausência não é zero.",
  } }
}
