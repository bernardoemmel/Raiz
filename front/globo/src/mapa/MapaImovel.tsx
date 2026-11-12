import { AttributionControl, LngLatBounds, Map as MapaGL, NavigationControl, ScaleControl } from "maplibre-gl"
import "maplibre-gl/dist/maplibre-gl.css"
import { useEffect, useRef } from "react"
import type { Geo } from "../../../compartilhado/dados"
import { estiloBase, imagemHachura, prepararMapLibre } from "./estilo"

interface Props {
  aneis: [number, number][][]
  cod: string
  /** divisa do município: contorno no mapa e primeira parada do voo */
  municipio: Geo | null
  /** veio da busca: o mapa sai da vista do Brasil, passa pelo município e pousa na fazenda */
  voar?: boolean
  base: string | null
  vizinhos: Geo | null
  ti: Geo | null
  rios: Geo | null
}

const VAZIO: Geo = { type: "FeatureCollection", features: [] }

/** O imóvel no mapa: perímetro do CAR em destaque, vizinhos em cinza, terras indígenas e rios. */
function limitesDe(g: Geo | null): LngLatBounds | null {
  if (!g?.features.length) return null
  const b = new LngLatBounds()
  const andar = (c: unknown): void => {
    if (Array.isArray(c) && typeof c[0] === "number") b.extend(c as [number, number])
    else if (Array.isArray(c)) c.forEach(andar)
  }
  g.features.forEach((f) => andar(f.geometry.coordinates))
  return b
}

export function MapaImovel({ aneis, cod, municipio, voar, base, vizinhos, ti, rios }: Props) {
  const caixa = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!caixa.current || !aneis.length) return
    prepararMapLibre()
    const b = new LngLatBounds()
    aneis.forEach((a) => a.forEach((p) => b.extend(p)))
    const doMunicipio = limitesDe(municipio)
    const reduzido = matchMedia("(prefers-reduced-motion: reduce)").matches
    const comVoo = !!voar && !reduzido
    const m = new MapaGL({
      container: caixa.current,
      style: estiloBase(base),
      ...(comVoo
        ? { center: (doMunicipio ?? b).getCenter(), zoom: 3.6 }
        : { bounds: b, fitBoundsOptions: { padding: 56, maxZoom: 15 } }),
      attributionControl: false,
      cooperativeGestures: true,
    })
    if (comVoo)
      m.once("idle", () => {
        // Brasil → município → fazenda
        const pousar = () => m.fitBounds(b, { padding: 56, maxZoom: 15, duration: 1800, essential: true })
        if (!doMunicipio) return pousar()
        m.fitBounds(doMunicipio, { padding: 40, duration: 2000, essential: true })
        m.once("moveend", () => setTimeout(pousar, 600))
      })
    m.addControl(new AttributionControl({ compact: true }), "bottom-right")
    m.addControl(new NavigationControl({ showCompass: false }), "top-right")
    m.addControl(new ScaleControl({ unit: "metric" }), "top-left")
    m.once("load", () => caixa.current?.querySelector(".maplibregl-compact-show")?.classList.remove("maplibregl-compact-show"))
    if (import.meta.env.DEV) Object.assign(caixa.current, { __mapa: m })
    m.once("style.load", () => {
      const antes = m.getStyle().layers.find((l) => l.type === "symbol")?.id
      if (!m.hasImage("hachura")) m.addImage("hachura", imagemHachura(), { pixelRatio: 2 })
      const imovel: Geo = {
        type: "FeatureCollection",
        features: [{ type: "Feature", properties: {}, geometry: { type: "MultiPolygon", coordinates: aneis.map((a) => [a]) } }],
      }
      const outros: Geo = {
        type: "FeatureCollection",
        features: (vizinhos?.features ?? []).filter((f) => f.properties.cod_imovel !== cod),
      }
      m.addSource("ti", { type: "geojson", data: (ti ?? VAZIO) as never })
      m.addSource("rios", { type: "geojson", data: (rios ?? VAZIO) as never })
      m.addSource("vizinhos", { type: "geojson", data: outros as never })
      m.addSource("imovel", { type: "geojson", data: imovel as never })
      m.addSource("municipio", { type: "geojson", data: (municipio ?? VAZIO) as never })
      m.addLayer({ id: "ti", type: "fill", source: "ti", paint: { "fill-pattern": "hachura" } }, antes)
      m.addLayer({ id: "rios", type: "fill", source: "rios", paint: { "fill-color": "#86a9cf" } }, antes)
      m.addLayer({ id: "vizinhos", type: "fill", source: "vizinhos", paint: { "fill-color": "#a7aea6", "fill-opacity": 0.22 } }, antes)
      m.addLayer(
        { id: "vizinhos-borda", type: "line", source: "vizinhos", paint: { "line-color": "#ffffff", "line-width": 1 } },
        antes,
      )
      m.addLayer({ id: "municipio", type: "line", source: "municipio", paint: { "line-color": "#1d5a39", "line-width": 1.6, "line-dasharray": [3, 2] } }, antes)
      m.addLayer({ id: "imovel", type: "fill", source: "imovel", paint: { "fill-color": "#1d5a39", "fill-opacity": 0.2 } }, antes)
      m.addLayer({
        id: "imovel-borda",
        type: "line",
        source: "imovel",
        paint: { "line-color": "#1d5a39", "line-width": 3 },
      })
    })
    return () => m.remove()
  }, [aneis, cod, municipio, voar, base, vizinhos, ti, rios])

  return (
    <div className="mapa-caixa mapa-imovel">
      <div className="mapa" ref={caixa} role="region" aria-label="Mapa do imóvel" />
      {!aneis.length && <div className="mapa-carregando">O perímetro deste imóvel ainda não foi baixado.</div>}
      <ul className="legenda">
        <li>
          <i style={{ background: "rgba(29,90,57,.25)", border: "2px solid #1d5a39" }} />
          Perímetro do CAR
        </li>
        <li>
          <i style={{ background: "rgba(167,174,166,.4)" }} />
          Imóveis vizinhos
        </li>
        <li>
          <i style={{ border: "2px dashed #1d5a39" }} />
          Divisa do município
        </li>
        <li>
          <i className="hachura" />
          Terra indígena
        </li>
      </ul>
    </div>
  )
}
