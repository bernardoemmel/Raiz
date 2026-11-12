/**
 * Mini mapa do Brasil em SVG (guia, item 2.1, parte 8): o contorno dos estados em névoa, o estado do município
 * destacado e um ponto em urucum no município. É texto SVG pronto (uns 11 kB), sem segundo mapa WebGL; serve ao painel
 * (React) e à ficha do produtor (Preact, também sem JavaScript).
 */

import { ALTURA, ESTADOS, LARGURA, projetar } from "./brasil-estados"
import { COR } from "./cores"

export function svgMiniBrasil(opcoes: { uf?: string | null; lon?: number | null; lat?: number | null; titulo: string }): string {
  const { uf, lon, lat, titulo } = opcoes
  const estados = Object.entries(ESTADOS)
    .map(
      ([sigla, d]) =>
        `<path d="${d}" fill="${sigla === uf ? COR.situacaoNaoApta : COR.nevoa}" stroke="${COR.superficie}" stroke-width="0.6"/>`,
    )
    .join("")
  let ponto = ""
  if (lon !== null && lon !== undefined && lat !== null && lat !== undefined) {
    const [x, y] = projetar(lon, lat)
    ponto = `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4" fill="${COR.urucum}" stroke="${COR.superficie}" stroke-width="1.5"/>`
  }
  const esc = titulo.replace(/[&<>"]/g, (c) => `&#${c.charCodeAt(0)};`)
  return (
    `<svg viewBox="-2 -2 ${LARGURA + 4} ${(ALTURA + 4).toFixed(1)}" role="img" aria-label="${esc}" xmlns="http://www.w3.org/2000/svg">` +
    `<title>${esc}</title>${estados}${ponto}</svg>`
  )
}
