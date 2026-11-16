import type { Geo } from "../../dados/tipos"

/**
 * Contornos fictícios em dois agrupamentos afastados, com variação dentro de cada um.
 * A posição independe de custo, risco e crédito: a opção compacta precisa escolher
 * vizinhos de verdade, não apenas herdar uma ordem favorável aos outros critérios.
 * Nenhum contorno representa uma fazenda real; só os identificadores vêm da amostra.
 */
export function geometriasDeTeste(cod: string, imoveis: string[]): Geo {
  const unidade = (valor: string): number => {
    let hash = 2166136261
    for (const c of valor) hash = Math.imul(hash ^ c.charCodeAt(0), 16777619)
    return (hash >>> 0) / 4294967296
  }
  const centro = cod === "1507300" ? [-53, -7] : [-47, -2]
  return {
    type: "FeatureCollection",
    features: imoveis.map((id) => {
      const x = centro[0] + unidade(`longitude:${id}`)
      const y = centro[1] + unidade(`latitude:${id}`)
      return {
        type: "Feature",
        properties: { cod_imovel: id },
        geometry: { type: "Polygon", coordinates: [[[x, y], [x + 0.001, y], [x + 0.001, y + 0.001], [x, y + 0.001], [x, y]]] },
      }
    }),
  }
}
