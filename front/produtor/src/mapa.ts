/**
 * O mapa da ficha leve: só é baixado quando o produtor toca em "ver no mapa" (import dinâmico). MapLibre GL JS lê o
 * mapa base do município em PMTiles por faixas de bytes, sem servidor de mapa.
 */

import { layers, namedFlavor, type Flavor } from "@protomaps/basemaps"
import {
  addProtocol,
  AttributionControl,
  LngLatBounds,
  Map as MapaGL,
  NavigationControl,
  ScaleControl,
  setWorkerUrl,
  type LayerSpecification,
  type StyleSpecification,
} from "maplibre-gl"
import "maplibre-gl/dist/maplibre-gl.css"
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url"
import { Protocol } from "pmtiles"
import { COR, MAPA } from "../../compartilhado/cores"
import { CORES_MAPA, FILTRO_PAISES } from "../../compartilhado/mapa-cores"
import { fonteMapaBase } from "../../compartilhado/mapa-base"

const SABOR: Flavor = { ...namedFlavor("white"), ...CORES_MAPA, landcover: { ...CORES_MAPA.landcover } }

/** O mesmo acabamento do painel (guia, item 2.1): nomes de cidade sem ícone, rio com largura por zoom, halo de 1,5 px. */
function camadas(): LayerSpecification[] {
  return layers("protomaps", SABOR, { lang: "pt" }).flatMap((l): LayerSpecification[] => {
    if (l.id === "pois" || l.id.startsWith("address") || l.id === "buildings") return []
    if (l.id === "places_country") l = { ...l, filter: FILTRO_PAISES } as unknown as LayerSpecification
    if (l.type === "symbol" && l.layout && "icon-image" in l.layout) {
      if (l.id !== "places_locality") return []
      const layout = Object.fromEntries(Object.entries(l.layout).filter(([k]) => !k.startsWith("icon-")))
      return [{ ...l, layout } as LayerSpecification]
    }
    if (l.id === "water_river" || l.id === "water_stream")
      return [{ ...l, paint: { "line-color": MAPA.rio, "line-width": ["interpolate", ["linear"], ["zoom"], 8, 0.6, 12, 1.4, 15, 3] } } as LayerSpecification]
    if (l.type === "symbol" && l.paint && "text-halo-width" in l.paint) return [{ ...l, paint: { ...l.paint, "text-halo-width": 1.5 } } as LayerSpecification]
    return [l]
  })
}

function estilo(base: string | null): StyleSpecification {
  // as chaves {fontstack} e {range} não podem passar por new URL (viram %7B)
  const glyphs = new URL(import.meta.env.BASE_URL + "geo/fontes/", location.href).href + "{fontstack}/{range}.pbf"
  if (!base)
    return { version: 8, glyphs, sources: {}, layers: [{ id: "fundo", type: "background", paint: { "background-color": CORES_MAPA.earth } }] }
  return {
    version: 8,
    glyphs,
    sources: { protomaps: fonteMapaBase(base) },
    layers: camadas(),
  }
}

let pronto = false

export function montarMapa(caixa: HTMLElement, aneis: [number, number][][], base: string | null) {
  if (!pronto) {
    pronto = true
    setWorkerUrl(workerUrl)
    addProtocol("pmtiles", new Protocol().tile)
  }
  const limites = new LngLatBounds()
  aneis.forEach((a) => a.forEach((p) => limites.extend(p)))
  const m = new MapaGL({
    container: caixa,
    style: estilo(base),
    bounds: limites,
    fitBoundsOptions: { padding: 32, maxZoom: 15 },
    attributionControl: false,
    dragRotate: false,
    pitchWithRotate: false,
  })
  m.addControl(new AttributionControl({ compact: true }), "bottom-right")
  m.addControl(new NavigationControl({ showCompass: false }), "top-right")
  m.addControl(new ScaleControl({ unit: "metric" }), "top-left")
  m.once("load", () => {
    caixa.querySelector(".maplibregl-compact-show")?.classList.remove("maplibregl-compact-show")
    // um pouco mais longe que o contorno, para aparecer o que fica em volta (estrada, rio, cidade)
    m.easeTo({ zoom: m.getZoom() - 1.3, duration: 600 })
  })
  m.once("style.load", () => {
    m.addSource("fazenda", {
      type: "geojson",
      data: { type: "Feature", properties: {}, geometry: { type: "MultiPolygon", coordinates: aneis.map((a) => [a]) } },
    })
    m.addLayer({ id: "fazenda", type: "fill", source: "fazenda", paint: { "fill-color": COR.mata, "fill-opacity": 0.12 } })
    // contorno duplo: branco por fora, tinta por dentro (guia, item 2.1, parte 5)
    m.addLayer({ id: "fazenda-fora", type: "line", source: "fazenda", paint: { "line-color": MAPA.contornoFora, "line-width": 6, "line-opacity": 0.9 } })
    m.addLayer({ id: "fazenda-borda", type: "line", source: "fazenda", paint: { "line-color": MAPA.contornoClaro, "line-width": 2.5 } })
  })
  return m
}
