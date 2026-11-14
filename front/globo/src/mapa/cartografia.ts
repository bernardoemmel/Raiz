/** Regras do mapa de levantamento: potencial agregado de longe, limites transparentes de perto. */
import type { ExpressionSpecification, LayerSpecification } from "maplibre-gl"
import { COR, COR_MAPA_V2 } from "../../../compartilhado/cores"
import type { Geo } from "../../../compartilhado/dados"

export const ZOOM_IMOVEIS = 9

/** Área em coordenadas usada somente para ordenar o desenho, nunca apresentada como hectares. */
function areaAnel(anel: number[][]): number {
  let dobro = 0
  for (let i = 0; i < anel.length; i++) {
    const a = anel[i], b = anel[(i + 1) % anel.length]
    dobro += a[0] * b[1] - b[0] * a[1]
  }
  return Math.abs(dobro) / 2
}
function areaPoligono(aneis: number[][][]): number {
  return Math.max(0, (aneis[0] ? areaAnel(aneis[0]) : 0) - aneis.slice(1).reduce((s, a) => s + areaAnel(a), 0))
}

export function ordenarImoveis(geo: Geo | null | undefined): Geo {
  return { type: "FeatureCollection", features: (geo?.features ?? []).map((f) => {
    const area = f.geometry.type === "Polygon" ? areaPoligono(f.geometry.coordinates as number[][][])
      : f.geometry.type === "MultiPolygon" ? (f.geometry.coordinates as number[][][][]).reduce((s, p) => s + areaPoligono(p), 0) : 0
    return { ...f, properties: { ...f.properties, ordem_desenho: -area } }
  }).sort((a, b) => Number(a.properties.ordem_desenho) - Number(b.properties.ordem_desenho)) }
}

export function camadasImoveis(): LayerSpecification[] {
  const apagada: ExpressionSpecification = ["in", ["coalesce", ["feature-state", "g"], -1], ["literal", [-1, 2, 3]]]
  const cor: ExpressionSpecification = ["interpolate", ["linear"], ["zoom"],
    11, ["case", ["boolean", ["feature-state", "pendenciaFiltrada"], false], COR_MAPA_V2.acao, COR_MAPA_V2.rotulo],
    12, ["case", ["boolean", ["feature-state", "pendenciaFiltrada"], false], COR_MAPA_V2.acao, COR.tinta]]
  return [
    // O preenchimento transparente permite tocar no interior, sem pintar ou acumular cor em sobreposições.
    { id: "imoveis", type: "fill", source: "imoveis", minzoom: ZOOM_IMOVEIS,
      layout: { "fill-sort-key": ["get", "ordem_desenho"] }, paint: { "fill-color": COR.tinta, "fill-opacity": 0 } },
    { id: "imoveis-linha", type: "line", source: "imoveis", minzoom: ZOOM_IMOVEIS,
      filter: ["!=", ["get", "sobreposto"], true],
      layout: { "line-sort-key": ["get", "ordem_desenho"] },
      paint: { "line-color": cor,
        "line-width": 1, "line-opacity": ["case", apagada, 0.12, 0.8] } } as LayerSpecification,
    { id: "imoveis-sobrepostos", type: "line", source: "imoveis", minzoom: ZOOM_IMOVEIS,
      filter: ["==", ["get", "sobreposto"], true], layout: { "line-sort-key": ["get", "ordem_desenho"] },
      paint: { "line-color": cor, "line-width": 1, "line-dasharray": [3, 3], "line-opacity": ["case", apagada, 0.12, 0.8] } },
    { id: "imoveis-destaque", type: "line", source: "imoveis", minzoom: ZOOM_IMOVEIS,
      paint: { "line-color": COR_MAPA_V2.destaque, "line-width": 2.5,
        "line-opacity": ["case", ["any", ["boolean", ["feature-state", "destaque"], false], ["boolean", ["feature-state", "sobre"], false], ["boolean", ["feature-state", "selecionado"], false]], 1, 0] } },
  ]
}
