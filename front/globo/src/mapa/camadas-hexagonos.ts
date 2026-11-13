import { COR_MAPA_V2, CORES_H3_V2 } from "../../../compartilhado/cores"
import type { ExpressionSpecification, LayerSpecification } from "maplibre-gl"
import type { HexagonoMapa, LegendaHexagonos } from "./hexagonos"
import { fmtHa, fmtInt } from "../../../compartilhado/formato"

/** A mesma publicação pode entregar a URL ao worker; nunca credenciais, consulta ou outra origem. */
export function fontePublicaHexagonos(url: string | null | undefined, esperado: string): string | null {
  if (!url) return null
  try {
    const referencia = new URL(esperado), recebido = new URL(url, referencia)
    return recebido.href === referencia.href && !recebido.username && !recebido.password ? recebido.href : null
  } catch { return null }
}

export function corHexagonos(legenda: LegendaHexagonos): ExpressionSpecification {
  const expressao: unknown[] = ["step", ["get", "valor"], legenda.cores[0]]
  for (let i = 1; i < legenda.limites.length; i++) expressao.push(legenda.limites[i], legenda.cores[i])
  return expressao as ExpressionSpecification
}

export function camadasHexagonos(): LayerSpecification[] {
  return [
    { id: "hexagonos", type: "fill", source: "hexagonos", paint: {
      "fill-color": CORES_H3_V2[0], "fill-opacity": 0.92, "fill-antialias": false,
      "fill-opacity-transition": { duration: 300 }, "fill-color-transition": { duration: 300 },
    } },
    { id: "hexagonos-linha", type: "line", source: "hexagonos", paint: {
      "line-color": COR_MAPA_V2.terra, "line-width": 0.5, "line-opacity-transition": { duration: 300 },
    } },
    { id: "hexagonos-selecionados", type: "line", source: "hexagonos", filter: ["==", ["get", "selecionado"], true], paint: {
      "line-color": COR_MAPA_V2.acao, "line-width": 2.2, "line-opacity-transition": { duration: 300 },
    } },
    { id: "hexagonos-sobre", type: "line", source: "hexagonos", filter: ["==", ["get", "h3"], ""], paint: {
      "line-color": COR_MAPA_V2.destaque, "line-width": 1.5, "line-opacity-transition": { duration: 300 },
    } },
  ]
}

export function descreverHexagono(hex: HexagonoMapa): string {
  const ha = hex.hectares === null ? "hectares não informados"
    : `${hex.hectares > 0 && hex.hectares < 0.1 ? "menos de 0,1 ha" : fmtHa(hex.hectares)} conhecidos${hex.parcial ? ", medida parcial" : ""}`
  return `${fmtInt(hex.fazendas)} fazendas cadastradas, ${ha}. Cobertura pública parcial.`
}
