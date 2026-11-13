import type { Geo } from "../../../compartilhado/dados"
import { fmtHa, fmtInt } from "../../../compartilhado/formato"

export interface GrupoMapa {
  chave: string
  centro: [number, number]
  cluster?: number
  fazendas: number
  hectares: number | null
  semMedida: number
}

/** Compatibilidade com publicações anteriores; a projeção normal pronta é lida direto pelo worker. */
export function prepararPontosAgregados(geo?: Geo | null): Geo {
  const vistos = new Set<string>()
  return { type: "FeatureCollection", features: (geo?.features ?? []).flatMap(f => {
    const { h3, fazendas, potencial_ha: ha } = f.properties
    if (f.geometry.type !== "Point" || typeof h3 !== "string" || vistos.has(h3) || !Number.isSafeInteger(fazendas) || Number(fazendas) < 5) return []
    vistos.add(h3)
    return [{ type: "Feature" as const, geometry: f.geometry, properties: {
      h3, fazendas, potencial_ha: typeof ha === "number" && Number.isFinite(ha) && ha > 0 ? ha : null,
    } }]
  }) }
}

/** Defesa adicional: o renderer só entrega ao worker o arquivo público desta mesma publicação. */
export function urlAgregadosPublica(url: string | null | undefined, arquivoEsperado: string): string | null {
  if (!url) return null
  try {
    const esperado = new URL(arquivoEsperado), recebido = new URL(url, esperado)
    return recebido.href === esperado.href && !recebido.username && !recebido.password ? recebido.href : null
  } catch { return null }
}

export function raioGrupo(grupo: GrupoMapa): number {
  return grupo.fazendas >= 100000 ? 56 : grupo.fazendas >= 10000 ? 50 : 44
}

export function rotulosGrupo(grupo: GrupoMapa): [string, string] {
  const ha = grupo.hectares
  return [fmtInt(grupo.fazendas), ha === null ? "Sem medida" : ha < 0.1 ? "<0,1 ha"
    : fmtHa(ha)]
}

export function lerGrupo(f: { properties: Record<string, unknown> | null; geometry: { type: string; coordinates?: unknown } }): GrupoMapa | null {
  const p = f.properties, c = f.geometry.coordinates
  if (!p) return null
  if (f.geometry.type !== "Point" || !Array.isArray(c) || c.length !== 2 || !c.every(n => typeof n === "number" && Number.isFinite(n))) return null
  if (!Number.isSafeInteger(p.fazendas) || Number(p.fazendas) < 5) return null
  const cluster = p.cluster === true && typeof p.cluster_id === "number" ? p.cluster_id : undefined
  const ha = cluster === undefined ? p.potencial_ha : Number(p.com_medida) > 0 ? p.ha_conhecidos : null
  const hectares = typeof ha === "number" && Number.isFinite(ha) && ha > 0 ? ha : null
  return { chave: cluster === undefined ? String(p.h3) : `grupo-${cluster}`, centro: c as [number, number], cluster,
    fazendas: Number(p.fazendas), hectares, semMedida: cluster === undefined ? hectares === null ? 1 : 0 : Number(p.sem_medida) }
}

export function descreverGrupo(grupo: GrupoMapa): string {
  const ha = grupo.hectares === null ? "hectares não informados" : `${grupo.hectares < 0.1 ? "menos de 0,1 ha" : fmtHa(grupo.hectares)} conhecidos`
  return `${fmtInt(grupo.fazendas)} fazendas no agregado, ${ha}. Cobertura parcial.`
}
