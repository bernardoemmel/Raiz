/** Crédito do mapa base e das camadas (as cores ficam em cores.ts). */
export { SABOR_MAPA as CORES_MAPA } from "./cores"

export const ATRIBUICAO_MAPA =
  '<a href="https://openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap</a>, ' +
  '<a href="https://protomaps.com" target="_blank" rel="noopener">Protomaps</a>, CAR/SICAR, INPE TerraBrasilis'

/**
 * Rótulo de país sem o do Brasil: a Raíz só trabalha no Brasil, e o nome "Brasil" caía em cima do Pará. Os vizinhos
 * continuam com nome, para dar contexto. Brasil no OpenStreetMap: Q155 no Wikidata.
 */
export const FILTRO_PAISES = [
  "all",
  ["==", ["get", "kind"], "country"],
  ["!=", ["coalesce", ["get", "wikidata"], ""], "Q155"],
  ["!=", ["coalesce", ["get", "name:en"], ""], "Brazil"],
] as const
