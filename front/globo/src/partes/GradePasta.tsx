import { useEffect, useRef } from 'react'
import { Tabulator, SortModule, ResizeColumnsModule, FormatModule } from 'tabulator-tables'
import type { PastaFiadorDados } from '../../../compartilhado/pasta-fiador'
import { linhasPasta } from '../../../compartilhado/pasta-fiador'
import 'tabulator-tables/dist/css/tabulator.min.css'
// Sem download, clipboard, edição ou carga remota. Exportações passam pelo back-end.
Tabulator.registerModule([SortModule, ResizeColumnsModule, FormatModule])
export function GradePasta({ pasta }: { pasta: PastaFiadorDados }) {
  const elemento = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!elemento.current) return
    const grade = new Tabulator(elemento.current, {
      data: linhasPasta(pasta), layout: 'fitColumns', maxHeight: 420, placeholder: 'Nenhum imóvel conferido.',
      columns: [
        { title: 'CAR', field: 'car', minWidth: 220 }, { title: 'Área elegível', field: 'area', minWidth: 140 },
        { title: 'Estágio', field: 'estagio', minWidth: 150 }, { title: 'Título em nível', field: 'titulo', minWidth: 170 },
        { title: 'Documento', field: 'documento', minWidth: 240 }, { title: 'Validade', field: 'validade', minWidth: 150 },
        { title: 'Situação do documento', field: 'estado_documento', minWidth: 170 },
      ].map((c) => ({ ...c, formatter: 'plaintext' as const, headerSort: true })),
    })
    grade.on('tableBuilt', () => {
      // O contêiner rolável do Tabulator é focável, mas vem sem papel ARIA.
      // A hierarquia real passa a ser grid > rowgroup > row, inclusive ao rolar com teclado.
      elemento.current?.removeAttribute('aria-owns')
      elemento.current?.querySelector('.tabulator-tableholder')?.setAttribute('role', 'rowgroup')
      elemento.current?.querySelector('.tabulator-table')?.setAttribute('role', 'presentation')
      for (const coluna of grade.getColumns()) {
        const cabecalho = coluna.getElement()
        cabecalho.tabIndex = 0
        cabecalho.addEventListener('keydown', (evento) => {
          if (evento.key === 'Enter' || evento.key === ' ') { evento.preventDefault(); cabecalho.click() }
        })
      }
    })
    return () => grade.destroy()
  }, [pasta])
  return <div className="pasta-grade" ref={elemento} aria-label="Grade da pasta: área, estágio, documento e validade" />
}
