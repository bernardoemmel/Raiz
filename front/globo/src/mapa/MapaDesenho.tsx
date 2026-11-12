import { AttributionControl, Map as MapaGL, NavigationControl, type GeoJSONSource } from "maplibre-gl"
import "maplibre-gl/dist/maplibre-gl.css"
import { useEffect, useRef } from "react"
import { COR } from "../../../compartilhado/cores"
import type { Geo } from "../../../compartilhado/dados"
import { estiloBase, prepararMapLibre } from "./estilo"

/** a Amazônia Legal: onde o mapa abre para desenhar */
const AMAZONIA: [number, number, number, number] = [-74, -18.1, -43.9, 5.3]

/**
 * Desenhar a área do pedido: cada toque marca um canto; o polígono se fecha sozinho a partir de 3 cantos. Sem
 * biblioteca de desenho: um GeoJSON que muda a cada toque.
 */
export function MapaDesenho({ base, pontos, mudar }: { base: string | null; pontos: [number, number][]; mudar: (p: [number, number][]) => void }) {
  const caixa = useRef<HTMLDivElement>(null)
  const mapaRef = useRef<MapaGL | null>(null)
  const atual = useRef({ pontos, mudar })
  useEffect(() => {
    atual.current = { pontos, mudar }
  })

  useEffect(() => {
    if (!caixa.current) return
    prepararMapLibre()
    const m = new MapaGL({
      container: caixa.current,
      style: estiloBase(base),
      bounds: AMAZONIA,
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
      doubleClickZoom: false,
      locale: { "NavigationControl.ZoomIn": "Aproximar", "NavigationControl.ZoomOut": "Afastar" },
    })
    m.addControl(new AttributionControl({ compact: false }), "bottom-right")
    m.addControl(new NavigationControl({ showCompass: false }), "top-right")
    if (import.meta.env.DEV) Object.assign(caixa.current, { __mapa: m })
    m.once("style.load", () => {
      m.addSource("desenho", { type: "geojson", data: { type: "FeatureCollection", features: [] } })
      m.addLayer({ id: "desenho-area", type: "fill", source: "desenho", filter: ["==", ["geometry-type"], "Polygon"], paint: { "fill-color": COR.urucum, "fill-opacity": 0.12 } })
      m.addLayer({ id: "desenho-linha", type: "line", source: "desenho", filter: ["!=", ["geometry-type"], "Point"], paint: { "line-color": COR.urucumTexto, "line-width": 2 } })
      m.addLayer({
        id: "desenho-cantos",
        type: "circle",
        source: "desenho",
        filter: ["==", ["geometry-type"], "Point"],
        paint: { "circle-radius": 5, "circle-color": COR.superficie, "circle-stroke-color": COR.urucumTexto, "circle-stroke-width": 2 },
      })
      desenhar(m, atual.current.pontos)
    })
    m.on("click", (e) => atual.current.mudar([...atual.current.pontos, [round(e.lngLat.lng), round(e.lngLat.lat)]]))
    mapaRef.current = m
    return () => {
      m.remove()
      mapaRef.current = null
    }
  }, [base])

  useEffect(() => {
    const m = mapaRef.current
    if (m?.getSource("desenho")) desenhar(m, pontos)
  }, [pontos])

  return <div className="mapa mapa-desenho" ref={caixa} role="application" aria-label="Mapa para desenhar a área do pedido" />
}

const round = (v: number) => Math.round(v * 1e5) / 1e5

function desenhar(m: MapaGL, pontos: [number, number][]) {
  const features: Geo["features"] = pontos.map((p) => ({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: p } }))
  if (pontos.length >= 3) features.push({ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [[...pontos, pontos[0]]] } })
  else if (pontos.length === 2) features.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: pontos } })
  ;(m.getSource("desenho") as GeoJSONSource).setData({ type: "FeatureCollection", features } as never)
}
