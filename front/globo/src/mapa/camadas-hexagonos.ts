import { COR_MAPA_V2, CORES_H3_V2 } from "../../../compartilhado/cores"
import type { ExpressionSpecification, LayerSpecification, Map as MapaGL } from "maplibre-gl"
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

/** Seis intervalos quantitativos; as bordas inferiores vêm da mesma legenda enviada à interface. */
export function filtroFaixaHexagonos(legenda: LegendaHexagonos, faixa: number, lote: boolean, selecionados: boolean): ExpressionSpecification {
  const filtros: ExpressionSpecification[] = [[">=", ["get", "valor"], legenda.limites[faixa]]]
  if (faixa < 5) filtros.push(["<", ["get", "valor"], legenda.limites[faixa + 1]])
  if (lote || selecionados) filtros.push([lote ? "==" : "!=", ["get", "selecionado"], true])
  return ["all", ...filtros]
}

export function aplicarEscalaHexagonos(m: MapaGL, legenda: LegendaHexagonos, selecionados: boolean): void {
  for (let faixa = 0; faixa < 6; faixa++) for (const lote of [false, true])
    m.setFilter(`hexagonos-${lote ? "lote-" : ""}faixa-${faixa}`, filtroFaixaHexagonos(legenda, faixa, lote, selecionados))
}

export function camadasHexagonos(): LayerSpecification[] {
  const fills: LayerSpecification[] = []
  for (let faixa = 0; faixa < 6; faixa++) for (const lote of [false, true]) fills.push({
    id: `hexagonos-${lote ? "lote-" : ""}faixa-${faixa}`, type: "fill", source: "hexagonos", filter: ["==", ["get", "h3"], ""],
    paint: { "fill-color": CORES_H3_V2[faixa], "fill-opacity": lote ? 0 : 0.92, "fill-antialias": false, "fill-opacity-transition": { duration: 300 } },
  })
  return [
    // Superfície transparente só para toque/hover. As seis cores constantes compartilham o programa gráfico da base.
    { id: "hexagonos", type: "fill", source: "hexagonos", paint: { "fill-color": CORES_H3_V2[0], "fill-opacity": 0, "fill-antialias": false } },
    ...fills,
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
