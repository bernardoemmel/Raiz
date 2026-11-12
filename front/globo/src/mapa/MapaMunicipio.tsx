import {
  AttributionControl,
  LngLatBounds,
  Map as MapaGL,
  NavigationControl,
  Popup,
  type ExpressionSpecification,
  type GeoJSONSource,
  type LayerSpecification,
} from "maplibre-gl"
import "maplibre-gl/dist/maplibre-gl.css"
import { useEffect, useImperativeHandle, useRef, useState, type Ref } from "react"
import { CATEGORIAS, type Geo, type Imovel } from "../../../compartilhado/dados"
import { abreviarCar, fmtHa, fmtInt, fmtModulos, STATUS_CAR } from "../../../compartilhado/formato"
import { ESCALA_FOGO, PERIODO_FOGO } from "../../../compartilhado/satelite"
import { fonte, useCarga } from "../dados"
import type { Frente } from "../filtros"
import { tituloDe } from "../filtros"
import { infoCaminho } from "../../../compartilhado/terra"
import type { Camadas } from "../partes/Filtros"
import { linkFazenda } from "../rota"
import { estiloBase, imagemHachura, prepararMapLibre } from "./estilo"

export interface MapaApi {
  /** voa da vista do Brasil até o município (abertura) */
  voar(duracao?: number): void
}

interface Props {
  cod: string
  imoveis: Imovel[] | null | undefined
  /** imóveis que passam nos filtros (null: todos) */
  passa: Set<string> | null
  camadas: Camadas
  frente: Frente
  destaque: string | null
  /** abertura: o mapa nasce na vista do Brasil e espera voar() */
  comecaLonge?: boolean
  aoPronto?: () => void
  ref?: Ref<MapaApi>
}

const CORES: ExpressionSpecification = [
  "match",
  ["get", "cat"],
  ...CATEGORIAS.flatMap((c) => [c.id, c.cor]),
  "sem_dado",
  "#8f9a8e",
  "#a7aea6",
] as unknown as ExpressionSpecification

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)

function caixaDeGeo(g: Geo | null): LngLatBounds | null {
  if (!g?.features.length) return null
  const b = new LngLatBounds()
  const andar = (c: unknown): void => {
    if (Array.isArray(c) && typeof c[0] === "number") b.extend(c as [number, number])
    else if (Array.isArray(c)) c.forEach(andar)
  }
  g.features.forEach((f) => andar(f.geometry.coordinates))
  return b
}

/** O mundo com um buraco no município: escurece o que está fora. */
function mascara(g: Geo | null): Geo | null {
  if (!g?.features.length) return null
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
  return {
    type: "FeatureCollection",
    features: [{ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [mundo, ...buracos] } }],
  }
}

function juntar(g: Geo, porCod: Map<string, Imovel>, passa: Set<string> | null): Geo {
  return {
    type: "FeatureCollection",
    features: g.features.map((f) => {
      const cod = String(f.properties.cod_imovel)
      const i = porCod.get(cod)
      return {
        type: "Feature",
        id: f.id,
        geometry: f.geometry,
        properties: {
          cod_imovel: cod,
          cat: i ? i.categoria : "sem_dado",
          passa: !i || !passa || passa.has(cod) ? 1 : 0,
          alerta: i && i.alerta_pos2020_ha > 1 ? 1 : 0,
          sec: i && (i.secundaria_ha ?? 0) >= 1 ? 1 : 0,
          fogo: i?.fogo_anos_max ?? -1,
          area: f.properties.area ?? null,
          m_fiscal: f.properties.m_fiscal ?? null,
          status: f.properties.status_imovel ?? null,
        },
      }
    }),
  }
}

const VAZIO: Geo = { type: "FeatureCollection", features: [] }

/** Um ponto por imóvel que queimou no ano mais recente do MapBiomas, no meio do maior anel do polígono. */
function pontosDeFogo(g: Geo, porCod: Map<string, Imovel>): Geo {
  const features: Geo["features"] = []
  for (const f of g.features) {
    const i = porCod.get(String(f.properties.cod_imovel))
    if (!i || !(i.mb_fogo_ha && i.mb_fogo_ha > 0)) continue
    const aneis =
      f.geometry.type === "Polygon"
        ? [(f.geometry.coordinates as number[][][])[0]]
        : (f.geometry.coordinates as number[][][][]).map((p) => p[0])
    const anel = aneis.sort((a, b) => b.length - a.length)[0]
    if (!anel?.length) continue
    let x = 0
    let y = 0
    for (const [a, b] of anel) {
      x += a
      y += b
    }
    features.push({
      type: "Feature",
      properties: { cod_imovel: i.cod_imovel, ha: i.mb_fogo_ha },
      geometry: { type: "Point", coordinates: [x / anel.length, y / anel.length] },
    })
  }
  return { type: "FeatureCollection", features }
}

function textoPopup(cod: string, props: Record<string, unknown>, i: Imovel | undefined, frente: Frente): string {
  const car = `<div class="pop-car">CAR ${esc(abreviarCar(cod))}</div>`
  if (!i) {
    const area = Number(props.area)
    const mf = Number(props.m_fiscal)
    const status = STATUS_CAR[String(props.status)] ?? ""
    return (
      car +
      `<div class="pop-titulo">${Number.isFinite(area) ? esc(fmtHa(area)) : "Imóvel"} no CAR</div>` +
      `<p class="pop-sub">${Number.isFinite(mf) ? esc(fmtModulos(mf)) + " · " : ""}${status ? "CAR " + esc(status) + " · " : ""}o funil por fazenda deste município ainda não está na amostra</p>`
    )
  }
  const area = frente.area(i)
  const titulo =
    area > 0 && frente.entra(i)
      ? `${fmtHa(area)} ${frente.sobre}`
      : (CATEGORIAS.find((c) => c.id === i.categoria)?.rotulo ?? "Imóvel")
  const terra = infoCaminho(tituloDe(i)).curto
  const alerta = i.alerta_pos2020_ha > 1 ? `alerta em ${i.alerta_ultimo_ano ?? "depois de 2020"}` : "0 alertas desde 2020"
  const fogo: string[] = []
  if (i.fogo_anos_max !== null)
    fogo.push(i.fogo_anos_max >= 0.5 ? `fogo em ${fmtInt(i.fogo_anos_max)} ${Math.round(i.fogo_anos_max) === 1 ? "ano" : "anos"} desde 1985` : "sem fogo desde 1985")
  if (i.mb_ano !== null && i.mb_fogo_ha) fogo.push(`${fmtHa(i.mb_fogo_ha)} queimados em ${i.mb_ano}`)
  return (
    car +
    `<div class="pop-titulo">${esc(titulo)}</div>` +
    `<p class="pop-sub">${esc(fmtHa(i.ha))} · ${terra} · ${esc(alerta)}${fogo.length ? "<br>" + esc(fogo.join(" · ")) : ""}</p>` +
    `<a class="pop-link" href="${esc(linkFazenda(cod))}">Abrir ficha →</a>`
  )
}

export function MapaMunicipio({ cod, imoveis, passa, camadas, frente, destaque, comecaLonge, aoPronto, ref }: Props) {
  const caixa = useRef<HTMLDivElement>(null)
  const mapaRef = useRef<MapaGL | null>(null)
  const [montado, setMontado] = useState(false)
  const geo = useCarga(async () => {
    const [municipio, imoveisGeo, ti, uc, rios, base, terraPublica] = await Promise.all([
      fonte.geo.camada(cod, "municipio"),
      fonte.geo.camada(cod, "imoveis"),
      fonte.geo.camada(cod, "ti"),
      fonte.geo.camada(cod, "uc"),
      fonte.geo.camada(cod, "rios"),
      fonte.geo.base(cod),
      fonte.geo.camada(cod, "terra_publica").catch(() => null), // só a API tem; a amostra não
    ])
    return { municipio, imoveisGeo, ti, uc, rios, base, terraPublica }
  }, [cod])

  // o que os eventos do mapa precisam ler na hora (sem recriar o mapa)
  const atual = useRef({ imoveis, frente, porCod: new Map<string, Imovel>() })
  atual.current.imoveis = imoveis
  atual.current.frente = frente
  const porCod = useRef(new Map<string, Imovel>())
  useEffect(() => {
    porCod.current = new Map((imoveis ?? []).map((i) => [i.cod_imovel, i]))
    atual.current.porCod = porCod.current
  }, [imoveis])

  const limites = useRef<LngLatBounds | null>(null)
  const jaVoou = useRef(!comecaLonge)

  useImperativeHandle(ref, () => ({
    voar(duracao = 2800) {
      jaVoou.current = true
      const m = mapaRef.current
      if (!m || !limites.current) return
      m.fitBounds(limites.current, { padding: 36, duration: duracao, curve: 1.5, essential: true })
    },
  }))

  // cria o mapa (uma vez) e troca o estilo quando o município muda
  useEffect(() => {
    const g = geo.dado
    if (!g || !caixa.current) return
    prepararMapLibre()
    limites.current = caixaDeGeo(g.municipio)
    const estilo = estiloBase(g.base)
    let m = mapaRef.current
    if (!m) {
      const centro = limites.current?.getCenter() ?? { lng: -52, lat: -6.6 }
      m = new MapaGL({
        container: caixa.current,
        style: estilo,
        center: [centro.lng, centro.lat],
        zoom: 3.4,
        attributionControl: false,
        cooperativeGestures: true,
        locale: {
          "CooperativeGesturesHandler.WindowsHelpText": "Use Ctrl + rolagem para aproximar o mapa",
          "CooperativeGesturesHandler.MacHelpText": "Use ⌘ + rolagem para aproximar o mapa",
          "CooperativeGesturesHandler.MobileHelpText": "Use dois dedos para mover o mapa",
          "NavigationControl.ZoomIn": "Aproximar",
          "NavigationControl.ZoomOut": "Afastar",
        },
      })
      m.addControl(new AttributionControl({ compact: true }), "bottom-right")
      // a atribuição começa recolhida (o "i" abre), para não cobrir a legenda
      m.once("load", () => caixa.current?.querySelector(".maplibregl-compact-show")?.classList.remove("maplibregl-compact-show"))
      m.addControl(new NavigationControl({ showCompass: false }), "top-right")
      mapaRef.current = m
      // só em desenvolvimento: deixa o mapa acessível para os testes de tela
      if (import.meta.env.DEV) Object.assign(caixa.current, { __mapa: m })
      ligarEventos(m)
    } else {
      setMontado(false)
      m.setStyle(estilo)
    }
    const mapa = m
    mapa.once("style.load", () => {
      montarCamadas(mapa, g)
      setMontado(true)
      if (jaVoou.current && limites.current) mapa.fitBounds(limites.current, { padding: 36, duration: 0 })
      mapa.once("idle", () => aoPronto?.())
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geo.dado])

  useEffect(
    () => () => {
      mapaRef.current?.remove()
      mapaRef.current = null
    },
    [],
  )

  // dados por fazenda e filtros
  useEffect(() => {
    const m = mapaRef.current
    const g = geo.dado?.imoveisGeo
    if (!m || !montado || !g) return
    ;(m.getSource("imoveis") as GeoJSONSource | undefined)?.setData(juntar(g, porCod.current, passa) as never)
    ;(m.getSource("fogo-recente") as GeoJSONSource | undefined)?.setData(pontosDeFogo(g, porCod.current) as never)
  }, [montado, imoveis, passa, geo.dado])

  // camadas ligadas e desligadas
  useEffect(() => {
    const m = mapaRef.current
    if (!m || !montado) return
    const vis = (id: string, on: boolean) => m.getLayer(id) && m.setLayoutProperty(id, "visibility", on ? "visible" : "none")
    vis("imoveis-sec", camadas.secundaria)
    vis("imoveis-alerta", camadas.alertas)
    vis("imoveis-fogo", camadas.fogo)
    vis("fogo-recente", camadas.fogo)
    for (const id of ["rios", "rios-linha"]) vis(id, camadas.rios)
    for (const id of ["ti", "ti-borda", "ti-rotulo", "uc", "uc-borda"]) vis(id, camadas.areas)
    for (const id of ["terra-publica", "terra-publica-borda"]) vis(id, camadas.terraPublica)
  }, [montado, camadas])

  // destaque vindo da lista
  const anterior = useRef<string | null>(null)
  useEffect(() => {
    const m = mapaRef.current
    if (!m || !montado || !m.getSource("imoveis")) return
    if (anterior.current) m.setFeatureState({ source: "imoveis", id: anterior.current }, { destaque: false })
    if (destaque) m.setFeatureState({ source: "imoveis", id: destaque }, { destaque: true })
    anterior.current = destaque
  }, [destaque, montado])

  function ligarEventos(m: MapaGL) {
    const popup = new Popup({ closeButton: true, maxWidth: "320px", offset: 6 })
    let sobre: string | null = null
    m.on("click", "imoveis", (e) => {
      const f = e.features?.[0]
      if (!f) return
      const cod = String(f.properties.cod_imovel)
      popup
        .setLngLat(e.lngLat)
        .setHTML(textoPopup(cod, f.properties, atual.current.porCod.get(cod), atual.current.frente))
        .addTo(m)
    })
    m.on("mousemove", "imoveis", (e) => {
      const cod = e.features?.[0]?.properties.cod_imovel as string | undefined
      if (cod === sobre) return
      if (sobre) m.setFeatureState({ source: "imoveis", id: sobre }, { sobre: false })
      sobre = cod ?? null
      if (sobre) m.setFeatureState({ source: "imoveis", id: sobre }, { sobre: true })
      m.getCanvas().style.cursor = "pointer"
    })
    m.on("mouseleave", "imoveis", () => {
      if (sobre) m.setFeatureState({ source: "imoveis", id: sobre }, { sobre: false })
      sobre = null
      m.getCanvas().style.cursor = ""
    })
  }

  function montarCamadas(m: MapaGL, g: NonNullable<typeof geo.dado>) {
    const antesDosRotulos = m.getStyle().layers.find((l) => l.type === "symbol")?.id
    const add = (camada: LayerSpecification, emCima = false) => m.addLayer(camada, emCima ? undefined : antesDosRotulos)
    if (!m.hasImage("hachura")) m.addImage("hachura", imagemHachura(), { pixelRatio: 2 })

    m.addSource("mascara", { type: "geojson", data: (mascara(g.municipio) ?? VAZIO) as never })
    m.addSource("municipio", { type: "geojson", data: (g.municipio ?? VAZIO) as never })
    m.addSource("ti", { type: "geojson", data: (g.ti ?? VAZIO) as never })
    m.addSource("uc", { type: "geojson", data: (g.uc ?? VAZIO) as never })
    m.addSource("rios", { type: "geojson", data: (g.rios ?? VAZIO) as never })
    m.addSource("terra-publica", { type: "geojson", data: (g.terraPublica ?? VAZIO) as never })
    m.addSource("imoveis", {
      type: "geojson",
      data: (g.imoveisGeo ? juntar(g.imoveisGeo, porCod.current, passa) : VAZIO) as never,
      promoteId: "cod_imovel",
    })
    m.addSource("fogo-recente", {
      type: "geojson",
      data: (g.imoveisGeo ? pontosDeFogo(g.imoveisGeo, porCod.current) : VAZIO) as never,
    })

    // terra pública para restaurar: contorno tracejado cor de terra e preenchimento leve; nunca some do mapa
    add({ id: "terra-publica", type: "fill", source: "terra-publica", paint: { "fill-color": "#A8741A", "fill-opacity": 0.18 } })
    add({
      id: "terra-publica-borda",
      type: "line",
      source: "terra-publica",
      paint: { "line-color": "#7E5510", "line-width": 1.4, "line-dasharray": [2, 2] },
    })
    add({ id: "uc", type: "fill", source: "uc", paint: { "fill-color": "#bcd2b3", "fill-opacity": 0.35 } })
    add({
      id: "uc-borda",
      type: "line",
      source: "uc",
      paint: { "line-color": "#6c8a6c", "line-width": 1.2, "line-dasharray": [3, 2] },
    })
    add({ id: "ti", type: "fill", source: "ti", paint: { "fill-pattern": "hachura", "fill-opacity": 0.9 } })
    add({
      id: "ti-borda",
      type: "line",
      source: "ti",
      paint: { "line-color": "#4f6d51", "line-width": 1.3, "line-dasharray": [4, 2] },
    })
    add({
      id: "rios",
      type: "fill",
      source: "rios",
      filter: ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]],
      paint: { "fill-color": "#86a9cf", "fill-opacity": 0.95 },
    })
    add({
      id: "rios-linha",
      type: "line",
      source: "rios",
      filter: ["in", ["geometry-type"], ["literal", ["LineString", "MultiLineString"]]],
      paint: { "line-color": "#7ea3cc", "line-width": 2 },
    })
    add({
      id: "imoveis",
      type: "fill",
      source: "imoveis",
      paint: {
        "fill-color": CORES,
        "fill-opacity": [
          "case",
          ["boolean", ["feature-state", "destaque"], false],
          1,
          ["==", ["get", "cat"], "sem_dado"],
          0.42,
          ["==", ["get", "passa"], 1],
          0.9,
          0.22,
        ],
      },
    })
    add({
      id: "imoveis-borda",
      type: "line",
      source: "imoveis",
      paint: {
        "line-color": "#ffffff",
        "line-opacity": ["interpolate", ["linear"], ["zoom"], 8, 0.25, 12, 0.9],
        "line-width": ["interpolate", ["linear"], ["zoom"], 8, 0.3, 13, 1.2],
      },
    })
    add({
      id: "imoveis-sec",
      type: "line",
      source: "imoveis",
      filter: ["==", ["get", "sec"], 1],
      paint: { "line-color": "#2c7a47", "line-width": 1.4, "line-dasharray": [1.5, 1.2] },
    })
    add({
      id: "imoveis-fogo",
      type: "line",
      source: "imoveis",
      filter: [">=", ["get", "fogo"], 0.5],
      layout: { visibility: "none" },
      paint: {
        "line-color": ["step", ["get", "fogo"], ESCALA_FOGO[0][1], ESCALA_FOGO[1][0], ESCALA_FOGO[1][1], ESCALA_FOGO[2][0], ESCALA_FOGO[2][1]],
        "line-width": ["interpolate", ["linear"], ["zoom"], 8, 1.1, 12, 2.6],
      },
    })
    add({
      id: "imoveis-alerta",
      type: "line",
      source: "imoveis",
      filter: ["==", ["get", "alerta"], 1],
      paint: { "line-color": "#b5483a", "line-width": 2 },
    })
    add({
      id: "imoveis-foco",
      type: "line",
      source: "imoveis",
      paint: {
        "line-color": "#10301f",
        "line-width": 2.6,
        "line-opacity": [
          "case",
          ["any", ["boolean", ["feature-state", "destaque"], false], ["boolean", ["feature-state", "sobre"], false]],
          1,
          0,
        ],
      },
    })
    add({ id: "mascara", type: "fill", source: "mascara", paint: { "fill-color": "#f3f4ef", "fill-opacity": 0.55 } })
    add({
      id: "fogo-recente",
      type: "circle",
      source: "fogo-recente",
      layout: { visibility: "none" },
      paint: {
        "circle-color": "#d9481f",
        "circle-opacity": 0.85,
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 1.2,
        "circle-radius": [
          "interpolate",
          ["linear"],
          ["zoom"],
          8,
          ["interpolate", ["linear"], ["sqrt", ["get", "ha"]], 0, 2, 10, 4, 55, 9],
          13,
          ["interpolate", ["linear"], ["sqrt", ["get", "ha"]], 0, 4, 10, 8, 55, 18],
        ],
      },
    })
    add({ id: "municipio", type: "line", source: "municipio", paint: { "line-color": "#1d5a39", "line-width": 2.2 } })
    add(
      {
        id: "ti-rotulo",
        type: "symbol",
        source: "ti",
        layout: {
          "text-field": ["concat", "Terra Indígena ", ["get", "nome"], "\n(excluída)"],
          "text-font": ["Noto Sans Italic"],
          "text-size": 12.5,
          "text-max-width": 12,
        },
        paint: { "text-color": "#3e5a41", "text-halo-color": "#eef2ea", "text-halo-width": 1.4 },
      },
      true,
    )
  }

  const g = geo.dado
  const semGeo = g && !g.municipio
  return (
    <div className="mapa-caixa">
      <div className="mapa" ref={caixa} aria-label="Mapa do município" role="region" />
      {!g && <div className="mapa-carregando">Carregando o mapa…</div>}
      {semGeo && (
        <div className="mapa-aviso">
          A geometria deste município ainda não foi gerada. Rode <code>python front/scripts/geo.py {cod}</code>.
        </div>
      )}
      {g && !g.imoveisGeo && !semGeo && (
        <div className="mapa-aviso">Os polígonos do CAR deste município ainda não foram baixados.</div>
      )}
      <ul className="legenda" aria-label="Legenda">
        {imoveis ? (
          CATEGORIAS.map((c) => (
            <li key={c.id}>
              <i style={{ background: c.cor }} />
              {c.rotulo}
            </li>
          ))
        ) : (
          <li>
            <i style={{ background: "#8f9a8e", opacity: 0.6 }} />
            Imóvel do CAR (funil por fazenda a caminho)
          </li>
        )}
        {camadas.areas && (
          <li>
            <i className="hachura" />
            Terra indígena (excluída)
          </li>
        )}
        {camadas.terraPublica && (
          <li>
            <i className="contorno" style={{ borderColor: "#7E5510", borderStyle: "dashed" }} />
            Terra pública para restaurar (candidata a concessão)
          </li>
        )}
        {imoveis && camadas.fogo && (
          <>
            <li className="titulo">Fogo, {PERIODO_FOGO}</li>
            <li>
              <i className="contorno" style={{ borderColor: ESCALA_FOGO[0][1] }} />1 a 2 anos
            </li>
            <li>
              <i className="contorno" style={{ borderColor: ESCALA_FOGO[1][1] }} />3 a 5 anos
            </li>
            <li>
              <i className="contorno" style={{ borderColor: ESCALA_FOGO[2][1] }} />6 anos ou mais
            </li>
            <li>
              <i className="circulo" />
              Queimou em {imoveis.find((i) => i.mb_ano !== null)?.mb_ano ?? "2025"} (tamanho pela área)
            </li>
          </>
        )}
        {imoveis && camadas.alertas && (
          <li>
            <i className="contorno" />
            Alerta de desmatamento depois de 2020
          </li>
        )}
      </ul>
    </div>
  )
}
