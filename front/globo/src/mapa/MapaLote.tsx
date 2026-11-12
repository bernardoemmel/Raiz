import { AttributionControl, LngLatBounds, Map as MapaGL, NavigationControl, ScaleControl, type ExpressionSpecification, type GeoJSONSource } from "maplibre-gl"
import "maplibre-gl/dist/maplibre-gl.css"
import { useEffect, useRef, useState } from "react"
import { COR, INTERESSE } from "../../../compartilhado/cores"
import type { Geo } from "../../../compartilhado/dados"
import { ORDEM_INTERESSE } from "../../../compartilhado/pedidos/exemplo"
import type { NivelInteresse, PapelNoLote } from "../../../compartilhado/pedidos/tipos"
import { fonte } from "../dados"
import { estiloBase, imagemHachura, imagemListras, prepararMapLibre } from "./estilo"

export interface FazendaNoMapa {
  cod_imovel: string
  cod_ibge: string
  lon: number
  lat: number
  papel: PapelNoLote
  interesse: NivelInteresse
  /** entrou no lugar de outra */
  trocou?: string | null
}

const VAZIO: Geo = { type: "FeatureCollection", features: [] }
const NIVEIS: NivelInteresse[] = [...ORDEM_INTERESSE, "recusou", "sem_resposta"]

/** cor do nível de interesse: código do nível → cor da paleta (cores.ts) */
const COR_INTERESSE = ["match", ["get", "nivel"], ...NIVEIS.flatMap((n, i) => [i, INTERESSE[n]]), COR.nevoa] as unknown as ExpressionSpecification

/** contorno das fazendas de um município, lido uma vez */
const contornos = new Map<string, Promise<Geo | null>>()
const contornoDe = (cod: string) => {
  let p = contornos.get(cod)
  if (!p) {
    p = fonte.geo.camada(cod, "imoveis")
    contornos.set(cod, p)
  }
  return p
}

/**
 * O lote no mapa. Modo "papel": fazenda do lote em verde-escuro, de reserva com listras deitadas (a diagonal é só da
 * área que volta a ser mata). Modo "interesse": cada fazenda na cor do nível de interesse do dono, quem recusou também
 * com a hachura cruzada, e quem entrou no lugar de outra com o contorno urucum. Tocar numa fazenda escolhe ela.
 */
export function MapaLote({
  base,
  fazendas,
  modo,
  escolhida,
  aoEscolher,
}: {
  base: string | null
  fazendas: FazendaNoMapa[]
  modo: "papel" | "interesse"
  escolhida: string | null
  aoEscolher: (cod: string | null) => void
}) {
  const caixa = useRef<HTMLDivElement>(null)
  const mapaRef = useRef<MapaGL | null>(null)
  const [pronto, setPronto] = useState(false)
  const atual = useRef(aoEscolher)
  useEffect(() => {
    atual.current = aoEscolher
  })
  const enquadrado = useRef<string>("")

  useEffect(() => {
    if (!caixa.current) return
    prepararMapLibre()
    const m = new MapaGL({
      container: caixa.current,
      style: estiloBase(base),
      bounds: [-56, -9, -50, -5],
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
      locale: { "NavigationControl.ZoomIn": "Aproximar", "NavigationControl.ZoomOut": "Afastar" },
    })
    m.addControl(new AttributionControl({ compact: false }), "bottom-right")
    m.addControl(new NavigationControl({ showCompass: false }), "top-right")
    m.addControl(new ScaleControl({ unit: "metric" }), "bottom-right")
    if (import.meta.env.DEV) Object.assign(caixa.current, { __mapa: m })
    m.once("style.load", () => {
      m.addImage("listras", imagemListras(COR.mata), { pixelRatio: 2 })
      m.addImage("hachura-cruzada", imagemHachura(COR.pedra, true), { pixelRatio: 2 })
      m.addSource("lote", { type: "geojson", data: VAZIO as never, promoteId: "cod" })
      m.addSource("lote-pontos", { type: "geojson", data: VAZIO as never, promoteId: "cod" })
      const antes = m.getStyle().layers.find((l) => l.type === "symbol")?.id
      m.addLayer({ id: "lote-area", type: "fill", source: "lote", paint: { "fill-color": COR.mata, "fill-opacity": 0.9 } }, antes)
      m.addLayer({ id: "lote-listras", type: "fill", source: "lote", paint: { "fill-pattern": "listras" } }, antes)
      m.addLayer({ id: "lote-recusa", type: "fill", source: "lote", paint: { "fill-pattern": "hachura-cruzada" } }, antes)
      m.addLayer(
        {
          id: "lote-linha",
          type: "line",
          source: "lote",
          paint: {
            "line-color": ["case", ["boolean", ["feature-state", "escolhida"], false], COR.tinta, ["boolean", ["get", "trocou"], false], COR.urucum, COR.mata],
            "line-width": ["case", ["boolean", ["feature-state", "escolhida"], false], 3, ["boolean", ["get", "trocou"], false], 2.5, 1],
          },
        },
        antes,
      )
      // na escala do município a fazenda pequena some: um ponto marca cada uma até o zoom 10
      m.addLayer({
        id: "lote-ponto",
        type: "circle",
        source: "lote-pontos",
        maxzoom: 10,
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, 3, 10, 6],
          "circle-color": COR.mata,
          "circle-stroke-color": ["case", ["boolean", ["get", "trocou"], false], COR.urucum, ["==", ["get", "papel"], 0], COR.mata, COR.superficie],
          "circle-stroke-width": ["case", ["boolean", ["get", "trocou"], false], 2, 1],
        },
      })
      setPronto(true)
    })
    const tocar = (e: { point: { x: number; y: number } }) => {
      const f = m.queryRenderedFeatures([e.point.x, e.point.y], { layers: ["lote-area", "lote-ponto"] })[0]
      atual.current(f ? String(f.properties.cod) : null)
    }
    m.on("click", tocar)
    for (const camada of ["lote-area", "lote-ponto"]) {
      m.on("mouseenter", camada, () => (m.getCanvas().style.cursor = "pointer"))
      m.on("mouseleave", camada, () => (m.getCanvas().style.cursor = ""))
    }
    mapaRef.current = m
    return () => {
      m.remove()
      mapaRef.current = null
    }
  }, [base])

  // as fazendas: contorno de cada uma (do município dela) e o ponto no meio
  useEffect(() => {
    const m = mapaRef.current
    if (!m || !pronto) return
    let vivo = true
    const porCod = new Map(fazendas.map((f) => [f.cod_imovel, f]))
    const props = (f: FazendaNoMapa) => ({
      cod: f.cod_imovel,
      papel: f.papel === "lote" ? 1 : 0,
      nivel: NIVEIS.indexOf(f.interesse),
      recusou: f.interesse === "recusou" ? 1 : 0,
      trocou: !!f.trocou,
    })
    ;(m.getSource("lote-pontos") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features: fazendas.map((f) => ({ type: "Feature", properties: props(f), geometry: { type: "Point", coordinates: [f.lon, f.lat] } })),
    } as never)
    Promise.all([...new Set(fazendas.map((f) => f.cod_ibge))].map(contornoDe)).then((geos) => {
      if (!vivo) return
      const features = geos
        .flatMap((g) => g?.features ?? [])
        .filter((f) => porCod.has(String(f.properties.cod_imovel)))
        .map((f) => ({ ...f, properties: props(porCod.get(String(f.properties.cod_imovel))!) }))
      ;(m.getSource("lote") as GeoJSONSource).setData({ type: "FeatureCollection", features } as never)
      // enquadra o lote quando a lista de fazendas muda de verdade (não a cada atualização do andamento)
      const chave = fazendas.map((f) => f.cod_imovel).sort().join(",")
      if (chave !== enquadrado.current && fazendas.length) {
        enquadrado.current = chave
        const b = new LngLatBounds()
        for (const f of fazendas) b.extend([f.lon, f.lat])
        m.fitBounds(b, { padding: 56, maxZoom: 11, duration: 0 })
      }
    })
    return () => {
      vivo = false
    }
  }, [pronto, fazendas])

  // cor pelo papel (lote ou reserva) ou pelo nível de interesse
  useEffect(() => {
    const m = mapaRef.current
    if (!m || !pronto) return
    if (modo === "papel") {
      m.setPaintProperty("lote-area", "fill-color", ["case", ["==", ["get", "papel"], 1], COR.mata, COR.superficie])
      m.setPaintProperty("lote-listras", "fill-opacity", ["case", ["==", ["get", "papel"], 0], 1, 0])
      m.setPaintProperty("lote-ponto", "circle-color", ["case", ["==", ["get", "papel"], 1], COR.mata, COR.superficie])
      m.setPaintProperty("lote-recusa", "fill-opacity", 0)
    } else {
      m.setPaintProperty("lote-area", "fill-color", COR_INTERESSE)
      m.setPaintProperty("lote-listras", "fill-opacity", 0)
      m.setPaintProperty("lote-ponto", "circle-color", COR_INTERESSE)
      m.setPaintProperty("lote-recusa", "fill-opacity", ["case", ["==", ["get", "recusou"], 1], 0.8, 0])
    }
  }, [pronto, modo])

  // fazenda escolhida: contorno em tinta
  const anterior = useRef<string | null>(null)
  useEffect(() => {
    const m = mapaRef.current
    if (!m || !pronto) return
    if (anterior.current) m.setFeatureState({ source: "lote", id: anterior.current }, { escolhida: false })
    if (escolhida) m.setFeatureState({ source: "lote", id: escolhida }, { escolhida: true })
    anterior.current = escolhida
  }, [pronto, escolhida, fazendas])

  return <div className="mapa mapa-lote" ref={caixa} role="region" aria-label="Mapa do lote: toque numa fazenda para ver a ficha" />
}
