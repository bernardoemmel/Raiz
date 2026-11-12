/** Cores do mapa base da Raíz (sobre o sabor "light" do Protomaps), usadas pelo painel e pela ficha do produtor. */

export const CORES_MAPA = {
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
} as const

export const ATRIBUICAO_MAPA =
  '<a href="https://openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap</a> · ' +
  '<a href="https://protomaps.com" target="_blank" rel="noopener">Protomaps</a> · CAR/SICAR · INPE TerraBrasilis'
