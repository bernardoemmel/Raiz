/**
 * Espelho das cores de compartilhado/base.css para o que não lê variável CSS (MapLibre, SVG gerado, legenda), mais a
 * paleta do mapa (guia, item 2). É o único arquivo TypeScript com cor escrita; o verificador recusa cor em outro lugar
 * e um teste confere que as cores da interface batem com o base.css.
 */

/** As mesmas do :root de base.css. */
export const COR = {
  papel: "#FAFAF7",
  superficie: "#FFFFFF",
  tinta: "#15231B",
  pedra: "#555D56",
  nevoa: "#E7EAE4",
  mata: "#1D6B44",
  mataTexto: "#16543A",
  urucum: "#C2521A",
  urucumTexto: "#9E3F0E",
  agua: "#1D69A6",
  aguaTexto: "#175A8C",
  terra: "#A8741A",
  terraTexto: "#7E5510",
  situacaoApta: "#1D6B44",
  situacaoPendencia: "#E3A21A",
  situacaoNaoApta: "#C9C4BA",
  restaurar: "#5FA36E",
} as const

/** Mapa base e camadas (guia, itens 2.1 e 2.2; cores de uso da terra adaptadas do MapBiomas). */
export const MAPA = {
  terra: "#F1F2EE",
  agua: "#CADDE6",
  rio: "#7FAFC4",
  estrada: "#D2D4CE",
  estradaMiolo: "#FFFFFF",
  /** máscara fora do imóvel: sobre satélite e sobre a base clara */
  mascaraSatelite: "#0F1A14",
  mascaraClara: "#F1F2EE",
  /** contorno do imóvel: linha de dentro sobre satélite e sobre a base clara; a de fora é branca */
  contornoSatelite: "#E9A23B",
  contornoClaro: "#15231B",
  contornoFora: "#FFFFFF",
  /** hachura da área que pode voltar a ser mata */
  hachuraClara: "#1D6B44",
  hachuraSatelite: "#B5DD7A",
  uso: {
    floresta: "#1F8D49",
    savana: "#A9D38F",
    pasto: "#EDDE8E",
    lavoura: "#B8892A",
    agua: "#2F6FD6",
    urbana: "#8D8F88",
  },
} as const

/** Sabor do mapa base do Protomaps em uso (a etapa 2 do guia troca pelo "white" recolorido). */
export const SABOR_MAPA = {
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

/** Fogo: dos anos com fogo (1 a 2, 3 a 5, 6 ou mais) ao fogo do ano, na família do urucum. */
export const FOGO = {
  poucos: COR.terra,
  varios: COR.urucum,
  muitos: COR.urucumTexto,
  recente: COR.urucum,
} as const

/** "#1D6B44" → [0.11, 0.42, 0.27], para o globo (cobe), que pede RGB de 0 a 1. */
export function rgb01(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16)
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255]
}
