import type { ExpressionSpecification, GeoJSONSourceSpecification, LayerSpecification } from "maplibre-gl"
import type { Geo } from "../../../compartilhado/dados"
import { fmtHa, fmtInt } from "../../../compartilhado/formato"
import { ZOOM_IMOVEIS } from "./cartografia"

export const FONTE_GRUPOS = "agregados-nacionais"
export const CAMADA_GRUPOS = "grupos-fazendas"
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

const HA_PONTO: ExpressionSpecification = ["coalesce", ["get", "potencial_ha"], 0]
const COM_MEDIDA_PONTO: ExpressionSpecification = ["case", [">", HA_PONTO, 0], 1, 0]

/** Supercluster do MapLibre roda no worker; não há segundo índice no thread da interface. */
export function fonteGrupos(): GeoJSONSourceSpecification {
  return { type: "geojson", data: { type: "FeatureCollection", features: [] }, cluster: true,
    clusterRadius: 112, clusterMaxZoom: ZOOM_IMOVEIS - 1, clusterMinPoints: 2,
    // Zero é só a identidade da soma; com_medida preserva a ausência de hectares no resultado.
    clusterProperties: { fazendas: ["+", ["get", "fazendas"]], ha_conhecidos: ["+", HA_PONTO],
      com_medida: ["+", COM_MEDIDA_PONTO], sem_medida: ["+", ["-", 1, COM_MEDIDA_PONTO]] },
  }
}

/** A camada mantém a consulta espacial; os botões visíveis dispensam o programa gráfico de círculos. */
export function camadasGrupos(): LayerSpecification[] {
  return [{ id: CAMADA_GRUPOS, type: "circle", source: FONTE_GRUPOS, maxzoom: ZOOM_IMOVEIS,
    paint: { "circle-opacity": 0, "circle-stroke-opacity": 0,
      "circle-radius": ["step", ["get", "fazendas"], 44, 10000, 50, 100000, 56] } }]
}

export function raioGrupo(grupo: GrupoMapa): number {
  return grupo.fazendas >= 100000 ? 56 : grupo.fazendas >= 10000 ? 50 : 44
}

export function rotulosGrupo(grupo: GrupoMapa): [string, string] {
  const ha = grupo.hectares
  return [fmtInt(grupo.fazendas), ha === null ? "Sem medida" : ha < 0.1 ? "<0,1 ha"
    : `${ha.toLocaleString("pt-BR", { maximumFractionDigits: ha >= 10 ? 0 : 1 })} ha`]
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
