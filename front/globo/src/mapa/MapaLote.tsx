import { AttributionControl, Map as MapaGL, NavigationControl, ScaleControl, type ExpressionSpecification, type GeoJSONSource } from "maplibre-gl"
import "maplibre-gl/dist/maplibre-gl.css"
import { useEffect, useRef, useState } from "react"
import { COR, INTERESSE } from "../../../compartilhado/cores"
import type { Geo } from "../../../compartilhado/dados"
import type { IdOpcao, NivelInteresse } from "../../../compartilhado/pedidos/tipos"
import { estiloBase, imagemHachura, imagemListras, prepararMapLibre } from "./estilo"
import { coordenadaValida, geometriasDosLotes, limitesDoLote, propriedadesDaFazenda, type FazendaNoMapa } from "./lotes"
export type { FazendaNoMapa } from "./lotes"

const VAZIO: Geo = { type: "FeatureCollection", features: [] }
const NIVEIS = Object.keys(INTERESSE) as NivelInteresse[]
const CORES_OPCOES: Record<IdOpcao, string> = { barata: COR.mata, segura: COR.agua, compacta: COR.terra }
const IDS_OPCOES: IdOpcao[] = ["barata", "segura", "compacta"]
const COR_OPCAO = ["match", ["get", "opcao"], ...IDS_OPCOES.flatMap((id) => [id, CORES_OPCOES[id]]), COR.mata] as unknown as ExpressionSpecification

/** cor do nível de interesse: código do nível → cor da paleta (cores.ts) */
const COR_INTERESSE = ["match", ["get", "interesse"], ...NIVEIS.flatMap((n) => [n, INTERESSE[n]]), COR.nevoa] as unknown as ExpressionSpecification

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
  aoEscolherOpcao,
  opcaoAtiva,
  carregarContorno,
}: {
  base: string | null
  fazendas: FazendaNoMapa[]
  modo: "papel" | "interesse" | "opcoes"
  escolhida: string | null
  aoEscolher: (cod: string | null) => void
  aoEscolherOpcao?: (opcao: IdOpcao) => void
  opcaoAtiva?: IdOpcao
  /** Somente fonte autorizada para os CARs do pedido. Não usar os agregados do mapa público. */
  carregarContorno?: (codIbge: string) => Promise<Geo | null>
}) {
  const caixa = useRef<HTMLDivElement>(null)
  const mapaRef = useRef<MapaGL | null>(null)
  const [pronto, setPronto] = useState(false)
  const [semDesenho, setSemDesenho] = useState(0)
  const atual = useRef({ aoEscolher, aoEscolherOpcao })
  useEffect(() => {
    atual.current = { aoEscolher, aoEscolherOpcao }
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
    if (import.meta.env.DEV || import.meta.env.VITE_RAIZ_TESTE_MAPA === "1") Object.assign(caixa.current, { __mapa: m })
    m.once("style.load", () => {
      m.addImage("listras", imagemListras(COR.mata), { pixelRatio: 2 })
      m.addImage("hachura-cruzada", imagemHachura(COR.pedra, true), { pixelRatio: 2 })
      m.addSource("lote", { type: "geojson", data: VAZIO as never, promoteId: "id" })
      m.addSource("lote-pontos", { type: "geojson", data: VAZIO as never, promoteId: "id" })
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
      // Contornos deslocados deixam visível quando a mesma fazenda participa de mais de uma opção.
      for (const [indice, id] of IDS_OPCOES.entries()) {
        m.addLayer({ id: `lote-opcao-${id}`, type: "line", source: "lote", filter: ["==", ["get", "opcao"], id],
          layout: { visibility: "none" },
          paint: { "line-color": CORES_OPCOES[id], "line-width": 2.5, "line-offset": (indice - 1) * 3,
            "line-dasharray": id === "segura" ? [3, 2] : id === "compacta" ? [1, 2] : [1, 0] },
        }, antes)
      }
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
      if (!m.getLayer("lote-area")) return
      const f = m.queryRenderedFeatures([e.point.x, e.point.y], { layers: ["lote-area", "lote-ponto"] })[0]
      if (f?.properties.opcao) atual.current.aoEscolherOpcao?.(f.properties.opcao as IdOpcao)
      atual.current.aoEscolher(f ? String(f.properties.cod) : null)
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
      setPronto(false)
    }
  }, [base])

  // as fazendas: contorno de cada uma (do município dela) e o ponto no meio
  useEffect(() => {
    const m = mapaRef.current
    if (!m || !pronto) return
    let vivo = true
    ;(m.getSource("lote-pontos") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features: fazendas.filter(coordenadaValida).map((f) => ({ type: "Feature", properties: propriedadesDaFazenda(f), geometry: { type: "Point", coordinates: [f.lon, f.lat] } })),
    } as never)
    const recebidas: Geo = { type: "FeatureCollection", features: fazendas.filter((f) => f.geometria).map((f) => ({
      type: "Feature", properties: { cod_imovel: f.cod_imovel }, geometry: f.geometria!,
    })) }
    const municipiosSemDesenho = [...new Set(fazendas.filter((f) => !f.geometria).map((f) => f.cod_ibge))]
    Promise.all(carregarContorno ? municipiosSemDesenho.map((cod) => carregarContorno(cod).catch(() => null)) : []).then((extras) => {
      const geos = [recebidas, ...extras]
      if (!vivo) return
      const desenho = geometriasDosLotes(geos, fazendas)
      ;(m.getSource("lote") as GeoJSONSource).setData(desenho as never)
      const desenhadas = new Set(desenho.features.map((f) => f.properties.cod))
      setSemDesenho(new Set(fazendas.filter((f) => !desenhadas.has(f.cod_imovel)).map((f) => f.cod_imovel)).size)
      // enquadra o lote quando a lista de fazendas muda de verdade (não a cada atualização do andamento)
      const chave = fazendas.map((f) => f.cod_imovel).sort().join(",")
      const limites = limitesDoLote(desenho, fazendas)
      if (chave !== enquadrado.current && limites) {
        enquadrado.current = chave
        m.fitBounds(limites, { padding: 56, maxZoom: 11, duration: 0 })
      }
    })
    return () => {
      vivo = false
    }
  }, [pronto, fazendas, carregarContorno])

  // cor pelo papel (lote ou reserva) ou pelo nível de interesse
  useEffect(() => {
    const m = mapaRef.current
    if (!m || !pronto) return
    for (const id of IDS_OPCOES) m.setLayoutProperty(`lote-opcao-${id}`, "visibility", modo === "opcoes" ? "visible" : "none")
    m.setPaintProperty("lote-area", "fill-opacity", modo === "opcoes" ? ["case", ["==", ["get", "opcao"], opcaoAtiva ?? "barata"], 0.45, 0.15] : 0.9)
    if (modo === "opcoes") {
      m.setPaintProperty("lote-area", "fill-color", COR_OPCAO)
      m.setPaintProperty("lote-ponto", "circle-color", COR_OPCAO)
      m.setPaintProperty("lote-listras", "fill-opacity", ["case", ["==", ["get", "papel"], 0], 0.6, 0])
      m.setPaintProperty("lote-recusa", "fill-opacity", 0)
    } else if (modo === "papel") {
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
  }, [pronto, modo, opcaoAtiva])

  // fazenda escolhida: contorno em tinta
  const anterior = useRef<string | null>(null)
  useEffect(() => {
    const m = mapaRef.current
    if (!m || !pronto) return
    for (const opcao of ["lote", ...IDS_OPCOES]) {
      if (anterior.current) m.setFeatureState({ source: "lote", id: `${opcao}:${anterior.current}` }, { escolhida: false })
      if (escolhida) m.setFeatureState({ source: "lote", id: `${opcao}:${escolhida}` }, { escolhida: true })
    }
    anterior.current = escolhida
  }, [pronto, escolhida, fazendas])

  return (
    <div className="mapa-lote-conjunto">
      <div className="mapa mapa-lote" ref={caixa} role="region" aria-label="Mapa dos lotes: a tabela abaixo oferece as mesmas fazendas pelo teclado" />
      {semDesenho > 0 && <p className="aviso mapa-lote-aviso" role="status">{semDesenho.toLocaleString("pt-BR")} fazendas deste pedido ainda não têm desenho disponível. Os desenhos dependem de consulta autorizada e cobertura geográfica. Os pontos mostram somente a localização recebida do motor.</p>}
    </div>
  )
}
