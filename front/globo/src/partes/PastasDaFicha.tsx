import { useEffect, useRef, useState } from 'react'
import type { PastasDaFichaDados } from '../../../compartilhado/pasta-fiador'
import { numeroPasta, rotuloPasta } from '../../../compartilhado/pasta-fiador'
import { dataTerra, prospeccao } from '../prospeccao'
import { linkPasta, linkPedidos } from '../rota'

/** Só a conta dona do pedido vê esta conferência; nada vai ao snapshot global da ficha. */
export function PastasDaFicha({ car }: { car: string }) {
  const [dados, setDados] = useState<PastasDaFichaDados | null>(null)
  const [erro, setErro] = useState(''), [lendo, setLendo] = useState(false)
  const controle = useRef<AbortController | null>(null)
  useEffect(() => () => controle.current?.abort(), [car])
  async function consultar() {
    controle.current?.abort()
    const novo = new AbortController(); controle.current = novo
    setLendo(true); setErro(''); setDados(null)
    try { const r = await prospeccao.pastasDaFicha(car, novo.signal); if (!novo.signal.aborted) setDados(r) }
    catch (e) { if (!novo.signal.aborted) setErro((e as Error).message) }
    finally { if (!novo.signal.aborted) setLendo(false) }
  }
  return <section><h2>Crédito por método e título nos meus lotes</h2>
    <p>A pasta de cada lote reúne a conferência de título, garantia e previsão. Métodos alternativos sobre a mesma área não se somam.</p>
    <button className="botao" type="button" disabled={lendo} onClick={consultar}>{lendo ? 'Conferindo meus lotes…' : 'Ver a conferência nos meus lotes'}</button>
    {erro && <p role="alert">{erro}</p>}
    {dados && !dados.pastas.length && <p>Esta fazenda ainda não tem pasta disponível nos seus lotes. <a href={linkPedidos}>Abrir meus pedidos</a>.</p>}
    {dados?.pastas.map((p) => <article key={p.pasta_id}><h3><a href={linkPasta(p.pedido_id, p.opcao)}>Lote {rotuloPasta(p.opcao)}, versão {p.numero}</a></h3>
      <p>{p.pronto ? 'Conferência concluída' : 'Pasta com pendências'}. Corte {dataTerra(p.data_corte)}.</p>
      <p>Título em nível: {rotuloPasta(p.imovel.titulo?.nivel ?? 'nao_verificado')}. Situação: {p.imovel.titulo?.situacao ?? 'pendente'}.</p>
      <ul>{p.imovel.titulo?.fontes.map((f, i) => <li key={i}>Documento {f.documento_id}; {f.localizador}; referência {dataTerra(f.data_referencia)}.</li>)}</ul>
      {p.imovel.creditos.map((c) => <details key={c.metodo}><summary>{rotuloPasta(c.metodo)}: P50 {numeroPasta(c.p50?.valor)} tCO₂e</summary>
        <p>Estimativa de {dataTerra(c.periodo?.inicio)} a {dataTerra(c.periodo?.fim)}. Modelo {c.modelo_versao ?? 'não informado'}.</p>
        <dl>{(['p10', 'p50', 'p90'] as const).map((q) => <div key={q}><dt>{q.toUpperCase()}</dt><dd>{numeroPasta(c[q]?.valor)} {c[q]?.unidade}<ul>{c[q]?.fontes.map((f, i) => <li key={i}>Documento {f.documento_id}; {f.localizador}; referência {dataTerra(f.data_referencia)}.</li>)}</ul></dd></div>)}</dl>
      </details>)}
    </article>)}
  </section>
}
