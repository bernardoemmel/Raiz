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
  type StyleSpecification,
} from "maplibre-gl"
import "maplibre-gl/dist/maplibre-gl.css"
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url"
import { Protocol } from "pmtiles"
import { COR } from "../../compartilhado/cores"
import { ATRIBUICAO_MAPA, CORES_MAPA } from "../../compartilhado/mapa-cores"

const SABOR: Flavor = { ...namedFlavor("light"), ...CORES_MAPA, landcover: { ...CORES_MAPA.landcover } }

function estilo(base: string | null): StyleSpecification {
  // as chaves {fontstack} e {range} não podem passar por new URL (viram %7B)
  const glyphs = new URL(import.meta.env.BASE_URL + "geo/fontes/", location.href).href + "{fontstack}/{range}.pbf"
  if (!base)
    return { version: 8, glyphs, sources: {}, layers: [{ id: "fundo", type: "background", paint: { "background-color": CORES_MAPA.earth } }] }
  return {
    version: 8,
    glyphs,
    sources: { protomaps: { type: "vector", url: "pmtiles://" + base, attribution: ATRIBUICAO_MAPA } },
    layers: layers("protomaps", SABOR, { lang: "pt" }).filter(
      (l) => l.id !== "pois" && !l.id.startsWith("address") && !(l.type === "symbol" && l.layout && "icon-image" in l.layout),
    ),
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
    m.addLayer({ id: "fazenda", type: "fill", source: "fazenda", paint: { "fill-color": COR.mata, "fill-opacity": 0.2 } })
    m.addLayer({ id: "fazenda-borda", type: "line", source: "fazenda", paint: { "line-color": COR.tinta, "line-width": 3 } })
  })
  return m
}
