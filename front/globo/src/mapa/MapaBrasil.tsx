import { SITUACOES_BASICAS, type ImovelBasico, type SituacaoBasica } from "../../../compartilhado/dados/basico"
import { normalizarCar } from "../../../compartilhado/calendario"
import {
  AttributionControl,
  LngLatBounds,
  Map as MapaGL,
  NavigationControl,
  Popup,
  ScaleControl,
  type GeoJSONSource,
  type SourceSpecification,
  type LayerSpecification,
} from "maplibre-gl"
import "maplibre-gl/dist/maplibre-gl.css"
import { useEffect, useRef, useState } from "react"
import { COR, MAPA } from "../../../compartilhado/cores"
import type { Estados, Geo, Imovel } from "../../../compartilhado/dados"
import { MOTIVOS, etapaDe, noFoco, situacaoDe, type Foco, type MotivoId } from "../../../compartilhado/funil-etapas"
import { abreviarCar, fmtHa, fmtInt, ufDoCodigo } from "../../../compartilhado/formato"
import { rotulosDeAreas } from "../../../compartilhado/rotulos-mapa"
import { fonteMapaBase } from "../../../compartilhado/mapa-base"
import { cederProcessamento } from "../../../compartilhado/ceder-processamento"
import { tituloDe } from "../filtros"
import { linkCalendarioImovel, linkFazenda } from "../rota"
import { camadasBase, estiloBase, imagemHachura, prepararMapLibre } from "./estilo"
import { prepararGpu } from "./preparar-gpu"
import { MarcadoresGrupos } from "./marcadores-grupos"

import type { AgregadosMapa } from "../../../compartilhado/dados/agregados"
import { CAMADA_GRUPOS, FONTE_GRUPOS, descreverGrupo, lerGrupo, prepararPontosAgregados, urlAgregadosPublica, type GrupoMapa } from "./grupos"
import { adicionarSatelitePublico, SATELITE_PUBLICO, type EstadoSatelitePublico } from "./satelite-publico"
import "./cartografia.css"
import { camadasImoveis, ordenarImoveis, ZOOM_IMOVEIS } from "./cartografia"

/** O que o mapa pinta nas fazendas do município: a situação (padrão), o título da terra ou o fogo. */
export type CamadaAssunto = "situacao" | "titulo" | "fogo" | "terra_publica"

export interface GeoMunicipio {
  municipio: Geo | null
  imoveis: Geo | null
  ti: Geo | null
  uc: Geo | null
  rios: Geo | null
  /** base detalhada compartilhada pelo estado; a nacional continua visível onde não houver detalhe */
  base?: string | null
  /** terra pública para restaurar (gleba não destinada, floresta nacional ou estadual): só pela API */
  terraPublica?: Geo | null
  /** Recorte medido e já autorizado pela API; nunca inferido de percentuais ou lido na fonte pública. */
  restauracaoAutorizada?: Geo | null
}

interface Props {
  agregados?: AgregadosMapa | null
  agregadosCarregando?: boolean
  agregadosErro?: boolean
  aoAproximar: () => void
  brasil: { municipios: Geo | null; estados: Geo | null; base: string | null } | undefined
  /** o que a Raíz já leu de cada estado (completo, incompleto, sem dados) */
  estados: Estados | undefined
  /** municípios com funil (resumo) e com lista por fazenda */
  processados: Set<string>
  comLista: Set<string>
  /** estado escolhido (tela do estado) */
  uf: string | null
  municipio: string | null
  geoMunicipio: GeoMunicipio | null
  imoveis: Imovel[] | null
  basicos?: ImovelBasico[] | null
  situacaoBasica?: SituacaoBasica | null
  foco: Foco
  camada: CamadaAssunto
  destaque: string | null
  emLeilao?: Set<string>
  /** espaço que a gaveta ocupa embaixo, no celular (o voo enquadra o município acima dela) */
  margemBaixo: number
  aoEscolherMunicipio: (cod: string) => void
  aoEscolherEstado: (uf: string) => void
}

const BRASIL: [number, number, number, number] = [-74, -34, -34.5, 5.5]
/** a partir deste zoom o município aparece por fazenda; abaixo, as fazendas aptas viram círculos com o número */
const ZOOM_FAZENDAS = ZOOM_IMOVEIS
const SITUACAO_ESTADO = { completo: 2, incompleto: 1, sem_dados: 0 } as const

/** A cobertura municipal acompanha o nome do estado no mapa. */
function rotuloDoEstado(e: Estados["estados"][number]): string {
  if (e.situacao === "sem_dados") return "ainda não processado"
  return `${fmtInt(e.municipios)} de ${fmtInt(e.municipios_ibge)} municípios`
}

/** Códigos do estado de feição "g" de cada fazenda: a cor sai daqui, sem recarregar os polígonos (resposta rápida). */
const G = {
  apta: 0,
  pendencia: 1,
  naoApta: 2,
  apagada: 3,
  privada_matricula: 20,
  assentamento: 21,
  posse_em_titulacao: 22,
  publica_concessao: 23,
  publica_sem_destinacao: 24,
  terra_indigena_ou_tradicional: 25,
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
  const ilhas: Geo["features"] = []
  for (const f of g.features) {
    const poligonos = f.geometry.type === "Polygon" ? [f.geometry.coordinates as unknown[]]
      : f.geometry.type === "MultiPolygon" ? f.geometry.coordinates as unknown[][] : []
    for (const p of poligonos) {
      buracos.push(p[0])
      for (const anel of p.slice(1)) ilhas.push({ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [anel] } })
    }
  }
  const mundo = [
    [-180, -85],
    [180, -85],
    [180, 85],
    [-180, 85],
    [-180, -85],
  ]
  return { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [mundo, ...buracos] } }, ...ilhas] }
}

/** Aparelho fraco ou economia de dados: sem voo, só um corte (guia, item 3.3). */
function aparelhoFraco(): boolean {
  const n = navigator as Navigator & { deviceMemory?: number; connection?: { saveData?: boolean } }
  return (n.deviceMemory ?? 8) <= 2 || n.connection?.saveData === true || matchMedia("(prefers-reduced-motion: reduce)").matches
}

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)

function textoPopup(i: Imovel, emLeilao = false): string {
  const s = situacaoDe(i)
  const titulo = s === "nao_apta" ? "Não apta agora" : `${fmtHa(i.carbono_ha)} podem voltar a ser mata`
  const { motivo } = etapaDe(i)
  const por = motivo && s === "nao_apta" ? MOTIVOS[motivo].rotulo : s === "pendencia" ? "falta o título" : "com matrícula no SIGEF"
  return (
    (emLeilao ? `<a class="selo conferir" href="${esc(linkCalendarioImovel(i.cod_imovel))}">Em leilão</a>` : "") +
    `<div class="pop-car">CAR ${esc(abreviarCar(i.cod_imovel))}</div>` +
    `<div class="pop-titulo">${esc(titulo)}</div>` +
    `<p class="pop-sub">Imóvel de ${esc(fmtHa(i.ha))}, ${esc(por.charAt(0).toLowerCase() + por.slice(1))}.</p>` +
    `<a class="pop-link" href="${esc(linkFazenda(i.cod_imovel))}">Abrir ficha</a>`
  )
}

export function MapaBrasil(props: Props) {
  const { brasil, estados, processados, comLista, uf, municipio, geoMunicipio, imoveis, basicos, situacaoBasica, foco, camada, destaque, margemBaixo, emLeilao } =
    props
  const caixa = useRef<HTMLDivElement>(null)
  const mapaRef = useRef<MapaGL | null>(null)
  const [pronto, setPronto] = useState(false)
  const [regional, setRegional] = useState(false)
  const limparSatelite = useRef<(() => void) | undefined>(undefined)
  const [zoom, setZoom] = useState(4)
  const [gruposVisiveis, setGruposVisiveis] = useState<GrupoMapa[]>([])
  const [erroAgregadosNoMapa, setErroAgregadosNoMapa] = useState(false)
  const listaGruposAberta = useRef(false)
  const marcadoresGrupos = useRef<MarcadoresGrupos | null>(null)
  const gruposAgendados = useRef<MapaGL | null>(null)
  const geracaoGrupos = useRef(0)
  const gruposProntos = useRef(false)
  const municipioPorZoom = useRef<string | null>(null)
  const [satelite, setSatelite] = useState<EstadoSatelitePublico>("carregando")
  const margemAplicada = useRef(margemBaixo)
  const atual = useRef({ props, porCod: new Map<string, Imovel>(), basicosPorCod: new Map<string, ImovelBasico>() })
  const escolhido = useRef<string | null>(null)
  atual.current.props = props

  // cria o mapa uma vez, quando o mapa base do Brasil chega
  useEffect(() => {
    if (!brasil || !caixa.current || mapaRef.current) return
    let removido = false
    let instancia: MapaGL | null = null
    let liberarGpu: (() => void) | undefined
    void prepararGpu().then(async (liberar) => {
      liberarGpu = liberar
      if (removido || !caixa.current) { liberar(); return }
      prepararMapLibre()
      const estilo = estiloBase(brasil.base, { nacional: true })
      // Montar o estilo, criar o contexto nativo e instalar controles são trabalhos independentes.
      // Cada continuação entrega a thread à entrada e à pintura, sem esperar um prazo ou ociosidade.
      await cederProcessamento()
      if (removido || !caixa.current) { liberar(); return }
      const m = new MapaGL({
        container: caixa.current,
        attributionControl: false,
        pixelRatio: Math.min(window.devicePixelRatio || 1, 2),
        fadeDuration: 0,
        dragRotate: false,
        pitchWithRotate: false,
        locale: { "NavigationControl.ZoomIn": "Aproximar", "NavigationControl.ZoomOut": "Afastar", "Popup.Close": "Fechar ficha breve" },
      })
      instancia = m
      // bounds no construtor faz o MapLibre redimensionar o canvas duas vezes.
      // O enquadramento imediato usa o tamanho final antes do primeiro frame.
      m.fitBounds(BRASIL, { padding: { top: 48, left: 48, right: 48, bottom: 48 + margemBaixo }, duration: 0 })
      margemAplicada.current = margemBaixo
      liberar()
      liberarGpu = undefined
      await cederProcessamento()
      if (removido) return
      m.addControl(new AttributionControl({ compact: false }), "bottom-right")
      m.addControl(new NavigationControl({ showCompass: false }), "top-right")
      m.addControl(new ScaleControl({ unit: "metric" }), "bottom-right")
      if (import.meta.env.DEV || import.meta.env.VITE_RAIZ_TESTE_MAPA === "1") Object.assign(caixa.current, { __mapa: m })
      mapaRef.current = m
      marcadoresGrupos.current = new MarcadoresGrupos(m, grupo => { void aproximarGrupo(m, grupo) })
      m.once("load", () => {
        ligarEventos(m)
        setPronto(true)
        setZoom(m.getZoom())
        m.on("zoom", () => {
          if (m.getZoom() >= ZOOM_FAZENDAS) marcadoresGrupos.current?.limpar()
        })
        m.on("zoomend", () => {
          setZoom(m.getZoom())
          if (m.getZoom() >= 6) atual.current.props.aoAproximar()
        })
        m.on("idle", () => {
          agendarGruposVisiveis(m)
          if (m.getZoom() < ZOOM_FAZENDAS || atual.current.props.municipio || !m.getLayer("brasil-mun")) return
          const p = m.project(m.getCenter())
          const municipio = m.queryRenderedFeatures(p, { layers: ["brasil-mun"] })[0]
          const cod = municipio && String(municipio.properties.cod_ibge)
          if (cod && cod !== municipioPorZoom.current) {
            municipioPorZoom.current = cod
            atual.current.props.aoEscolherMunicipio(cod)
          }
        })
      })
      // Registra os eventos antes do estilo: nenhuma resposta rápida pode perder o primeiro load.
      // As variantes deste estilo interno passam pela especificação MapLibre no build.
      // As camadas e filtros acrescentados depois continuam com a validação padrão.
      m.setStyle(estilo, { validate: false })
    })
    return () => {
      removido = true
      liberarGpu?.()
      limparSatelite.current?.()
      limparSatelite.current = undefined
      setPronto(false)
      setRegional(false)
      geracaoGrupos.current++
      gruposProntos.current = false
      gruposAgendados.current = null
      marcadoresGrupos.current?.limpar()
      marcadoresGrupos.current = null
      instancia?.remove()
      mapaRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brasil?.base])

  // Estradas, rios e nomes locais não são necessários no enquadramento do país.
  // Acrescenta o estilo completo à mesma instância quando a pessoa escolhe um lugar ou aproxima.
  useEffect(() => {
    const m = mapaRef.current
    if (!m || !pronto || regional || (!uf && !municipio && zoom < 6)) return
    let antes: string | undefined = "estados-preenchimento"
    for (const camada of m.getSource("protomaps") ? [...camadasBase()].reverse() : []) {
      if (!m.getLayer(camada.id)) m.addLayer(camada, antes)
      else if (camada.type === "background") m.setPaintProperty(camada.id, "background-opacity", camada.paint?.["background-opacity"] ?? 1)
      else if (camada.type === "symbol" && camada.layout?.["text-font"]) m.setLayoutProperty(camada.id, "text-font", camada.layout["text-font"])
      else if (camada.type === "line" && camada.paint?.["line-dasharray"]) m.setPaintProperty(camada.id, "line-dasharray", camada.paint["line-dasharray"])
      antes = camada.id
    }
    montar(m, brasil?.municipios ?? null)
    // A base estadual usa o satélite como âncora; ambos devem ficar abaixo de toda a cartografia regional.
    limparSatelite.current = adicionarSatelitePublico(m, "brasil-mun", setSatelite)
    setRegional(true)
  }, [pronto, regional, uf, municipio, zoom, brasil])

  // municípios processados (mata) e os demais (névoa)
  useEffect(() => {
    const m = mapaRef.current
    if (!m || !regional || !brasil?.municipios) return
    const fs = brasil.municipios.features.map((f) => {
      const cod = String(f.properties.cod_ibge)
      return { ...f, properties: { ...f.properties, p: comLista.has(cod) ? 2 : processados.has(cod) ? 1 : 0 } }
    })
    ;(m.getSource("brasil-municipios") as GeoJSONSource).setData({ type: "FeatureCollection", features: fs } as never)
  }, [regional, brasil, processados, comLista])

  useEffect(() => {
    const m = mapaRef.current
    if (!m || !pronto) return
    const arquivoEsperado = new URL(`${import.meta.env.BASE_URL}geo/agregados_brasil.geojson`, document.baseURI)
    const url = arquivoEsperado.origin === location.origin ? urlAgregadosPublica(props.agregados?.url, arquivoEsperado.href) : null
    setErroAgregadosNoMapa(false)
    const fonte = m.getSource(FONTE_GRUPOS) as GeoJSONSource
    let ativo = true
    const geracao = ++geracaoGrupos.current
    gruposProntos.current = false
    marcadoresGrupos.current?.limpar()
    setGruposVisiveis([])
    const falhou = () => {
      if (!ativo || mapaRef.current !== m) return
      gruposProntos.current = false
      geracaoGrupos.current++
      marcadoresGrupos.current?.limpar()
      setGruposVisiveis([])
      setErroAgregadosNoMapa(true)
    }
    fonte.on("error", falhou)
    void fonte.setData((url ?? prepararPontosAgregados(props.agregados?.geo)) as never).then(() => {
      if (ativo && mapaRef.current === m && geracao === geracaoGrupos.current) gruposProntos.current = true
    }).catch(falhou)
    return () => { ativo = false; fonte.off("error", falhou) }
  }, [pronto, props.agregados])

  // os estados pela situação: cor do contorno e o rótulo com a contagem (completo, incompleto, ainda não processado)
  useEffect(() => {
    const m = mapaRef.current
    if (!m || !pronto || !brasil?.estados || !estados) return
    const porUf = new Map((estados?.estados ?? []).map((e) => [e.uf, e]))
    const rotulos: Geo["features"] = []
    const fs = brasil.estados.features.map((f) => {
      const sigla = String(f.properties.uf)
      const e = porUf.get(sigla)
      const s = e ? SITUACAO_ESTADO[e.situacao] : -1
      const ponto = f.properties.rotulo as [number, number] | undefined
      if (e && ponto)
        rotulos.push({
          type: "Feature",
          // na disputa de espaço entre rótulos, ganha o estado com dado e, entre iguais, o de mais municípios (Goiás
          // aparece antes do Distrito Federal)
          properties: { uf: sigla, nome: e.nome, linha: rotuloDoEstado(e), s, ordem: (2 - s) * 10000 - e.municipios_ibge },
          geometry: { type: "Point", coordinates: ponto },
        })
      return { ...f, properties: { ...f.properties, s } }
    })
    ;(m.getSource("brasil-estados") as GeoJSONSource).setData({ type: "FeatureCollection", features: fs } as never)
    ;(m.getSource("estados-rotulos") as GeoJSONSource).setData({ type: "FeatureCollection", features: rotulos } as never)
  }, [pronto, brasil, estados])

  // o estado escolhido ganha o contorno forte (no município, quem tem o contorno forte é o município)
  useEffect(() => {
    const m = mapaRef.current
    if (!m || !pronto) return
    m.setFilter("estado-escolhido", ["==", ["get", "uf"], municipio ? "" : (uf ?? "")])
    m.setLayoutProperty("estados-preenchimento", "visibility", uf || municipio ? "none" : "visible")
    m.setLayoutProperty("estados-sem-dados", "visibility", uf || municipio ? "none" : "visible")
  }, [pronto, uf, municipio])

  // O fundo nacional continua em overzoom. A base do estado entra por cima sem recarregar as fazendas nem o mapa.
  useEffect(() => {
    const m = mapaRef.current
    const base = geoMunicipio?.base
    if (!m || !regional || !base || base === brasil?.base) return
    const fonte = "protomaps-detalhe"
    m.addSource(fonte, fonteMapaBase(base))
    const ids: string[] = []
    const antes = m.getLayer(SATELITE_PUBLICO.id) ? SATELITE_PUBLICO.id : "brasil-mun"
    for (const camada of camadasBase()) {
      if (camada.type === "background") continue
      const id = `detalhe-${camada.id}`
      ids.push(id)
      m.addLayer({ ...camada, id, source: fonte } as LayerSpecification, camada.type === "symbol" ? undefined : antes)
    }
    return () => {
      for (const id of ids) if (m.getLayer(id)) m.removeLayer(id)
      if (m.getSource(fonte)) m.removeSource(fonte)
    }
  }, [regional, geoMunicipio?.base, brasil?.base])

  // camadas do município escolhido
  useEffect(() => {
    const m = mapaRef.current
    if (!m || !regional) return
    const g = geoMunicipio
    const set = (id: string, d: Geo | null | undefined) => (m.getSource(id) as GeoJSONSource).setData((d ?? VAZIO) as never)
    set("municipio", g?.municipio)
    set("mascara", municipio ? mascara(g?.municipio ?? null) : VAZIO)
    set("ti", g?.ti)
    set("uc", g?.uc)
    set("nomes", rotulosDeAreas(g?.ti, g?.uc))
    set("rios", g?.rios)
    set("terra-publica", g?.terraPublica)
    set("imoveis", ordenarImoveis(g?.imoveis))
    set("restauracao-autorizada", g?.restauracaoAutorizada)
    set("mascara-fazenda", VAZIO)
    set("fogo-recente", VAZIO)
    m.setFilter("brasil-mun-escolhido", ["==", ["get", "cod_ibge"], municipio ?? ""])
    if (escolhido.current) m.setFeatureState({ source: "brasil-municipios", id: escolhido.current }, { escolhido: false })
    if (municipio) m.setFeatureState({ source: "brasil-municipios", id: municipio }, { escolhido: true })
    escolhido.current = municipio
  }, [regional, geoMunicipio, municipio])

  // cor de cada fazenda pela situação, pelo foco do funil e pela camada de assunto (estado de feição: rápido)
  useEffect(() => {
    const m = mapaRef.current
    const g = geoMunicipio?.imoveis
    atual.current.porCod = new Map()
    atual.current.basicosPorCod = new Map(basicos?.map((i) => [i.cod_imovel, i]) ?? [])
    if (!m || !regional || !g) return
    if (basicos) {
      for (const f of g.features) {
        const cod = String(f.properties.cod_imovel)
        const basico = atual.current.basicosPorCod.get(cod)
        const codigo = !basico || (situacaoBasica && basico.situacao_basica !== situacaoBasica)
          ? G.apagada : { apto: G.apta, com_pendencia: G.pendencia, nao_apto: G.naoApta }[basico.situacao_basica]
        m.setFeatureState({ source: "imoveis", id: cod }, { g: codigo, pendenciaFiltrada: situacaoBasica === "com_pendencia" && basico?.situacao_basica === "com_pendencia", emLeilao: !!emLeilao?.has(normalizarCar(cod)), fogo: 0 })
      }
      ;(m.getSource("fogo-recente") as GeoJSONSource).setData(VAZIO as never)
      return
    }
    if (!imoveis) return
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
      m.setFeatureState({ source: "imoveis", id: cod }, { g: codigo, pendenciaFiltrada: foco?.lado === "fora" && codigo !== G.apagada, emLeilao: !!emLeilao?.has(normalizarCar(cod)), fogo: i && camada === "fogo" && noFoco(i, foco) ? (i.fogo_anos_max ?? 0) : 0 })
    }
    ;(m.getSource("fogo-recente") as GeoJSONSource).setData({ type: "FeatureCollection", features: fogo } as never)
  }, [regional, geoMunicipio, imoveis, basicos, situacaoBasica, foco, camada, emLeilao])

  // voo até o município (curva e duração do guia, item 3.2), ou de volta ao Brasil; sem passar por zoom de mundo
  const primeiraVez = useRef(true)
  const enquadramento = useRef<string | null>(null)
  const alvoRef = useRef<LngLatBounds | null>(null)
  useEffect(() => {
    const m = mapaRef.current
    if (!m || !pronto) return
    const rota = municipio ? `municipio-${municipio}` : uf ? `estado-${uf}` : "brasil"
    // Carregar as divisas depois de expandir um grupo não desfaz o zoom escolhido.
    if (rota === "brasil" && enquadramento.current === rota) return
    enquadramento.current = rota
    const alvo = municipio
      ? (limitesDe(brasil?.municipios, (f) => String(f.properties.cod_ibge) === municipio) ??
        limitesDe(geoMunicipio?.municipio))
      : uf
        ? (limitesDe(brasil?.estados, (f) => f.properties.uf === uf) ??
          limitesDe(brasil?.municipios, (f) => f.properties.uf === uf) ??
          new LngLatBounds([BRASIL[0], BRASIL[1]], [BRASIL[2], BRASIL[3]]))
        : new LngLatBounds([BRASIL[0], BRASIL[1]], [BRASIL[2], BRASIL[3]])
    if (!alvo) return
    if (municipio && municipioPorZoom.current === municipio) { alvoRef.current = m.getBounds(); return }
    municipioPorZoom.current = null
    alvoRef.current = alvo
    const padding = { top: 48, left: 48, right: 48, bottom: 48 + margemBaixo }
    const inicialBrasil = primeiraVez.current && !uf && !municipio
    const cortar = primeiraVez.current || aparelhoFraco()
    primeiraVez.current = false
    if (inicialBrasil) return
    if (cortar) m.fitBounds(alvo, { padding, duration: 0 })
    else m.fitBounds(alvo, { padding, speed: 1.2, curve: 1.42, maxDuration: 2500 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pronto, municipio, uf, brasil?.municipios, municipio ? !!geoMunicipio?.municipio : false])

  // a gaveta mudou de altura no celular: reenquadra o mesmo alvo, sem voo
  useEffect(() => {
    const m = mapaRef.current
    if (!m || !pronto || !alvoRef.current || primeiraVez.current) return
    if (margemAplicada.current === margemBaixo) return
    margemAplicada.current = margemBaixo
    m.fitBounds(alvoRef.current, { padding: { top: 48, left: 48, right: 48, bottom: 48 + margemBaixo }, duration: 200 })
  }, [margemBaixo, pronto])

  // destaque vindo da tabela
  const anterior = useRef<string | null>(null)
  useEffect(() => {
    const m = mapaRef.current
    if (!m || !regional) return
    if (anterior.current) m.setFeatureState({ source: "imoveis", id: anterior.current }, { destaque: false })
    if (destaque) m.setFeatureState({ source: "imoveis", id: destaque }, { destaque: true })
    anterior.current = destaque
  }, [destaque, regional])

  // assunto do mapa: hachura cruzada só na situação, contorno e círculos só no fogo
  useEffect(() => {
    const m = mapaRef.current
    if (!m || !regional) return
    const vis = (id: string, on: boolean) => m.getLayer(id) && m.setLayoutProperty(id, "visibility", on ? "visible" : "none")
    vis("imoveis-fogo", camada === "fogo")
    vis("fogo-recente", camada === "fogo")
    vis("terra-publica", camada === "terra_publica")
    vis("terra-publica-linha", camada === "terra_publica")
  }, [camada, regional])

  function montar(m: MapaGL, municipiosBrasil: Geo | null) {
    const antesDosRotulos = m.getStyle().layers.find((l) => l.type === "symbol")?.id
    const add = (l: LayerSpecification, emCima = false) => {
      if (!m.getLayer(l.id)) m.addLayer(l, emCima ? undefined : antesDosRotulos)
    }
    const fonte = (id: string, especificacao: SourceSpecification) => {
      if (!m.getSource(id)) m.addSource(id, especificacao)
    }
    // A hachura só representa um recorte medido e autorizado, nunca uma área inferida do limite ou da situação.
    if (!m.hasImage("hachura-restauracao")) m.addImage("hachura-restauracao", imagemHachura(COR.mata), { pixelRatio: 2 })
    fonte("brasil-municipios", { type: "geojson", data: (municipiosBrasil ?? VAZIO) as never, promoteId: "cod_ibge" })
    for (const id of ["municipio", "mascara", "ti", "uc", "nomes", "rios", "fogo-recente", "terra-publica", "restauracao-autorizada", "mascara-fazenda"])
      fonte(id, { type: "geojson", data: VAZIO as never })
    fonte("imoveis", { type: "geojson", data: VAZIO as never, promoteId: "cod_imovel" })
    // A superfície invisível escolhe o município; nenhum preenchimento representa potencial por CAR.
    add({ id: "brasil-mun", type: "fill", source: "brasil-municipios", paint: { "fill-color": COR.nevoa, "fill-opacity": 0 } })
    add({
      id: "brasil-mun-linha",
      type: "line",
      source: "brasil-municipios",
      paint: {
        "line-color": ["case", ["boolean", ["feature-state", "sobre"], false], COR.tinta, COR.pedra],
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
    if (!m.getLayer("municipio-fundo")) m.addLayer({ id: "municipio-fundo", type: "fill", source: "municipio", maxzoom: ZOOM_FAZENDAS, paint: { "fill-color": COR.nevoa, "fill-opacity": 0 } }, daAgua)
    // terra indígena e unidade de conservação: só a divisa, fina e tracejada, e o nome por cima (camada "nomes")
    for (const id of ["ti", "uc"])
      add({
        id: `${id}-linha`,
        type: "line",
        source: id,
        paint: { "line-color": COR.pedra, "line-width": 0.8, "line-opacity": 0.6, "line-dasharray": [3, 2] },
      })
    add({ id: "rios", type: "fill", source: "rios", paint: { "fill-color": MAPA.agua } })
    // terra pública para restaurar: cor de terra, contorno tracejado; só com a camada de assunto ligada
    add({ id: "terra-publica", type: "fill", source: "terra-publica", layout: { visibility: "none" },
          paint: { "fill-color": COR.terra, "fill-opacity": 0.22 } })  // prettier-ignore
    add({ id: "terra-publica-linha", type: "line", source: "terra-publica", layout: { visibility: "none" },
          paint: { "line-color": COR.terraTexto, "line-width": 1.4, "line-dasharray": [2, 2] } })  // prettier-ignore
    // Sem preenchimento: uma fazenda grande não esconde pequenas nem escurece áreas sobrepostas.
    for (const camada of camadasImoveis()) add(camada)
    add({ id: "restauracao-hachura", type: "fill", source: "restauracao-autorizada", minzoom: ZOOM_FAZENDAS,
      paint: { "fill-pattern": "hachura-restauracao", "fill-opacity": 0.7 } })
    // O calendário conserva o selo e a ficha. Não disputa a cor com o potencial nem com as pendências.
    add({ id: "imoveis-leilao", type: "line", source: "imoveis", minzoom: ZOOM_FAZENDAS,
      layout: { visibility: "none" }, paint: { "line-color": COR.pedra, "line-width": 1, "line-dasharray": [2, 2] } })
    add({ id: "imoveis-fogo", type: "line", source: "imoveis", minzoom: ZOOM_FAZENDAS,
      layout: { visibility: "none" }, paint: { "line-color": COR.tinta, "line-width": 1,
        "line-opacity": ["case", [">", ["coalesce", ["feature-state", "fogo"], 0], 0], 0.8, 0] } })
    add({ id: "mascara", type: "fill", source: "mascara", maxzoom: ZOOM_FAZENDAS, paint: { "fill-color": MAPA.mascaraClara, "fill-opacity": 0 } })
    add({ id: "mascara-fazenda", type: "fill", source: "mascara-fazenda", minzoom: ZOOM_FAZENDAS, paint: { "fill-color": MAPA.mascaraSatelite, "fill-opacity": 0.45 } })
    add({
      id: "fogo-recente",
      type: "circle",
      source: "fogo-recente",
      layout: { visibility: "none" },
      paint: {
        "circle-color": COR.tinta,
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
  }

  function agendarGruposVisiveis(m: MapaGL) {
    if (gruposAgendados.current === m) return
    gruposAgendados.current = m
    void cederProcessamento().then(() => {
      if (gruposAgendados.current !== m) return
      gruposAgendados.current = null
      if (mapaRef.current === m) atualizarGruposVisiveis(m)
    })
  }

  function atualizarGruposVisiveis(m: MapaGL) {
    if (!m.getLayer(CAMADA_GRUPOS)) return
    const grupos = new Map<string, GrupoMapa>()
    if (gruposProntos.current && m.getZoom() < ZOOM_FAZENDAS) {
      for (const f of m.queryRenderedFeatures({ layers: [CAMADA_GRUPOS] })) {
        const grupo = lerGrupo(f)
        if (grupo) grupos.set(grupo.chave, grupo)
      }
    }
    const visiveis = [...grupos.values()].sort((a, b) => b.fazendas - a.fazendas)
    marcadoresGrupos.current?.atualizar(visiveis)
    if (listaGruposAberta.current) setGruposVisiveis(visiveis)
  }

  async function aproximarGrupo(m: MapaGL, grupo: GrupoMapa) {
    const geracao = geracaoGrupos.current
    if (!gruposProntos.current) return
    try {
      const fonte = m.getSource(FONTE_GRUPOS) as GeoJSONSource
      const z = grupo.cluster === undefined ? ZOOM_FAZENDAS : Math.min(ZOOM_FAZENDAS, await fonte.getClusterExpansionZoom(grupo.cluster))
      if (mapaRef.current !== m || geracao !== geracaoGrupos.current || !gruposProntos.current) return
      atual.current.props.aoAproximar()
      m.easeTo({ center: grupo.centro, zoom: Math.max(m.getZoom() + 0.5, z), duration: aparelhoFraco() ? 0 : 500 })
    } catch {
      // O worker pode encerrar ou substituir o índice enquanto o grupo está sendo aberto.
    }
  }

  function ligarEventos(m: MapaGL) {
    const feicoes = (ponto: { x: number; y: number }, camada: string) => {
      const layers = (camada === "estados-preenchimento" ? [camada, "estados-sem-dados"] : [camada]).filter((id) => m.getLayer(id))
      return layers.length ? m.queryRenderedFeatures([ponto.x, ponto.y], { layers }) : []
    }
    const popup = new Popup({ closeButton: true, maxWidth: "320px", offset: 6 })
    let selecionado: string | null = null
    const limparSelecao = () => {
      if (!m.getSource("mascara-fazenda")) return
      ;(m.getSource("mascara-fazenda") as GeoJSONSource).setData(VAZIO as never)
      if (selecionado) m.setFeatureState({ source: "imoveis", id: selecionado }, { selecionado: false })
      selecionado = null
    }
    popup.on("close", limparSelecao)
    const selecionar = (cod: string) => {
      limparSelecao()
      const f = atual.current.props.geoMunicipio?.imoveis?.features.find((f) => String(f.properties.cod_imovel) === cod)
      if (!f) return
      selecionado = cod
      m.setFeatureState({ source: "imoveis", id: cod }, { selecionado: true })
      ;(m.getSource("mascara-fazenda") as GeoJSONSource).setData(mascara({ type: "FeatureCollection", features: [f] }) as never)
    }
    let sobre: { fonte: string; id: string | number } | null = null
    const marcar = (fonte: string, id: string | number | undefined) => {
      if (sobre?.fonte === fonte && sobre.id === id) return
      if (sobre && sobre.fonte !== "brasil-estados") m.setFeatureState({ source: sobre.fonte, id: sobre.id }, { sobre: false })
      sobre = id === undefined ? null : { fonte, id }
      if (sobre && sobre.fonte !== "brasil-estados") m.setFeatureState({ source: sobre.fonte, id: sobre.id }, { sobre: true })
      m.setFilter("estado-sobre", ["==", ["get", "uf"], sobre?.fonte === "brasil-estados" ? String(sobre.id) : ""])
      m.getCanvas().style.cursor = sobre ? "pointer" : ""
    }
    m.on("click", (e) => {
      const fazenda = feicoes(e.point, "imoveis")[0]
      const basico = fazenda && atual.current.basicosPorCod.get(String(fazenda.properties.cod_imovel))
      if (basico) {
        popup.setLngLat(e.lngLat).setHTML(
          (atual.current.props.emLeilao?.has(normalizarCar(basico.cod_imovel)) ? `<a class="selo conferir" href="${esc(linkCalendarioImovel(basico.cod_imovel))}">Em leilão</a>` : "") +
          `<div class="pop-car">CAR ${esc(abreviarCar(basico.cod_imovel))}</div>` +
          `<div class="pop-titulo">${esc(SITUACOES_BASICAS[basico.situacao_basica])}</div>` +
          `<p class="pop-sub">Situação básica da terra. As camadas completas são consultadas com créditos pagos.</p>` +
          `<a class="pop-link" href="${esc(linkFazenda(basico.cod_imovel))}">Abrir ficha completa</a>`
        ).addTo(m)
        selecionar(basico.cod_imovel)
        return
      }
      const i = fazenda && atual.current.porCod.get(String(fazenda.properties.cod_imovel))
      if (i) {
        popup.setLngLat(e.lngLat).setHTML(textoPopup(i, atual.current.props.emLeilao?.has(normalizarCar(i.cod_imovel)))).addTo(m)
        selecionar(i.cod_imovel)
        return
      }
      popup.remove()
      limparSelecao()
      const { uf, municipio } = atual.current.props
      const estado = feicoes(e.point, "estados-preenchimento")[0]
      const mun = feicoes(e.point, "brasil-mun")[0]
      const cod = mun && String(mun.properties.cod_ibge)
      const ufTocada = cod ? ufDoCodigo(cod) : estado ? String(estado.properties.uf) : null
      const emFoco = municipio ? ufDoCodigo(municipio) : uf
      // na escala do país, o toque escolhe o estado (aproxima e carrega só ele); dentro de um estado, o município
      if (ufTocada && ufTocada !== emFoco) return atual.current.props.aoEscolherEstado(ufTocada)
      if (cod && cod !== municipio) atual.current.props.aoEscolherMunicipio(cod)
    })
    m.on("mousemove", (e) => {
      const fazenda = feicoes(e.point, "imoveis")[0]
      if (fazenda && (atual.current.porCod.has(String(fazenda.properties.cod_imovel)) || atual.current.basicosPorCod.has(String(fazenda.properties.cod_imovel))))
        return marcar("imoveis", String(fazenda.properties.cod_imovel))
      const estado = feicoes(e.point, "estados-preenchimento")[0]
      const mun = feicoes(e.point, "brasil-mun")[0]
      const { uf, municipio } = atual.current.props
      const emFoco = municipio ? ufDoCodigo(municipio) : uf
      const ufSob = mun ? ufDoCodigo(String(mun.properties.cod_ibge)) : estado ? String(estado.properties.uf) : null
      // fora do estado em foco, quem acende é o estado inteiro (o toque vai escolher ele)
      if (ufSob && ufSob !== emFoco) return marcar("brasil-estados", ufSob)
      if (mun && m.getZoom() < ZOOM_FAZENDAS) return marcar("brasil-municipios", String(mun.properties.cod_ibge))
      marcar("", undefined)
    })
  }

  const nomeMun = municipio
    ? (brasil?.municipios?.features.find((f) => String(f.properties.cod_ibge) === municipio)?.properties.nome as string | undefined)
    : undefined
  const nomeUf = !municipio && uf ? estados?.estados.find((e) => e.uf === uf)?.nome : undefined
  const falhaNosAgregados = props.agregadosErro || erroAgregadosNoMapa
  return (
    <div className="mapa-brasil" role="region" aria-label={nomeMun ? `Mapa de ${nomeMun}` : nomeUf ? `Mapa de ${nomeUf}` : "Mapa do Brasil"}>
      <div className="mapa" ref={caixa} style={{ backgroundColor: MAPA.terra }} />
      {brasil && <div className="cartografia-legenda" aria-label="Como ler o mapa">
        {zoom < ZOOM_FAZENDAS && falhaNosAgregados && <p role="alert">Não foi possível carregar os agregados. Confira a conexão e recarregue a página.</p>}
        <details className="cartografia-resumo" open={margemBaixo === 0 && zoom >= ZOOM_FAZENDAS}>
        <summary><strong>{zoom < ZOOM_FAZENDAS ? "Grupos de fazendas" : "Limites do CAR"}</strong></summary>
        {zoom < ZOOM_FAZENDAS ? <>
          <p>Grupos mostram fazendas e hectares conhecidos. Cobertura parcial; toque para aproximar.</p>
          {props.agregadosCarregando ? <p role="status">Carregando os agregados…</p> : falhaNosAgregados ? null : props.agregados?.metadados.contagens.celulas ? <>
            <details><summary>Fonte e limites</summary><p>{props.agregados.metadados.aviso}</p><p>Fonte: {props.agregados.metadados.fonte}. Atualização: {props.agregados.metadados.atualizado_em ? new Date(props.agregados.metadados.atualizado_em).toLocaleDateString("pt-BR") : "não informada"}.</p></details>
            <details onToggle={e => { listaGruposAberta.current = e.currentTarget.open; if (mapaRef.current) atualizarGruposVisiveis(mapaRef.current) }}>
              <summary>Explorar grupos com teclado</summary>
              <ul className="cartografia-grupos-lista">{gruposVisiveis.map(grupo => <li key={grupo.chave}><button type="button" onClick={() => { if (mapaRef.current) void aproximarGrupo(mapaRef.current, grupo) }}>{descreverGrupo(grupo)} Aproximar.</button></li>)}</ul>
            </details>
          </> : <p>Agregados ainda não publicados. A ausência não significa área zero.</p>}
          {!uf && !municipio && <p>Estados verdes têm municípios processados; cinza indica ausência de dados.</p>}
        </> : <>
          <p>Sem preenchimento. Tracejado: limites com sobreposição. Limites declarados podem ter erro.</p>
          <details><summary>Imagem e áreas para restaurar</summary>
            <p>{satelite === "indisponivel" ? "Satélite indisponível neste momento; a base vetorial continua visível." : `${SATELITE_PUBLICO.titulo}, ${SATELITE_PUBLICO.resolucao}, ${SATELITE_PUBLICO.licenca}. Não mostra a situação atual da terra.`}</p>
            <p>{geoMunicipio?.restauracaoAutorizada?.features.length ? "Hachura verde: área que pode virar mata, medida e autorizada na API." : "A área que pode virar mata aparece hachurada quando seu recorte medido está disponível na ficha autorizada. Não é deduzida do limite do CAR."}</p>
          </details>
        </>}
        </details>
      </div>}
      {!brasil && (
        <div className="mapa-carregando">
          <span className="girando" aria-hidden="true" /> Carregando o mapa do Brasil
        </div>
      )}
      {brasil && !brasil.municipios && (uf || municipio) && (
        <p className="aviso mapa-aviso">
          Os limites municipais ainda não estão disponíveis para esta consulta.
        </p>
      )}
      <span className="sr">Agregados públicos com cobertura parcial. Limites reais do CAR ao aproximar.</span>
    </div>
  )
}
