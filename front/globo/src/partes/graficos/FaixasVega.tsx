import { useEffect, useRef, useState } from "react"
import { compile } from "vega-lite"
import { parse, View } from "vega"
import type { ComparacaoMetodo } from "../../../../compartilhado/graficos-resultados"
import { especificacaoFaixas } from "./modelos"

export default function FaixasVega({ comparacoes }: { comparacoes: ComparacaoMetodo[] }) {
  const elemento = useRef<HTMLDivElement>(null)
  const [erro, setErro] = useState(false)
  useEffect(() => {
    const el = elemento.current
    if (!el) return
    let encerrado = false
    setErro(false)
    // O gráfico usa só a projeção validada da API. Até fontes externas do runtime ficam desabilitadas.
    const negar = async (): Promise<never> => { throw new Error("Fonte externa não permitida no gráfico.") }
    const semRede = { http: negar, file: negar, load: async () => { throw new Error("Fonte externa não permitida no gráfico.") }, sanitize: async () => { throw new Error("Link externo não permitido no gráfico.") } }
    let view: View | undefined
    try {
      view = new View(parse(compile(especificacaoFaixas(comparacoes, el.clientWidth)).spec), { renderer: "svg", loader: semRede }).initialize(el)
      view.runAsync().catch(() => { if (!encerrado) setErro(true) })
    } catch { setErro(true) }
    const tamanho = new ResizeObserver(() => {
      if (view && !encerrado) view.width(Math.max(160, el.clientWidth)).runAsync().catch(() => { if (!encerrado) setErro(true) })
    })
    tamanho.observe(el)
    return () => { encerrado = true; tamanho.disconnect(); view?.finalize(); el.replaceChildren() }
  }, [comparacoes])
  return <>{erro && <p role="alert">Não foi possível desenhar as faixas. Consulte os registros na tabela abaixo.</p>}<div ref={elemento} className="resultado-grafico faixas-grafico" aria-hidden="true" /></>
}
