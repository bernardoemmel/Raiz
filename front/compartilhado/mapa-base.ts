import { ATRIBUICAO_MAPA } from "./mapa-cores"

/**
 * A base nacional cobre todo o Brasil até z6. O teto explícito mantém o overzoom mesmo em um cache antigo que
 * anuncie z14 mas só tenha esses ladrilhos em dois municípios. A base detalhada de cada estado usa o próprio teto.
 */
export function fonteMapaBase(base: string) {
  const comum = { type: "vector" as const, attribution: ATRIBUICAO_MAPA }
  if (/(?:^|\/)base_brasil\.pmtiles(?:[?#]|$)/.test(base))
    return { ...comum, tiles: [`pmtiles://${base}/{z}/{x}/{y}`], minzoom: 0, maxzoom: 6 }
  return { ...comum, url: `pmtiles://${base}` }
}
