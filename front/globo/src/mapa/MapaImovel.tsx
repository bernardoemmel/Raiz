import { AttributionControl, LngLatBounds, Map as MapaGL, NavigationControl, ScaleControl } from "maplibre-gl"
import "maplibre-gl/dist/maplibre-gl.css"
import { useEffect, useRef } from "react"
import { camposDeFutebol } from "../../../compartilhado/comparacoes"
import { COR, MAPA } from "../../../compartilhado/cores"
import type { Geo } from "../../../compartilhado/dados"
import { fmtHa } from "../../../compartilhado/formato"
import { MiniBrasil } from "../partes/MiniBrasil"
import { estiloBase, imagemHachura, prepararMapLibre } from "./estilo"

interface Props {
  aneis: [number, number][][]
  cod: string
  /** área do imóvel, para a escala de leigo embaixo do mapa */
  ha: number
  uf: string
  municipioNome: string
  /** divisa do município: contorno no mapa e ponto de partida do voo */
  municipio: Geo | null
  /** veio da busca: o mapa sai do município e pousa na fazenda */
  voar?: boolean
  base: string | null
  vizinhos: Geo | null
  ti: Geo | null
  rios: Geo | null
}

const VAZIO: Geo = { type: "FeatureCollection", features: [] }

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

/**
 * O imóvel no mapa (guia, item 2.1): máscara fora do imóvel, contorno duplo, vizinhos só com contorno fino a partir do
 * zoom 12, terras indígenas em hachura e rios. A imagem de satélite da fazenda entra no lugar do mapa base quando o
 * back-end gerar (GET /imoveis/{cod}/imagem/hoje.webp); enquanto isso, a base clara.
 */
export function MapaImovel({ aneis, cod, ha, uf, municipioNome, municipio, voar, base, vizinhos, ti, rios }: Props) {
  const caixa = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!caixa.current || !aneis.length) return
    prepararMapLibre()
    const b = new LngLatBounds()
    aneis.forEach((a) => a.forEach((p) => b.extend(p)))
    const doMunicipio = limitesDe(municipio)
    const reduzido = matchMedia("(prefers-reduced-motion: reduce)").matches
    const comVoo = !!voar && !reduzido && !!doMunicipio
    const m = new MapaGL({
      container: caixa.current,
      style: estiloBase(base),
      bounds: comVoo ? doMunicipio! : b,
      fitBoundsOptions: { padding: 48, maxZoom: 15 },
      attributionControl: false,
      cooperativeGestures: true,
      pixelRatio: Math.min(window.devicePixelRatio || 1, 2),
      fadeDuration: 150,
      dragRotate: false,
      pitchWithRotate: false,
    })
    m.addControl(new AttributionControl({ compact: false }), "bottom-right")
    m.addControl(new NavigationControl({ showCompass: false }), "top-right")
    m.addControl(new ScaleControl({ unit: "metric" }), "bottom-right")
    if (import.meta.env.DEV) Object.assign(caixa.current, { __mapa: m })
    m.once("style.load", () => {
      const antes = m.getStyle().layers.find((l) => l.type === "symbol")?.id
      if (!m.hasImage("hachura")) m.addImage("hachura", imagemHachura(), { pixelRatio: 2 })
      const imovel: Geo = {
        type: "FeatureCollection",
        features: [{ type: "Feature", properties: {}, geometry: { type: "MultiPolygon", coordinates: aneis.map((a) => [a]) } }],
      }
      const mundo = [
        [-180, -85],
        [180, -85],
        [180, 85],
        [-180, 85],
        [-180, -85],
      ]
      const fora: Geo = {
        type: "FeatureCollection",
        features: [{ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [mundo, ...aneis] } }],
      }
      const outros: Geo = { type: "FeatureCollection", features: (vizinhos?.features ?? []).filter((f) => f.properties.cod_imovel !== cod) }
      m.addSource("ti", { type: "geojson", data: (ti ?? VAZIO) as never })
      m.addSource("rios", { type: "geojson", data: (rios ?? VAZIO) as never })
      m.addSource("vizinhos", { type: "geojson", data: outros as never })
      m.addSource("imovel", { type: "geojson", data: imovel as never })
      m.addSource("fora", { type: "geojson", data: fora as never })
      m.addSource("municipio", { type: "geojson", data: (municipio ?? VAZIO) as never })
      const acesa = comVoo ? 0 : 1
      m.addLayer({ id: "ti", type: "fill", source: "ti", paint: { "fill-pattern": "hachura", "fill-opacity": 0.5 } }, antes)
      m.addLayer({ id: "rios", type: "fill", source: "rios", paint: { "fill-color": MAPA.agua } }, antes)
      m.addLayer({ id: "municipio", type: "line", source: "municipio", maxzoom: 11, paint: { "line-color": COR.tinta, "line-width": 1.5 } }, antes)
      // máscara fora do imóvel (vizinhos continuam visíveis, apagados)
      m.addLayer(
        {
          id: "fora",
          type: "fill",
          source: "fora",
          paint: { "fill-color": MAPA.mascaraClara, "fill-opacity": 0.6 * acesa, "fill-opacity-transition": { duration: 280 } },
        },
        antes,
      )
      // vizinhos do CAR: só contorno fino, a partir do zoom 12
      m.addLayer(
        { id: "vizinhos", type: "line", source: "vizinhos", minzoom: 12, paint: { "line-color": COR.pedra, "line-width": 0.8, "line-opacity": 0.7 } },
        antes,
      )
      // contorno duplo: branco de 6 px por fora e tinta de 2,5 px por dentro (sobre a base clara)
      m.addLayer({
        id: "imovel-fora",
        type: "line",
        source: "imovel",
        paint: { "line-color": MAPA.contornoFora, "line-width": 6, "line-opacity": 0.9 * acesa, "line-opacity-transition": { duration: 280 } },
      })
      m.addLayer({
        id: "imovel-dentro",
        type: "line",
        source: "imovel",
        paint: { "line-color": MAPA.contornoClaro, "line-width": 2.5, "line-opacity": acesa, "line-opacity-transition": { duration: 280 } },
      })
      if (comVoo)
        m.once("idle", () => {
          // do município à fazenda; só depois do moveend acende a máscara e o contorno (guia, item 3.2)
          m.fitBounds(b, { padding: 48, maxZoom: 15, duration: 1100 })
          m.once("moveend", () => {
            m.setPaintProperty("fora", "fill-opacity", 0.6)
            m.setPaintProperty("imovel-fora", "line-opacity", 0.9)
            m.setPaintProperty("imovel-dentro", "line-opacity", 1)
          })
        })
    })
    return () => m.remove()
  }, [aneis, cod, municipio, voar, base, vizinhos, ti, rios])

  let x0 = Infinity,
    y0 = Infinity,
    x1 = -Infinity,
    y1 = -Infinity
  for (const a of aneis)
    for (const [x, y] of a) {
      x0 = Math.min(x0, x)
      x1 = Math.max(x1, x)
      y0 = Math.min(y0, y)
      y1 = Math.max(y1, y)
    }
  const centro = Number.isFinite(x0) ? { lon: (x0 + x1) / 2, lat: (y0 + y1) / 2 } : { lon: null, lat: null }

  return (
    <figure className="mapa-figura">
      <div className="mapa-caixa mapa-imovel">
        <div className="mapa" ref={caixa} role="region" aria-label="Mapa do imóvel" />
        {!aneis.length && <div className="mapa-carregando">O perímetro deste imóvel ainda não foi baixado.</div>}
        <MiniBrasil uf={uf} lon={centro.lon} lat={centro.lat} titulo={`Fica em ${municipioNome}`} />
        <ul className="legenda">
          <li>
            <i className="imovel-duplo" />
            Limite do imóvel no CAR
          </li>
          <li>
            <i className="vizinho-linha" />
            Imóveis vizinhos
          </li>
          <li>
            <i className="hachura" />
            Terra indígena
          </li>
        </ul>
      </div>
      <figcaption className="mapa-legenda-fixa">
        <span>
          {fmtHa(ha)}, do tamanho de {camposDeFutebol(ha).replace(/^são |^é /, "")}.
        </span>
        <span>Limites do CAR são declarados pelo dono e podem ter erro.</span>
      </figcaption>
    </figure>
  )
}
