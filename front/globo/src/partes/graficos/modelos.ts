import { COR_GRAFICO_V2 as COR } from "../../../../compartilhado/cores"
import type { ComparacaoMetodo, SerieContrato } from "../../../../compartilhado/graficos-resultados"
import type { EChartsCoreOption } from "echarts/core"
import type { TopLevelSpec } from "vega-lite"

export const TITULOS_SERIES = ["Contratado", "Emitido", "Entregue"] as const
const CAMPOS = ["contratado", "emitido", "entregue"] as const
export const numeroResultado = (n: number) => new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 }).format(n)
export const dataResultado = (d: string) => new Date(`${d.slice(0, 10)}T12:00:00Z`).toLocaleDateString("pt-BR", { timeZone: "UTC" })
export function nomeMetodo(metodo: string): string {
  return ({ regeneracao_assistida: "Regeneração assistida", semeadura_direta: "Semeadura direta", plantio_total: "Plantio total", agrofloresta: "Agrofloresta", silvipastoril: "Silvipastoril", regra: "Método da regra", plantio: "Plantio", regeneracao_e_plantio: "Regeneração e plantio" } as Record<string, string>)[metodo] ?? metodo.replaceAll("_", " ")
}
/** Sem preenchimento e sem interpolar ausências: null produz uma lacuna, zero continua sendo zero. */
export function opcaoContratos(serie: SerieContrato): EChartsCoreOption {
  return {
    animation: false,
    backgroundColor: COR.fundo,
    textStyle: { fontFamily: "Bricolage Grotesque, sans-serif", color: COR.texto, fontSize: 14 },
    grid: { left: 12, right: 16, top: 64, bottom: 12, containLabel: true },
    legend: { top: 0, textStyle: { color: COR.texto, fontSize: 14 }, itemWidth: 26, itemHeight: 12 },
    xAxis: { type: "category", data: serie.marcos.map((m) => dataResultado(m.data)), axisLabel: { hideOverlap: true, color: COR.secundario }, axisLine: { lineStyle: { color: COR.secundario } } },
    yAxis: { type: "value", name: serie.referencia.unidade, min: 0, splitNumber: 4, axisLabel: { formatter: numeroResultado, color: COR.secundario }, splitLine: { lineStyle: { color: COR.grade } }, nameTextStyle: { color: COR.secundario } },
    series: CAMPOS.map((campo, i) => ({
      type: "line", name: TITULOS_SERIES[i], data: serie.marcos.map((m) => m[campo]?.valor ?? null),
      connectNulls: false, smooth: false, symbol: ["circle", "diamond", "rect"][i], symbolSize: 8,
      lineStyle: { width: 2, type: ["dashed", "dotted", "solid"][i] },
      itemStyle: { color: [COR.contratado, COR.emitido, COR.entregue][i] },
    })),
  }
}
/** Só valores internos: não aceita spec, expressão, URL nem transformação vinda da API. */
export function especificacaoFaixas(comparacoes: ComparacaoMetodo[], largura: number): TopLevelSpec {
  return {
    width: Math.max(160, largura), height: Math.max(160, comparacoes.length * 52), autosize: { type: "fit-x", contains: "padding" },
    data: { values: comparacoes.map((c, i) => ({ id: c.id, rotulo: `${nomeMetodo(c.metodo)} (${c.versao}; ${i + 1})`, p10: c.previsao.p10, p50: c.previsao.p50, p90: c.previsao.p90, real: c.observado.valor })) },
    encoding: { y: { field: "rotulo", type: "nominal", sort: null, axis: { title: null, labelLimit: largura < 500 ? 95 : 180 } } },
    layer: [
      { mark: { type: "rule", strokeWidth: 8, color: COR.faixa, opacity: 1 }, encoding: { x: { field: "p10", type: "quantitative", title: comparacoes[0]?.previsao.referencia.unidade ?? "Valor", scale: { zero: true } }, x2: { field: "p90" } } },
      // Halo opaco: os símbolos continuam distinguíveis quando ficam sobre a faixa verde (WCAG 1.4.11).
      { mark: { type: "point", filled: true, size: 80, shape: "circle", color: COR.mediana, opacity: 1, stroke: COR.fundo, strokeWidth: 2 }, encoding: { x: { field: "p50", type: "quantitative" } } },
      { mark: { type: "point", filled: true, size: 100, shape: "diamond", color: COR.observado, opacity: 1, stroke: COR.fundo, strokeWidth: 2 }, encoding: { x: { field: "real", type: "quantitative" } } },
    ],
    config: { background: COR.fundo, font: "Bricolage Grotesque, sans-serif", view: { stroke: null }, axis: { labelColor: COR.secundario, titleColor: COR.texto, labelFontSize: 14, titleFontSize: 14, gridColor: COR.grade, domainColor: COR.secundario, tickCount: largura < 500 ? 3 : 5 }, title: { color: COR.texto } },
  }
}
