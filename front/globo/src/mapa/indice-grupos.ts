import { Supercluster } from "@maplibre/geojson-vt"
import type { Geo } from "../../../compartilhado/dados"
import { lerGrupo, prepararPontosAgregados, type GrupoMapa } from "./grupos"
import type { CaixaGrupos } from "./protocolo-grupos"

/** Os mesmos parâmetros de GeoJSONSource: extent 8192, tileSize 512 e raio de 112 pixels. */
export const OPCOES_INDICE_GRUPOS = { maxZoom: 11, minPoints: 2, extent: 8192, radius: 112 * 8192 / 512,
  coordinates: "lngLat" as const, wrap: true }

function pontosPublicos(valor: unknown): Geo {
  if (valor === null) return { type: "FeatureCollection", features: [] }
  if (!valor || typeof valor !== "object" || !("type" in valor) || valor.type !== "FeatureCollection"
    || !("features" in valor) || !Array.isArray(valor.features)) throw new Error("Agregados públicos inválidos.")
  const features: Geo["features"] = []
  for (const item of valor.features) {
    if (!item || typeof item !== "object") throw new Error("Agregados públicos inválidos.")
    const { geometry: g, properties: p } = item
    if (item.type !== "Feature" || !g || g.type !== "Point" || !Array.isArray(g.coordinates)
      || g.coordinates.length !== 2 || !g.coordinates.every((n: unknown) => typeof n === "number" && Number.isFinite(n))
      || Math.abs(g.coordinates[0]) > 180 || Math.abs(g.coordinates[1]) > 90 || !p || typeof p !== "object"
      || typeof p.h3 !== "string" || !/^85[0-9a-f]{13}$/.test(p.h3)) throw new Error("Agregados públicos inválidos.")
    // A lista positiva exclui qualquer campo acrescido à publicação, mesmo dentro do worker.
    features.push({ type: "Feature", geometry: { type: "Point", coordinates: [...g.coordinates] },
      properties: { h3: p.h3, fazendas: p.fazendas, potencial_ha: p.potencial_ha } })
  }
  return prepararPontosAgregados({ type: "FeatureCollection", features })
}

/** Vive somente no worker: o JSON inteiro e o índice nunca voltam à interface. */
export class IndiceGrupos {
  private readonly indice: Supercluster

  constructor(dados: unknown) {
    this.indice = new Supercluster({ ...OPCOES_INDICE_GRUPOS,
      map: p => {
        const ha = typeof p?.potencial_ha === "number" && p.potencial_ha > 0 ? p.potencial_ha : 0
        return { fazendas: p?.fazendas, ha_conhecidos: ha, com_medida: ha > 0 ? 1 : 0, sem_medida: ha > 0 ? 0 : 1 }
      },
      reduce: (a, b) => {
        for (const campo of ["fazendas", "ha_conhecidos", "com_medida", "sem_medida"])
          a[campo] = Number(a[campo]) + Number(b[campo])
      },
    })
    this.indice.load(pontosPublicos(dados).features as never)
  }

  consultar(bbox: CaixaGrupos, zoom: number): GrupoMapa[] {
    if (bbox.length !== 4 || !bbox.every(Number.isFinite) || bbox[1] > bbox[3] || !Number.isFinite(zoom))
      throw new Error("Enquadramento dos agregados inválido.")
    if (zoom >= 12) return []
    const grupos = new Map<string, GrupoMapa>()
    for (const feicao of this.indice.getClusters(bbox, Math.max(0, Math.floor(zoom)))) {
      // lerGrupo constrói cada campo do resultado; não devolve propriedades recebidas.
      const grupo = lerGrupo(feicao)
      if (grupo) grupos.set(grupo.chave, grupo)
    }
    return [...grupos.values()].sort((a, b) => b.fazendas - a.fazendas)
  }

  aproximar(cluster: number): number {
    if (!Number.isSafeInteger(cluster) || cluster < 0) throw new Error("Grupo público inválido.")
    return Math.min(12, this.indice.getClusterExpansionZoom(cluster))
  }
}
