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

/**
 * Sabor do mapa base: o "white" do Protomaps recolorido com a paleta do guia (item 2.1, parte 1): terra, água, estrada
 * com miolo branco, rótulos em tinta com halo da cor do fundo. Os rios ganham cor e largura por zoom em estilo.ts.
 */
export const SABOR_MAPA = {
  background: MAPA.terra,
  earth: MAPA.terra,
  park_a: MAPA.terra,
  park_b: MAPA.terra,
  wood_a: MAPA.terra,
  wood_b: MAPA.terra,
  scrub_a: MAPA.terra,
  scrub_b: MAPA.terra,
  sand: MAPA.terra,
  beach: MAPA.terra,
  glacier: MAPA.terra,
  water: MAPA.agua,
  boundaries: COR.situacaoNaoApta,
  other: MAPA.estradaMiolo,
  minor_service: MAPA.estradaMiolo,
  minor_a: MAPA.estradaMiolo,
  minor_b: MAPA.estradaMiolo,
  link: MAPA.estradaMiolo,
  major: MAPA.estradaMiolo,
  highway: MAPA.estradaMiolo,
  minor_service_casing: MAPA.estrada,
  minor_casing: MAPA.estrada,
  link_casing: MAPA.estrada,
  major_casing_early: MAPA.estrada,
  major_casing_late: MAPA.estrada,
  highway_casing_early: MAPA.estrada,
  highway_casing_late: MAPA.estrada,
  bridges_other_casing: MAPA.estrada,
  bridges_minor_casing: MAPA.estrada,
  bridges_link_casing: MAPA.estrada,
  bridges_major_casing: MAPA.estrada,
  bridges_highway_casing: MAPA.estrada,
  city_label: COR.tinta,
  city_label_halo: MAPA.terra,
  subplace_label: COR.pedra,
  subplace_label_halo: MAPA.terra,
  state_label: COR.pedra,
  state_label_halo: MAPA.terra,
  country_label: COR.pedra,
  roads_label_minor: COR.pedra,
  roads_label_minor_halo: MAPA.terra,
  roads_label_major: COR.pedra,
  roads_label_major_halo: MAPA.terra,
  ocean_label: MAPA.rio,
  landcover: {
    barren: MAPA.terra,
    farmland: MAPA.terra,
    forest: MAPA.terra,
    glacier: MAPA.terra,
    grassland: MAPA.terra,
    scrub: MAPA.terra,
    urban_area: MAPA.terra,
  },
} as const

/** Situação da fazenda (guia, item 2.2): apta, com pendência (rótulo escuro por cima), não apta (com hachura cruzada). */
export const SITUACAO = {
  apta: COR.situacaoApta,
  pendencia: COR.situacaoPendencia,
  naoApta: COR.situacaoNaoApta,
  /** fora do foco do funil: fica em branco, não some (a névoa é do chão sem imóvel do CAR) */
  apagada: COR.superficie,
} as const

/** Porte por módulos fiscais, em três tons do mesmo verde (guia, item 4.2): os pequenos vão para o projeto agrupado. */
/** Três tons do mesmo verde no funil (guia, item 4.2): escuro, médio e o médio clareado pela opacidade. */
export const PORTE = {
  grande: COR.mataTexto,
  medio: COR.restaurar,
  pequeno: COR.restaurar,
} as const
export const PORTE_OPACIDADE = { grande: 1, medio: 1, pequeno: 0.45 } as const

/** Motivo que tirou o imóvel de cada etapa do funil, para o mapa e a legenda (sempre com o rótulo escrito). */
export const MOTIVO = {
  embargo: COR.urucumTexto,
  ti: COR.terraTexto,
  desmate: COR.urucum,
  alerta: COR.terra,
  sem_area: COR.pedra,
  desmate10: COR.situacaoPendencia,
  assentamento: COR.restaurar,
  posse: COR.aguaTexto,
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
