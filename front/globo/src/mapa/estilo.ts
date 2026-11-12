/**
 * Mapa base da Raíz: MapLibre GL JS lendo o recorte do Protomaps em PMTiles (dados © OpenStreetMap, ODbL), com as
 * cores da Raíz. Sem chave e sem servidor de mapa: o arquivo .pmtiles é lido por faixas de bytes.
 */

import { layers, namedFlavor, type Flavor } from "@protomaps/basemaps"
import { addProtocol, setWorkerUrl, type StyleSpecification } from "maplibre-gl"
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url"
import { Protocol } from "pmtiles"

let pronto = false

export function prepararMapLibre() {
  if (pronto) return
  pronto = true
  setWorkerUrl(workerUrl)
  addProtocol("pmtiles", new Protocol().tile)
}

const claro = namedFlavor("light")

/** Tons de verde e azul da tela aprovada: terra verde-acinzentada, mata um pouco mais escura, rios azuis. */
export const SABOR_RAIZ: Flavor = {
  ...claro,
  background: "#dfe7d9",
  earth: "#e5ebdf",
  park_a: "#d6e3cf",
  park_b: "#cfdec7",
  wood_a: "#d4e1cc",
  wood_b: "#cbdbc2",
  scrub_a: "#dbe5d3",
  scrub_b: "#d6e1cd",
  water: "#94b4d6",
  boundaries: "#9ba69b",
  minor_a: "#f4f2ea",
  minor_b: "#f4f2ea",
  other: "#f1efe6",
  major: "#f7f3e6",
  highway: "#f6efd8",
  city_label: "#3f4a42",
  city_label_halo: "#eef2ea",
  subplace_label: "#5c675f",
  subplace_label_halo: "#eef2ea",
  state_label: "#7d877f",
  state_label_halo: "#eef2ea",
  country_label: "#7d877f",
  roads_label_minor: "#7d877f",
  roads_label_minor_halo: "#f4f2ea",
  roads_label_major: "#6a756d",
  roads_label_major_halo: "#f4f2ea",
  ocean_label: "#5f86b3",
  landcover: {
    barren: "#e9e6da",
    farmland: "#e7eadb",
    forest: "#c9dabf",
    glacier: "#ffffff",
    grassland: "#dce6d2",
    scrub: "#d7e2cd",
    urban_area: "#e3e1d8",
  },
}

/** URL das letras dos rótulos (geradas por front/scripts/geo.py em front/geo/fontes). */
const glyphs = () => location.origin + import.meta.env.BASE_URL + "geo/fontes/{fontstack}/{range}.pbf"

const ATRIBUICAO =
  '<a href="https://openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap</a> · ' +
  '<a href="https://protomaps.com" target="_blank" rel="noopener">Protomaps</a> · CAR/SICAR · INPE TerraBrasilis'

/** Estilo com o mapa base do município (ou só o fundo, se o PMTiles ainda não foi gerado). */
export function estiloBase(base: string | null, opcoes: { rotulos?: boolean } = {}): StyleSpecification {
  const fundo: StyleSpecification = {
    version: 8,
    glyphs: glyphs(),
    sources: {},
    layers: [{ id: "background", type: "background", paint: { "background-color": SABOR_RAIZ.earth } }],
  }
  if (!base) return fundo
  const camadas = layers("protomaps", SABOR_RAIZ, { lang: "pt" }).filter((l) => {
    if (l.id === "pois" || l.id.startsWith("address") || l.id === "buildings") return false
    if (opcoes.rotulos === false && l.type === "symbol") return false
    // sem sprite: nada de ícone
    return !(l.type === "symbol" && l.layout && "icon-image" in l.layout)
  })
  return {
    version: 8,
    glyphs: glyphs(),
    sources: { protomaps: { type: "vector", url: "pmtiles://" + base, attribution: ATRIBUICAO } },
    layers: camadas,
  }
}

/** Hachura diagonal para as terras indígenas (como na tela aprovada). */
export function imagemHachura(cor = "#5d7a5f"): { width: number; height: number; data: Uint8Array } {
  const t = 16
  const data = new Uint8Array(t * t * 4)
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(cor.slice(i, i + 2), 16))
  for (let y = 0; y < t; y++)
    for (let x = 0; x < t; x++) {
      const d = (x + y) % t
      const a = d < 2 ? 150 : 0
      const i = (y * t + x) * 4
      data.set([r, g, b, a], i)
    }
  return { width: t, height: t, data }
}
