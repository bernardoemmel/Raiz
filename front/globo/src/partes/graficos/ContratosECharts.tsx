import { useEffect, useRef, useState } from "react"
import { init, use } from "echarts/core"
import { LineChart } from "echarts/charts"
import { GridComponent, LegendComponent } from "echarts/components"
import { SVGRenderer } from "echarts/renderers"
import type { SerieContrato } from "../../../../compartilhado/graficos-resultados"
import { opcaoContratos } from "./modelos"

use([LineChart, GridComponent, LegendComponent, SVGRenderer])
export default function ContratosECharts({ serie }: { serie: SerieContrato }) {
  const elemento = useRef<HTMLDivElement>(null)
  const [erro, setErro] = useState(false)
  useEffect(() => {
    if (!elemento.current) return
    setErro(false)
    const grafico = init(elemento.current, undefined, { renderer: "svg" })
    try { grafico.setOption(opcaoContratos(serie)) } catch { setErro(true) }
    const tamanho = new ResizeObserver(() => grafico.resize())
    tamanho.observe(elemento.current)
    return () => { tamanho.disconnect(); grafico.dispose() }
  }, [serie])
  return <>{erro && <p role="alert">Não foi possível desenhar o gráfico. A tabela abaixo conserva os registros.</p>}<div ref={elemento} className="resultado-grafico contratos-grafico" aria-hidden="true" /></>
}
