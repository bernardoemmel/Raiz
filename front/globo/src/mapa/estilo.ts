/**
 * Mapa base da Raíz: MapLibre GL JS lendo o recorte do Protomaps em PMTiles (dados © OpenStreetMap, ODbL), com as
 * cores da Raíz. Sem chave e sem servidor de mapa: o arquivo .pmtiles é lido por faixas de bytes.
 */

import { layers, namedFlavor, type Flavor } from "@protomaps/basemaps"
import { addProtocol, setWorkerUrl, type LayerSpecification, type StyleSpecification } from "maplibre-gl"
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url"
import { Protocol } from "pmtiles"
import { COR, MAPA } from "../../../compartilhado/cores"
import { CORES_MAPA, FILTRO_PAISES } from "../../../compartilhado/mapa-cores"
import { fonteMapaBase } from "../../../compartilhado/mapa-base"
import { camadasNacionais, fontesNacionais, type DadosNacionais } from "./nacional"

let pronto = false

export function prepararMapLibre() {
  if (pronto) return
  pronto = true
  setWorkerUrl(workerUrl)
  addProtocol("pmtiles", new Protocol().tile)
}

/** O "white" do Protomaps recolorido com a paleta do guia (cores em compartilhado/cores.ts). */
export const SABOR_RAIZ: Flavor = { ...namedFlavor("white"), ...CORES_MAPA, landcover: { ...CORES_MAPA.landcover } }

/** URL das letras dos rótulos (geradas por front/scripts/geo.py em front/geo/fontes). */
const glyphs = () => location.origin + import.meta.env.BASE_URL + "geo/fontes/{fontstack}/{range}.pbf"

/** Estilo com o mapa base do município (ou só o fundo, se o PMTiles ainda não foi gerado). */
export function estiloBase(base: string | null, opcoes: { rotulos?: boolean; nacional?: boolean; dadosNacionais?: DadosNacionais } = {}): StyleSpecification {
  const fundo: StyleSpecification = {
    version: 8,
    glyphs: glyphs(),
    sources: {},
    layers: [{ id: "background", type: "background", paint: { "background-color": SABOR_RAIZ.earth, ...(opcoes.nacional ? { "background-opacity": 0 } : {}) } }],
  }
  if (opcoes.nacional) {
    const baseNacional = base ? camadasBaseNacionais() : fundo.layers
    const dadosNacionais = camadasNacionais(opcoes.dadosNacionais?.processadas)
    // Registra o estilo uma vez; o fundo aparece enquanto estados e agregados chegam.
    // Mantém fronteiras abaixo dos estados e nomes dos países abaixo dos rótulos de cobertura.
    return { ...fundo, sources: { ...(base ? { protomaps: fonteMapaBase(base) } : {}), ...fontesNacionais(opcoes.dadosNacionais) }, layers: [
      ...baseNacional.filter(camada => camada.type !== "symbol"),
      ...dadosNacionais.filter(camada => camada.type === "fill" || camada.type === "line"),
      ...baseNacional.filter(camada => camada.type === "symbol"),
      ...dadosNacionais.filter(camada => camada.type !== "fill" && camada.type !== "line"),
    ] }
  }
  if (!base) return fundo
  const camadas = camadasBase(opcoes.rotulos !== false)
  return {
    version: 8,
    glyphs: glyphs(),
    sources: { protomaps: fonteMapaBase(base) },
    layers: camadas,
  }
}

/** No país cabem terra, água, fronteiras e nomes. Estradas e usos locais entram quando a pessoa aproxima. */
export function camadasBaseNacionais(): LayerSpecification[] {
  const ids = new Set(["background", "earth", "water", "boundaries_country", "water_label_ocean", "places_country"])
  return camadasBase().filter((camada) => ids.has(camada.id)).map((camada) => {
    // O container nacional já tem a mesma cor sólida: não compila um programa gráfico só para ela.
    // A camada permanece como âncora de ordem; terra e água continuam sendo desenhadas pelo mapa real.
    if (camada.type === "background") return { ...camada, paint: { ...camada.paint, "background-opacity": 0 } }
    if (camada.type === "fill") return { ...camada, paint: { ...camada.paint, "fill-antialias": false } }
    if (camada.type === "symbol") return { ...camada, layout: { ...camada.layout, "text-font": ["Noto Sans Regular"] } }
    if (camada.type === "line") {
      // Fronteira contínua na visão do país: usa o mesmo programa gráfico dos limites estaduais.
      // O tracejado do estilo detalhado volta ao selecionar um lugar ou aproximar.
      const paint = { ...camada.paint }
      delete paint["line-dasharray"]
      return { ...camada, paint }
    }
    return camada
  })
}

/**
 * As camadas do Protomaps com o acabamento do guia (item 2.1, parte 1): rio em #7FAFC4 com 0,6 px no zoom 8, 1,4 no 12
 * e 3 no 15; nomes de cidade sem o ícone (não servimos sprite); rótulos com halo de 1,5 px da cor do fundo; sem pontos
 * de interesse, endereços e prédios.
 */
export function camadasBase(rotulos = true): LayerSpecification[] {
  return layers("protomaps", SABOR_RAIZ, { lang: "pt" }).flatMap((l): LayerSpecification[] => {
    if (l.id === "pois" || l.id.startsWith("address") || l.id === "buildings") return []
    // nome de estado sai do mapa base: a tela de entrada escreve o dela, com o que a Raíz já leu de cada um
    if (l.id === "places_region") return []
    if (l.type === "symbol" && !rotulos) return []
    if (l.id === "places_country") l = { ...l, filter: FILTRO_PAISES } as unknown as LayerSpecification
    if (l.type === "symbol" && l.layout && "icon-image" in l.layout) {
      if (l.id !== "places_locality") return []
      const layout = Object.fromEntries(Object.entries(l.layout).filter(([k]) => !k.startsWith("icon-")))
      return [{ ...l, layout: { ...layout, "text-anchor": "center", "text-offset": [0, 0] } } as LayerSpecification]
    }
    if (l.id === "water_river" || l.id === "water_stream")
      return [
        {
          ...l,
          paint: {
            "line-color": MAPA.rio,
            "line-width": ["interpolate", ["linear"], ["zoom"], 8, l.id === "water_river" ? 0.6 : 0.3, 12, 1.4, 15, 3],
          },
        } as LayerSpecification,
      ]
    if (l.type === "symbol" && l.paint && "text-halo-width" in l.paint)
      return [{ ...l, paint: { ...l.paint, "text-halo-width": 1.5 } } as LayerSpecification]
    return [l]
  })
}

/**
 * Hachura diagonal a 45 graus, linha de 1,5 px a cada 8 px (guia, item 2.1, parte 3), em imagem de 16 px com
 * pixelRatio 2. Com `cruzada`, as duas diagonais (não apta, item 2.2).
 */
/** Listras deitadas: fazenda de reserva no mapa do pedido (a diagonal é só da área que volta a ser mata, a cruzada da não apta). */
export function imagemListras(cor: string = COR.mata): { width: number; height: number; data: Uint8Array } {
  const t = 8
  const data = new Uint8Array(t * t * 4)
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(cor.slice(i, i + 2), 16))
  for (let y = 0; y < t; y++) for (let x = 0; x < t; x++) data.set([r, g, b, y % t < 2 ? 220 : 0], (y * t + x) * 4)
  return { width: t, height: t, data }
}

export function imagemHachura(cor: string = COR.mata, cruzada = false): { width: number; height: number; data: Uint8Array } {
  const t = 16
  const data = new Uint8Array(t * t * 4)
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(cor.slice(i, i + 2), 16))
  for (let y = 0; y < t; y++)
    for (let x = 0; x < t; x++) {
      const linha = (x + y) % t < 3 || (cruzada && (x - y + t) % t < 3)
      data.set([r, g, b, linha ? 200 : 0], (y * t + x) * 4)
    }
  return { width: t, height: t, data }
}
