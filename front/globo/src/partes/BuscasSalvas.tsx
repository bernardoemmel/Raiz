import { useEffect, useRef, useState } from "react"
import { filtrosDaBuscaSalva, type AvisoBusca, type BuscaSalva, type FiltrosProspeccao } from "../../../compartilhado/prospeccao"
import { useSessao } from "../pedidos"
import { dataTerra, prospeccao } from "../prospeccao"
import { linkFazenda } from "../rota"

/** A busca e os avisos pertencem à conta no servidor. Não há alertas simulados ou envio externo. */
export function BuscasSalvas({ filtros, aoAplicar }: { filtros: FiltrosProspeccao; aoAplicar: (f: FiltrosProspeccao) => void }) {
  const sessao = useSessao()
  const [nome, setNome] = useState("")
  const [buscas, setBuscas] = useState<BuscaSalva[]>([])
  const [avisos, setAvisos] = useState<AvisoBusca[]>([])
  const [cursor, setCursor] = useState<number | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const [mensagem, setMensagem] = useState<string | null>(null)
  const controle = useRef<AbortController | null>(null)
  const geracao = useRef(0)
  const mutacao = useRef(false)
  const podeUsar = !!sessao && prospeccao.disponivel

  useEffect(() => {
    if (!podeUsar) return
    const abortar = new AbortController()
    controle.current = abortar
    let consultando = false
    const atualizar = async () => {
      if (consultando || mutacao.current || abortar.signal.aborted) return
      const versao = geracao.current
      consultando = true
      try {
        const [salvas, novas] = await Promise.all([prospeccao.buscasSalvas(abortar.signal), prospeccao.avisos(0, abortar.signal)])
        if (!abortar.signal.aborted && versao === geracao.current) { setBuscas(salvas); setAvisos(novas.avisos); setCursor(novas.proximo_cursor) }
      } catch (e) { if (!abortar.signal.aborted) setErro((e as Error).message) }
      finally { consultando = false }
    }
    void atualizar()
    const intervalo = setInterval(() => { if (document.visibilityState === "visible") void atualizar() }, 60_000)
    return () => { abortar.abort(); clearInterval(intervalo) }
  }, [podeUsar, sessao?.token])

  async function executar(acao: (sinal: AbortSignal) => Promise<void>) {
    const sinal = controle.current?.signal
    if (!sinal || sinal.aborted || mutacao.current) return
    geracao.current++; mutacao.current = true
    setOcupado(true); setErro(null); setMensagem(null)
    try { await acao(sinal) }
    catch (e) { if (!sinal.aborted) setErro((e as Error).message) }
    finally { mutacao.current = false; if (!sinal.aborted) setOcupado(false) }
  }
  const carregarAvisos = (mais: boolean) => executar(async (sinal) => {
    const pagina = await prospeccao.avisos(mais ? cursor ?? 0 : 0, sinal)
    if (sinal.aborted) return
    setAvisos((atuais) => mais ? [...atuais, ...pagina.avisos.filter((novo) => !atuais.some((a) => a.id === novo.id))] : pagina.avisos)
    setCursor(pagina.proximo_cursor)
  })

  return <section className="buscas-salvas secao-painel" aria-labelledby="buscas-salvas-titulo">
    <h2 id="buscas-salvas-titulo">Buscas salvas e avisos</h2>
    <p>Salve os filtros aplicados. Quando a base receber novas fazendas que atendem à busca, o aviso aparece aqui. A primeira gravação usa a base atual como referência.</p>
    {!podeUsar ? <p>{!prospeccao.disponivel ? "Salvar buscas e receber avisos exige conexão com a Raíz." : <a href="#/entrar">Entre para salvar buscas e acompanhar avisos.</a>}</p> : <>
      <form className="formulario abrir-car" onSubmit={(e) => { e.preventDefault(); void executar(async (sinal) => {
        const salva = await prospeccao.salvarBusca(nome.trim(), filtros, sinal)
        if (sinal.aborted) return
        setBuscas((b) => [salva, ...b]); setNome(""); setMensagem("Busca salva. Novas correspondências aparecerão nos avisos após a atualização da base.")
      }) }}>
        <label className="campo"><span>Nome da busca</span><input required maxLength={80} value={nome} onChange={(e) => setNome(e.target.value)} placeholder="Ex.: Áreas no Pará" /></label>
        <button type="submit" className="botao" disabled={ocupado || !nome.trim() || buscas.length >= 20}>Salvar filtros aplicados</button>
      </form>
      <p className="legenda-frase">Até 20 buscas por conta. Este acompanhamento não libera fichas pagas e não envia mensagens a proprietários.</p>
      {!!buscas.length && <ul className="grupos-prospeccao">{buscas.map((busca) => <li key={busca.id}>
        <strong>{busca.nome}</strong><p className="legenda-frase">Salva em {dataTerra(busca.criada_em)}. Última verificação da base: {dataTerra(busca.verificada_em)}.</p>
        <div className="acoes-prospeccao"><button type="button" className="botao" onClick={() => { aoAplicar(filtrosDaBuscaSalva(busca.filtros)); setMensagem(`Filtros de “${busca.nome}” aplicados.`) }}>Aplicar busca {busca.nome}</button>
          <button type="button" className="botao" disabled={ocupado} onClick={() => void executar(async (sinal) => { await prospeccao.excluirBusca(busca.id, sinal); if (!sinal.aborted) { setBuscas((b) => b.filter((x) => x.id !== busca.id)); setAvisos((a) => a.filter((x) => x.busca_id !== busca.id)); setMensagem("Busca excluída.") } })}>Excluir busca {busca.nome}</button></div>
      </li>)}</ul>}
      <div className="secao-cabeca"><h3>Novas fazendas nas buscas</h3><button type="button" className="botao" disabled={ocupado} onClick={() => void carregarAvisos(false)}>Atualizar avisos</button></div>
      {!avisos.length ? <p>Nenhum aviso disponível. As buscas são verificadas quando a base é atualizada.</p> : <ul className="grupos-prospeccao">{avisos.map((aviso) => <li key={aviso.id}>
        <strong>{aviso.nome_busca}{aviso.lida_em ? "" : ": novo aviso"}</strong><p>{aviso.mensagem}</p><p className="car-terra"><a href={linkFazenda(aviso.codigo_car)}>CAR {aviso.codigo_car}</a></p><p className="legenda-frase">Recebido em {dataTerra(aviso.criada_em)}. {aviso.lida_em ? `Lido em ${dataTerra(aviso.lida_em)}.` : "Ainda não lido."}</p>
        {!aviso.lida_em && <button type="button" className="botao" disabled={ocupado} onClick={() => void executar(async (sinal) => { const lido = await prospeccao.lerAviso(aviso.id, sinal); if (!sinal.aborted) setAvisos((a) => a.map((x) => x.id === lido.id ? { ...x, lida_em: lido.lida_em } : x)) })}>Marcar aviso como lido</button>}
      </li>)}</ul>}
      {cursor !== null && <button type="button" className="botao" disabled={ocupado} onClick={() => void carregarAvisos(true)}>Carregar mais avisos</button>}
    </>}
    {mensagem && <p role="status">{mensagem}</p>}{erro && <p className="erro-campo" role="alert">{erro}</p>}
  </section>
}
