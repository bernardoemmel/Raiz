import type { GeoJSONSourceSpecification, LayerSpecification } from "maplibre-gl"
import type { Geo } from "../../../compartilhado/dados"
import { COR } from "../../../compartilhado/cores"
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

/** O zero interno é só a identidade da soma; com_medida impede apresentá-lo como dado conhecido. */
export function prepararPontosAgregados(geo?: Geo | null): Geo {
  const vistos = new Set<string>()
  return { type: "FeatureCollection", features: (geo?.features ?? []).flatMap(f => {
    const { h3, fazendas, potencial_ha: ha } = f.properties
    if (f.geometry.type !== "Point" || typeof h3 !== "string" || vistos.has(h3) || !Number.isSafeInteger(fazendas) || Number(fazendas) < 5) return []
    vistos.add(h3)
    const medida = typeof ha === "number" && Number.isFinite(ha) && ha > 0
    return [{ type: "Feature" as const, geometry: f.geometry, properties: {
      h3, fazendas, ha_conhecidos: medida ? ha : 0, com_medida: medida ? 1 : 0, sem_medida: medida ? 0 : 1,
    } }]
  }) }
}

/** Supercluster do MapLibre roda no worker; não há segundo índice no thread da interface. */
export function fonteGrupos(): GeoJSONSourceSpecification {
  return { type: "geojson", data: { type: "FeatureCollection", features: [] }, cluster: true,
    clusterRadius: 112, clusterMaxZoom: ZOOM_IMOVEIS - 1, clusterMinPoints: 2,
    clusterProperties: Object.fromEntries(["fazendas", "ha_conhecidos", "com_medida", "sem_medida"].map(c => [c, ["+", ["get", c]]])),
  }
}

export function camadasGrupos(): LayerSpecification[] {
  return [
    { id: CAMADA_GRUPOS, type: "circle", source: FONTE_GRUPOS, maxzoom: ZOOM_IMOVEIS,
      paint: { "circle-color": COR.mata, "circle-stroke-color": COR.superficie, "circle-stroke-width": 2,
        "circle-radius": ["step", ["get", "fazendas"], 44, 10000, 50, 100000, 56] } },
    { id: "grupos-numeros", type: "symbol", source: FONTE_GRUPOS, maxzoom: ZOOM_IMOVEIS,
      layout: { "text-font": ["Noto Sans Regular"], "text-size": 16, "text-line-height": 1.25,
        "text-allow-overlap": true, "text-field": ["concat",
          ["number-format", ["get", "fazendas"], { locale: "pt-BR", "max-fraction-digits": ["literal", 0] }], "\n",
          ["case", ["==", ["get", "com_medida"], 0], "Sem medida",
            ["<", ["get", "ha_conhecidos"], 0.1], "<0,1 ha",
            ["concat", ["case", [">=", ["get", "ha_conhecidos"], 10],
              ["number-format", ["get", "ha_conhecidos"], { locale: "pt-BR", "max-fraction-digits": ["literal", 0] }],
              ["number-format", ["get", "ha_conhecidos"], { locale: "pt-BR", "max-fraction-digits": 1 }]], " ha"]],
        ] }, paint: { "text-color": COR.superficie } },
  ]
}

export function lerGrupo(f: { properties: Record<string, unknown>; geometry: { type: string; coordinates?: unknown } }): GrupoMapa | null {
  const p = f.properties, c = f.geometry.coordinates
  if (f.geometry.type !== "Point" || !Array.isArray(c) || c.length !== 2 || !c.every(n => typeof n === "number" && Number.isFinite(n))) return null
  if (!Number.isSafeInteger(p.fazendas) || Number(p.fazendas) < 5) return null
  const cluster = p.cluster === true && typeof p.cluster_id === "number" ? p.cluster_id : undefined
  return { chave: cluster === undefined ? String(p.h3) : `grupo-${cluster}`, centro: c as [number, number], cluster,
    fazendas: Number(p.fazendas), hectares: Number(p.com_medida) > 0 ? Number(p.ha_conhecidos) : null, semMedida: Number(p.sem_medida) }
}

export function descreverGrupo(grupo: GrupoMapa): string {
  const ha = grupo.hectares === null ? "hectares não informados" : `${grupo.hectares < 0.1 ? "menos de 0,1 ha" : fmtHa(grupo.hectares)} conhecidos`
  return `${fmtInt(grupo.fazendas)} fazendas no agregado, ${ha}. Cobertura parcial.`
}
