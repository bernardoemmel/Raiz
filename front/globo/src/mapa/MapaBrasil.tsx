import {
  AttributionControl,
  LngLatBounds,
  Map as MapaGL,
  NavigationControl,
  Popup,
  ScaleControl,
  type ExpressionSpecification,
  type GeoJSONSource,
  type LayerSpecification,
} from "maplibre-gl"
import "maplibre-gl/dist/maplibre-gl.css"
import { useEffect, useRef, useState } from "react"
import { COR, FOGO, MAPA, SITUACAO } from "../../../compartilhado/cores"
import type { Geo, Imovel, PontoFazenda } from "../../../compartilhado/dados"
import { MOTIVOS, etapaDe, noFoco, situacaoDe, type Foco, type MotivoId } from "../../../compartilhado/funil-etapas"
import { abreviarCar, fmtHa, fmtInt } from "../../../compartilhado/formato"
import { rotulosDeAreas } from "../../../compartilhado/rotulos-mapa"
import { tituloDe } from "../filtros"
import { linkFazenda } from "../rota"
import { estiloBase, imagemHachura, prepararMapLibre } from "./estilo"

/** O que o mapa pinta nas fazendas do município: a situação (padrão), o título da terra ou o fogo. */
export type CamadaAssunto = "situacao" | "titulo" | "fogo"

export interface GeoMunicipio {
  municipio: Geo | null
  imoveis: Geo | null
  ti: Geo | null
  uc: Geo | null
  rios: Geo | null
}

interface Props {
  brasil: { municipios: Geo | null; base: string | null } | undefined
  /** municípios com funil (resumo) e com lista por fazenda */
  processados: Set<string>
  comLista: Set<string>
  pontos: PontoFazenda[]
  municipio: string | null
  geoMunicipio: GeoMunicipio | null
  imoveis: Imovel[] | null
  foco: Foco
  camada: CamadaAssunto
  destaque: string | null
  /** espaço que a gaveta ocupa embaixo, no celular (o voo enquadra o município acima dela) */
  margemBaixo: number
  aoEscolherMunicipio: (cod: string) => void
}

const BRASIL: [number, number, number, number] = [-74, -34, -34.5, 5.5]
/** a partir deste zoom o município aparece por fazenda; abaixo, as fazendas aptas viram círculos com o número */
const ZOOM_FAZENDAS = 7.5

/** Códigos do estado de feição "g" de cada fazenda: a cor sai daqui, sem recarregar os polígonos (resposta rápida). */
const G = {
  apta: 0,
  pendencia: 1,
  naoApta: 2,
  apagada: 3,
  matricula: 20,
  assentamento: 21,
  posse: 22,
} as const
const MOTIVO_G: Record<MotivoId, number> = {
  embargo: 10,
  ti: 11,
  desmate: 12,
  alerta: 13,
  sem_area: 14,
  desmate10: 15,
  assentamento: 16,
  posse: 17,
}
const COR_G: ExpressionSpecification = [
  "match",
  ["coalesce", ["feature-state", "g"], -1],
  G.apta,
  SITUACAO.apta,
  G.pendencia,
  SITUACAO.pendencia,
  G.naoApta,
  SITUACAO.naoApta,
  G.matricula,
  COR.mata,
  G.assentamento,
  COR.restaurar,
  G.posse,
  COR.situacaoPendencia,
  ...(Object.entries(MOTIVO_G).flatMap(([m, g]) => [g, MOTIVOS[m as MotivoId].cor]) as (number | string)[]),
  SITUACAO.apagada,
] as unknown as ExpressionSpecification

const VAZIO: Geo = { type: "FeatureCollection", features: [] }

function limitesDe(g: Geo | null | undefined, filtro?: (f: Geo["features"][number]) => boolean): LngLatBounds | null {
  if (!g?.features.length) return null
  const b = new LngLatBounds()
  const andar = (c: unknown): void => {
    if (Array.isArray(c) && typeof c[0] === "number") b.extend(c as [number, number])
    else if (Array.isArray(c)) c.forEach(andar)
  }
  for (const f of g.features) if (!filtro || filtro(f)) andar(f.geometry.coordinates)
  return b.isEmpty() ? null : b
}

/** O mundo com um buraco no município: apaga o que está fora (máscara do guia, item 2.1, parte 2). */
function mascara(g: Geo | null): Geo {
  if (!g?.features.length) return VAZIO
  const buracos: unknown[] = []
  for (const f of g.features) {
    if (f.geometry.type === "Polygon") buracos.push((f.geometry.coordinates as unknown[])[0])
    if (f.geometry.type === "MultiPolygon") for (const p of f.geometry.coordinates as unknown[][]) buracos.push(p[0])
  }
  const mundo = [
    [-180, -85],
    [180, -85],
    [180, 85],
    [-180, 85],
    [-180, -85],
  ]
  return { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [mundo, ...buracos] } }] }
}

/** Aparelho fraco ou economia de dados: sem voo, só um corte (guia, item 3.3). */
function aparelhoFraco(): boolean {
  const n = navigator as Navigator & { deviceMemory?: number; connection?: { saveData?: boolean } }
  return (n.deviceMemory ?? 8) <= 2 || n.connection?.saveData === true || matchMedia("(prefers-reduced-motion: reduce)").matches
}

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)

function textoPopup(i: Imovel): string {
  const s = situacaoDe(i)
  const titulo = s === "nao_apta" ? "Não apta agora" : `${fmtHa(i.carbono_ha)} podem voltar a ser mata`
  const { motivo } = etapaDe(i)
  const por = motivo && s === "nao_apta" ? MOTIVOS[motivo].rotulo : s === "pendencia" ? "falta o título" : "com matrícula no SIGEF"
  return (
    `<div class="pop-car">CAR ${esc(abreviarCar(i.cod_imovel))}</div>` +
    `<div class="pop-titulo">${esc(titulo)}</div>` +
    `<p class="pop-sub">Imóvel de ${esc(fmtHa(i.ha))}, ${esc(por.charAt(0).toLowerCase() + por.slice(1))}.</p>` +
    `<a class="pop-link" href="${esc(linkFazenda(i.cod_imovel))}">Abrir ficha</a>`
  )
}

export function MapaBrasil(props: Props) {
  const { brasil, processados, comLista, pontos, municipio, geoMunicipio, imoveis, foco, camada, destaque, margemBaixo } = props
  const caixa = useRef<HTMLDivElement>(null)
  const mapaRef = useRef<MapaGL | null>(null)
  const [pronto, setPronto] = useState(false)
  const atual = useRef({ props, porCod: new Map<string, Imovel>() })
  const escolhido = useRef<string | null>(null)
  atual.current.props = props

  // cria o mapa uma vez, quando o mapa base do Brasil chega
  useEffect(() => {
    if (!brasil || !caixa.current || mapaRef.current) return
    prepararMapLibre()
    const m = new MapaGL({
      container: caixa.current,
      style: estiloBase(brasil.base),
      bounds: BRASIL,
      fitBoundsOptions: { padding: 24 },
      attributionControl: false,
      pixelRatio: Math.min(window.devicePixelRatio || 1, 2),
      fadeDuration: 150,
      dragRotate: false,
      pitchWithRotate: false,
      locale: { "NavigationControl.ZoomIn": "Aproximar", "NavigationControl.ZoomOut": "Afastar" },
    })
    m.addControl(new AttributionControl({ compact: false }), "bottom-right")
    m.addControl(new NavigationControl({ showCompass: false }), "top-right")
    m.addControl(new ScaleControl({ unit: "metric" }), "bottom-right")
    if (import.meta.env.DEV) Object.assign(caixa.current, { __mapa: m })
    mapaRef.current = m
    m.once("style.load", () => {
      montar(m, brasil.municipios)
      ligarEventos(m)
      setPronto(true)
    })
    return () => {
      m.remove()
      mapaRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brasil])

  // municípios processados (mata) e os demais (névoa)
  useEffect(() => {
    const m = mapaRef.current
    if (!m || !pronto || !brasil?.municipios) return
    const fs = brasil.municipios.features.map((f) => {
      const cod = String(f.properties.cod_ibge)
      return { ...f, properties: { ...f.properties, p: comLista.has(cod) ? 2 : processados.has(cod) ? 1 : 0 } }
    })
    ;(m.getSource("brasil-municipios") as GeoJSONSource).setData({ type: "FeatureCollection", features: fs } as never)
  }, [pronto, brasil, processados, comLista])

  // fazendas aptas agrupadas (escala do país e do estado)
  useEffect(() => {
    const m = mapaRef.current
    if (!m || !pronto) return
    // as do município escolhido saem dos grupos: lá cada fazenda aparece com o próprio contorno
    ;(m.getSource("pontos") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features: pontos.filter((p) => p.cod_ibge !== municipio).map((p) => ({
        type: "Feature",
        properties: { s: p.situacao === "apta" ? 1 : 0, ha: p.ha },
        geometry: { type: "Point", coordinates: [p.lon, p.lat] },
      })),
    } as never)
  }, [pronto, pontos, municipio])

  // camadas do município escolhido
  useEffect(() => {
    const m = mapaRef.current
    if (!m || !pronto) return
    const g = geoMunicipio
    const set = (id: string, d: Geo | null | undefined) => (m.getSource(id) as GeoJSONSource).setData((d ?? VAZIO) as never)
    set("municipio", g?.municipio)
    set("mascara", municipio ? mascara(g?.municipio ?? null) : VAZIO)
    set("ti", g?.ti)
    set("uc", g?.uc)
    set("nomes", rotulosDeAreas(g?.ti, g?.uc))
    set("rios", g?.rios)
    set("imoveis", g?.imoveis)
    set("fogo-recente", VAZIO)
    m.setFilter("brasil-mun-escolhido", ["==", ["get", "cod_ibge"], municipio ?? ""])
    if (escolhido.current) m.setFeatureState({ source: "brasil-municipios", id: escolhido.current }, { escolhido: false })
    if (municipio) m.setFeatureState({ source: "brasil-municipios", id: municipio }, { escolhido: true })
    escolhido.current = municipio
  }, [pronto, geoMunicipio, municipio])

  // cor de cada fazenda pela situação, pelo foco do funil e pela camada de assunto (estado de feição: rápido)
  useEffect(() => {
    const m = mapaRef.current
    const g = geoMunicipio?.imoveis
    if (!m || !pronto || !g || !imoveis) return
    const porCod = new Map(imoveis.map((i) => [i.cod_imovel, i]))
    atual.current.porCod = porCod
    const fogo: Geo["features"] = []
    for (const f of g.features) {
      const cod = String(f.properties.cod_imovel)
      const i = porCod.get(cod)
      let codigo: number = G.apagada
      if (i) {
        const dentro = noFoco(i, foco)
        if (!dentro) codigo = G.apagada
        else if (foco?.lado === "fora") codigo = MOTIVO_G[etapaDe(i).motivo ?? "posse"]
        else if (camada === "titulo") codigo = G[tituloDe(i)]
        else if (camada === "fogo") codigo = G.apagada
        else codigo = { apta: G.apta, pendencia: G.pendencia, nao_apta: G.naoApta }[situacaoDe(i)]
        if (camada === "fogo" && dentro && i.mb_fogo_ha && i.mb_fogo_ha > 0) {
          const g = f.geometry
          const anel =
            g.type === "Polygon"
              ? (g.coordinates as number[][][])[0]
              : g.type === "MultiPolygon"
                ? (g.coordinates as number[][][][])[0][0]
                : null
          if (anel?.length) {
            const c = anel.reduce((s, p) => [s[0] + p[0], s[1] + p[1]], [0, 0]).map((v) => v / anel.length)
            fogo.push({ type: "Feature", properties: { ha: i.mb_fogo_ha }, geometry: { type: "Point", coordinates: c } })
          }
        }
      }
      m.setFeatureState({ source: "imoveis", id: cod }, { g: codigo, fogo: i && camada === "fogo" && noFoco(i, foco) ? (i.fogo_anos_max ?? 0) : 0 })
    }
    ;(m.getSource("fogo-recente") as GeoJSONSource).setData({ type: "FeatureCollection", features: fogo } as never)
  }, [pronto, geoMunicipio, imoveis, foco, camada])

  // voo até o município (curva e duração do guia, item 3.2), ou de volta ao Brasil; sem passar por zoom de mundo
  const primeiraVez = useRef(true)
  const alvoRef = useRef<LngLatBounds | null>(null)
  useEffect(() => {
    const m = mapaRef.current
    if (!m || !pronto) return
    const alvo = municipio
      ? (limitesDe(brasil?.municipios, (f) => String(f.properties.cod_ibge) === municipio) ??
        limitesDe(geoMunicipio?.municipio))
      : new LngLatBounds([BRASIL[0], BRASIL[1]], [BRASIL[2], BRASIL[3]])
    if (!alvo) return
    alvoRef.current = alvo
    const padding = { top: 48, left: 48, right: 48, bottom: 48 + margemBaixo }
    const cortar = primeiraVez.current || aparelhoFraco()
    primeiraVez.current = false
    if (cortar) m.fitBounds(alvo, { padding, duration: 0 })
    else m.fitBounds(alvo, { padding, speed: 1.2, curve: 1.42, maxDuration: 2500 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pronto, municipio, brasil?.municipios, municipio ? !!geoMunicipio?.municipio : false])

  // a gaveta mudou de altura no celular: reenquadra o mesmo alvo, sem voo
  useEffect(() => {
    const m = mapaRef.current
    if (!m || !pronto || !alvoRef.current || primeiraVez.current) return
    m.fitBounds(alvoRef.current, { padding: { top: 48, left: 48, right: 48, bottom: 48 + margemBaixo }, duration: 200 })
  }, [margemBaixo, pronto])

  // destaque vindo da tabela
  const anterior = useRef<string | null>(null)
  useEffect(() => {
    const m = mapaRef.current
    if (!m || !pronto) return
    if (anterior.current) m.setFeatureState({ source: "imoveis", id: anterior.current }, { destaque: false })
    if (destaque) m.setFeatureState({ source: "imoveis", id: destaque }, { destaque: true })
    anterior.current = destaque
  }, [destaque, pronto])

  // assunto do mapa: hachura cruzada só na situação, contorno e círculos só no fogo
  useEffect(() => {
    const m = mapaRef.current
    if (!m || !pronto) return
    const vis = (id: string, on: boolean) => m.getLayer(id) && m.setLayoutProperty(id, "visibility", on ? "visible" : "none")
    vis("imoveis-fogo", camada === "fogo")
    vis("fogo-recente", camada === "fogo")
  }, [camada, pronto])

  function montar(m: MapaGL, municipiosBrasil: Geo | null) {
    const antesDosRotulos = m.getStyle().layers.find((l) => l.type === "symbol")?.id
    const add = (l: LayerSpecification, emCima = false) => m.addLayer(l, emCima ? undefined : antesDosRotulos)
    // A hachura diagonal quer dizer uma coisa só: área que pode voltar a ser mata, dentro da fazenda (guia, item 2.1,
    // parte 3). Ela entra quando o back-end entregar esse recorte por fazenda; aqui só a cruzada da fazenda não apta.
    m.addImage("hachura-cruzada", imagemHachura(COR.pedra, true), { pixelRatio: 2 })
    m.addSource("brasil-municipios", { type: "geojson", data: (municipiosBrasil ?? VAZIO) as never, promoteId: "cod_ibge" })
    for (const id of ["municipio", "mascara", "ti", "uc", "nomes", "rios", "fogo-recente"]) m.addSource(id, { type: "geojson", data: VAZIO as never })
    m.addSource("imoveis", { type: "geojson", data: VAZIO as never, promoteId: "cod_imovel" })
    m.addSource("pontos", { type: "geojson", data: VAZIO as never, cluster: true, clusterRadius: 44, clusterMaxZoom: 7 })

    // municípios do Brasil: processado em mata, o resto em névoa; some quando o município aparece por fazenda
    add({
      id: "brasil-mun",
      type: "fill",
      source: "brasil-municipios",
      paint: {
        "fill-color": ["match", ["get", "p"], 2, COR.mata, 1, COR.mata, COR.nevoa],
        // o município escolhido fica sem preenchimento: quem fala ali são as fazendas
        "fill-opacity": [
          "interpolate",
          ["linear"],
          ["zoom"],
          6,
          ["case", ["boolean", ["feature-state", "escolhido"], false], 0, ["match", ["get", "p"], 2, 0.42, 1, 0.22, 0.7]],
          ZOOM_FAZENDAS + 1,
          ["case", ["boolean", ["feature-state", "escolhido"], false], 0, ["match", ["get", "p"], 2, 0, 1, 0.12, 0.35]],
        ],
      },
    })
    add({
      id: "brasil-mun-linha",
      type: "line",
      source: "brasil-municipios",
      paint: {
        "line-color": ["case", ["boolean", ["feature-state", "sobre"], false], COR.tinta, COR.superficie],
        "line-width": [
          "interpolate",
          ["linear"],
          ["zoom"],
          4,
          ["case", ["boolean", ["feature-state", "sobre"], false], 2, 0.2],
          9,
          ["case", ["boolean", ["feature-state", "sobre"], false], 2, 1],
        ],
      },
    })
    // Dentro do município, o que não é fazenda do CAR fica em névoa lisa: área sem imóvel, terra indígena e unidade de
    // conservação. Vai embaixo da água e das estradas do mapa base, que continuam aparecendo por cima.
    const daAgua = m.getStyle().layers.find((l) => l.id === "water")?.id ?? antesDosRotulos
    m.addLayer({ id: "municipio-fundo", type: "fill", source: "municipio", paint: { "fill-color": COR.nevoa } }, daAgua)
    // terra indígena e unidade de conservação: só a divisa, fina e tracejada, e o nome por cima (camada "nomes")
    for (const id of ["ti", "uc"])
      add({
        id: `${id}-linha`,
        type: "line",
        source: id,
        paint: { "line-color": COR.pedra, "line-width": 0.8, "line-opacity": 0.6, "line-dasharray": [3, 2] },
      })
    add({ id: "rios", type: "fill", source: "rios", paint: { "fill-color": MAPA.agua } })
    // fazendas do município: cor pelo estado de feição "g"; não apta também com hachura cruzada (nunca só cor).
    // Sem zoom mínimo: a fonte só tem o município escolhido, e no celular ele cabe num zoom menor.
    add({
      id: "imoveis",
      type: "fill",
      source: "imoveis",
      paint: { "fill-color": COR_G, "fill-opacity": ["case", ["boolean", ["feature-state", "destaque"], false], 1, 0.9] },
    })
    add({
      id: "imoveis-cruzada",
      type: "fill",
      source: "imoveis",
      paint: {
        "fill-pattern": "hachura-cruzada",
        "fill-opacity": ["case", ["==", ["coalesce", ["feature-state", "g"], -1], G.naoApta], 0.55, 0],
      },
    })
    add({
      id: "imoveis-linha",
      type: "line",
      source: "imoveis",
      paint: {
        // a fazenda apagada é branca: a divisa dela em névoa, para continuar dando para ver uma de cada
        "line-color": ["case", ["==", ["coalesce", ["feature-state", "g"], -1], G.apagada], COR.nevoa, COR.superficie],
        "line-width": ["interpolate", ["linear"], ["zoom"], 8, 0.2, 13, 1.2],
      },
    })
    add({
      id: "imoveis-fogo",
      type: "line",
      source: "imoveis",
      layout: { visibility: "none" },
      paint: {
        "line-color": ["step", ["coalesce", ["feature-state", "fogo"], 0], "transparent", 1, FOGO.poucos, 3, FOGO.varios, 6, FOGO.muitos],
        "line-width": ["interpolate", ["linear"], ["zoom"], 8, 1.1, 12, 2.6],
      },
    })
    add({
      id: "imoveis-destaque",
      type: "line",
      source: "imoveis",
      paint: {
        "line-color": COR.tinta,
        "line-width": 2.5,
        "line-opacity": ["case", ["any", ["boolean", ["feature-state", "destaque"], false], ["boolean", ["feature-state", "sobre"], false]], 1, 0],
      },
    })
    add({ id: "mascara", type: "fill", source: "mascara", paint: { "fill-color": MAPA.mascaraClara, "fill-opacity": 0.6 } })
    add({
      id: "fogo-recente",
      type: "circle",
      source: "fogo-recente",
      layout: { visibility: "none" },
      paint: {
        "circle-color": FOGO.recente,
        "circle-stroke-color": COR.superficie,
        "circle-stroke-width": 1.2,
        "circle-radius": ["interpolate", ["linear"], ["sqrt", ["get", "ha"]], 0, 3, 10, 6, 55, 14],
      },
    })
    add({ id: "municipio", type: "line", source: "municipio", paint: { "line-color": COR.tinta, "line-width": 2 } })
    add(
      {
        id: "nomes",
        type: "symbol",
        source: "nomes",
        minzoom: 6,
        layout: {
          "text-field": ["get", "rotulo"],
          "text-font": ["Noto Sans Italic"],
          "text-size": ["interpolate", ["linear"], ["zoom"], 6, 11, 10, 13],
          "text-max-width": 8,
          "text-padding": 4,
        },
        paint: { "text-color": COR.pedra, "text-halo-color": COR.nevoa, "text-halo-width": 1.5 },
      },
      true,
    )
    add({
      id: "brasil-mun-escolhido",
      type: "line",
      source: "brasil-municipios",
      filter: ["==", ["get", "cod_ibge"], ""],
      maxzoom: ZOOM_FAZENDAS,
      paint: { "line-color": COR.tinta, "line-width": 2 },
    })
    // fazendas aptas agrupadas em círculos com o número dentro (guia, item 3.5), até o zoom do município
    add(
      {
        id: "pontos-grupo",
        type: "circle",
        source: "pontos",
        maxzoom: ZOOM_FAZENDAS,
        filter: ["has", "point_count"],
        paint: {
          "circle-color": COR.mata,
          "circle-stroke-color": COR.superficie,
          "circle-stroke-width": 2,
          "circle-radius": ["interpolate", ["linear"], ["get", "point_count"], 2, 12, 100, 18, 2000, 28],
        },
      },
      true,
    )
    add(
      {
        id: "pontos-numero",
        type: "symbol",
        source: "pontos",
        maxzoom: ZOOM_FAZENDAS,
        filter: ["has", "point_count"],
        layout: {
          // "5,4 mil", nunca "5.4k" (guia, item 1.6)
          "text-field": [
            "case",
            [">=", ["get", "point_count"], 1000],
            ["concat", ["number-format", ["/", ["get", "point_count"], 1000], { locale: "pt-BR", "max-fraction-digits": 1 }], " mil"],
            ["number-format", ["get", "point_count"], { locale: "pt-BR" }],
          ],
          "text-font": ["Noto Sans Medium"],
          "text-size": 13,
          "text-allow-overlap": true,
        },
        paint: { "text-color": COR.superficie },
      },
      true,
    )
    add(
      {
        id: "pontos-soltos",
        type: "circle",
        source: "pontos",
        maxzoom: ZOOM_FAZENDAS,
        filter: ["!", ["has", "point_count"]],
        paint: {
          "circle-color": ["match", ["get", "s"], 1, SITUACAO.apta, SITUACAO.pendencia],
          "circle-stroke-color": COR.superficie,
          "circle-stroke-width": 1,
          "circle-radius": 4,
        },
      },
      true,
    )
  }

  function ligarEventos(m: MapaGL) {
    const popup = new Popup({ closeButton: true, maxWidth: "320px", offset: 6 })
    let sobre: { fonte: string; id: string | number } | null = null
    const marcar = (fonte: string, id: string | number | undefined) => {
      if (sobre) m.setFeatureState({ source: sobre.fonte, id: sobre.id }, { sobre: false })
      sobre = id === undefined ? null : { fonte, id }
      if (sobre) m.setFeatureState({ source: sobre.fonte, id: sobre.id }, { sobre: true })
      m.getCanvas().style.cursor = sobre ? "pointer" : ""
    }
    m.on("click", (e) => {
      const fazenda = m.queryRenderedFeatures(e.point, { layers: ["imoveis"] })[0]
      const i = fazenda && atual.current.porCod.get(String(fazenda.properties.cod_imovel))
      if (i) {
        popup.setLngLat(e.lngLat).setHTML(textoPopup(i)).addTo(m)
        return
      }
      const grupo = m.queryRenderedFeatures(e.point, { layers: ["pontos-grupo"] })[0]
      if (grupo) {
        const fonte = m.getSource("pontos") as GeoJSONSource
        fonte.getClusterExpansionZoom(grupo.properties.cluster_id as number).then((z) =>
          m.easeTo({ center: (grupo.geometry as unknown as { coordinates: [number, number] }).coordinates, zoom: z }),
        )
        return
      }
      // clicar num município faz o mesmo que buscar por ele
      const mun = m.queryRenderedFeatures(e.point, { layers: ["brasil-mun"] })[0]
      const cod = mun && String(mun.properties.cod_ibge)
      if (cod && cod !== atual.current.props.municipio) atual.current.props.aoEscolherMunicipio(cod)
    })
    m.on("mousemove", (e) => {
      const fazenda = m.queryRenderedFeatures(e.point, { layers: ["imoveis"] })[0]
      if (fazenda && atual.current.porCod.has(String(fazenda.properties.cod_imovel)))
        return marcar("imoveis", String(fazenda.properties.cod_imovel))
      const mun = m.queryRenderedFeatures(e.point, { layers: ["brasil-mun"] })[0]
      if (mun && m.getZoom() < ZOOM_FAZENDAS) return marcar("brasil-municipios", String(mun.properties.cod_ibge))
      marcar("", undefined)
    })
  }

  const nomeMun = municipio
    ? (brasil?.municipios?.features.find((f) => String(f.properties.cod_ibge) === municipio)?.properties.nome as string | undefined)
    : undefined
  return (
    <div className="mapa-brasil" role="region" aria-label={nomeMun ? `Mapa de ${nomeMun}` : "Mapa do Brasil"}>
      <div className="mapa" ref={caixa} />
      {!brasil && (
        <div className="mapa-carregando">
          <span className="girando" aria-hidden="true" /> Carregando o mapa do Brasil
        </div>
      )}
      {brasil && !brasil.municipios && (
        <p className="aviso mapa-aviso">
          O contorno dos municípios do Brasil ainda não foi gerado. Rode <code>python front/scripts/geo.py</code>.
        </p>
      )}
      <span className="sr">{fmtInt(pontos.length)} fazendas aptas no mapa</span>
    </div>
  )
}
