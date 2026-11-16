import { useEffect, useRef, useState } from 'react'
import type { FontePasta, HistoricoPasta, MedidaPasta, PastaFiadorDados } from '../../../compartilhado/pasta-fiador'
import { numeroPasta, rotuloPasta as rotulo } from '../../../compartilhado/pasta-fiador'
import { prospeccao } from '../prospeccao'
import { pedidos } from '../pedidos'
import { Cabecalho } from '../partes/Cabecalho'
import { GradePasta } from '../partes/GradePasta'
import { linkFazenda, linkPedido } from '../rota'
import './pasta-fiador.css'
function Fontes({ fontes }: { fontes: FontePasta[] }) {
  return <ul className="pasta-fontes">{fontes.map((f, n) => <li key={`${f.documento_id}-${n}`}>Documento {f.documento_id}; {f.localizador}; referência {f.data_referencia}</li>)}</ul>
}
function Medida({ dado }: { dado: MedidaPasta | null }) {
  return <>{dado?.valor == null ? 'Não informado' : `${numeroPasta(dado.valor)} ${dado.unidade}; ${dado.natureza}`}<Fontes fontes={dado?.fontes ?? []} /></>
}
export function PastaFiador({ id, opcaoInicial = "segura" }: { id: string; opcaoInicial?: string }) {
  const [opcao, setOpcao] = useState(opcaoInicial), [versao, setVersao] = useState('')
  const [pasta, setPasta] = useState<PastaFiadorDados | null>(null)
  const [historico, setHistorico] = useState<HistoricoPasta | null>(null)
  const [erro, setErro] = useState(''), [ocupado, setOcupado] = useState(false), [carregando, setCarregando] = useState(true)
  const vida = useRef<AbortController | null>(null)
  useEffect(() => {
    const controle = new AbortController(); vida.current = controle
    setPasta(null); setHistorico(null); setErro(''); setCarregando(true); setOcupado(false)
    Promise.all([prospeccao.pasta(id, opcao, versao || undefined, controle.signal), prospeccao.historicoPasta(id, opcao, controle.signal)])
      .then(([p, h]) => { if (!controle.signal.aborted) { setPasta(p); setHistorico(h) } })
      .catch((e: Error) => { if (!controle.signal.aborted) setErro(e.message) })
      .finally(() => { if (!controle.signal.aborted) setCarregando(false) })
    return () => controle.abort()
  }, [id, opcao, versao])
  async function exportar() {
    const controle = vida.current; const token = pedidos.sessao()?.token
    if (!controle || controle.signal.aborted) return
    setOcupado(true); setErro('')
    try {
      const blob = await prospeccao.exportarPasta(id, opcao, controle.signal)
      if (controle.signal.aborted || pedidos.sessao()?.token !== token) return
      const url = URL.createObjectURL(blob); const a = document.createElement('a')
      a.href = url; a.download = 'pasta-banco-comprador.zip'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (e) { if (!controle.signal.aborted) setErro((e as Error).message) }
    finally { if (!controle.signal.aborted) setOcupado(false) }
  }
  return <><Cabecalho atual="pedidos" /><main id="conteudo" className="pagina pasta-pagina">
    <a href={linkPedido(id)}>Voltar ao pedido</a><h1>Pasta do banco e do comprador</h1>
    <p>O mesmo lote, duas apresentações. Crédito por método, título em nível e documentos conferidos, com fonte e data.</p>
    <div className="pasta-comandos"><label>Opção do lote<select value={opcao} onChange={(e) => { setOpcao(e.target.value); setVersao('') }}><option value="barata">Mais barata</option><option value="segura">Mais segura</option><option value="compacta">Mais compacta</option></select></label>
      <label>Versão<select value={versao} onChange={(e) => setVersao(e.target.value)}><option value="">Atual</option>{historico?.versoes.map((v) => <option key={v.id} value={v.id}>{v.numero}; {rotulo(v.tipo)}; {v.registrada_em.slice(0, 10)}</option>)}</select></label>
      <button className="botao principal" type="button" disabled={!pasta?.validacao.pronto || !!versao || ocupado} onClick={exportar}>{ocupado ? 'Gerando pasta…' : 'Baixar banco + comprador'}</button></div>
    {erro && <p role="alert">{erro}</p>}{carregando && <p role="status">Conferindo a pasta…</p>}
    {pasta && <><section aria-label="Resultado da conferência"><h2>{pasta.validacao.pronto ? 'Conferência concluída' : 'Pasta com pendências'}</h2>
      <p>Versão {pasta.numero}; {rotulo(pasta.tipo_alteracao)}; corte {pasta.dados.data_corte}. Regra {pasta.validacao.regra_versao}.</p>
      <p>Garantia e titularidade são obrigatórias. A conferência da Raíz não é aprovação do banco. Apenas a versão atual pode ser exportada.</p>
      {pasta.validacao.falhas.length > 0 && <ul>{pasta.validacao.falhas.map((f, n) => <li key={n}><strong>{f.campo}</strong>: {f.mensagem}</li>)}</ul>}</section>
      <section><h2>Área, estágio e documentos</h2><GradePasta pasta={pasta} /></section>
      <section><h2>Ficha de cada imóvel no lote</h2><p>Métodos são alternativas. Não some faixas de métodos diferentes sobre a mesma área.</p>
        {pasta.dados.imoveis.map((i) => <article className="pasta-imovel" key={i.codigo_car}><h3><a href={linkFazenda(i.codigo_car)}>{i.codigo_car}</a></h3>
          <div>Área elegível: <Medida dado={i.area_elegivel} /></div><p>Título: {rotulo(i.titulo?.nivel ?? 'não conferido')}; {i.titulo?.situacao ?? 'pendente'}</p><Fontes fontes={i.titulo?.fontes ?? []} />
          <p>Garantia: {i.garantia?.situacao ?? 'pendente'}</p><Fontes fontes={i.garantia?.fontes ?? []} />
          {i.creditos.map((c) => <details key={c.metodo}><summary>{rotulo(c.metodo)}; P50 {numeroPasta(c.p50?.valor)} tCO2e</summary>
            <p>Modelo {c.modelo_versao ?? 'não informado'}; período {c.periodo ? `${c.periodo.inicio} a ${c.periodo.fim}` : 'não informado'}</p><Fontes fontes={c.fontes} />
            <dl>{(['area', 'p10', 'p50', 'p90'] as const).map((q) => <div key={q}><dt>{q.toUpperCase()}</dt><dd><Medida dado={c[q]} /></dd></div>)}</dl></details>)}
          <h4>Preço e origem</h4><p>{numeroPasta(i.preco?.valor)} {i.preco?.moeda ?? 'Moeda não informada'}/{i.preco?.unidade ?? 'unidade não informada'}; {i.preco?.natureza ?? 'natureza não informada'}; {i.preco?.periodo ? `${i.preco.periodo.inicio} a ${i.preco.periodo.fim}` : 'período não informado'}</p><Fontes fontes={i.preco?.fontes ?? []} />
        </article>)}</section>
      <details><summary>Referências e histórico das previsões</summary>{pasta.previsoes.map((p) => <div key={p.referencia}><p>{p.codigo_car}; {rotulo(p.metodo)}; {p.referencia}</p><ul>{p.relacoes.map((r) => <li key={r.tipo}>{r.tipo}: {r.referencia}</li>)}</ul></div>)}</details>
      <p>A exportação contém duas páginas HTML para leitura e impressão, dados e relatório de validação. Cada arquivo traz a marca desta licença. Nenhum contato é exportado.</p>
    </>}
  </main></>
}
