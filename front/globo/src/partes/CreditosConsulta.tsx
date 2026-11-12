import { useEffect, useRef, useState } from "react"
import type { CompraConsulta, PlanosConsulta, SaldoConsulta } from "../../../compartilhado/prospeccao"
import { dataTerra, numeroTerra, prospeccao } from "../prospeccao"
import { useSessao } from "../pedidos"

export function CreditosConsulta({ revisao = 0 }: { revisao?: number }) {
  const sessao = useSessao()
  const [planos, setPlanos] = useState<PlanosConsulta | null>(null)
  const [saldo, setSaldo] = useState<SaldoConsulta | null>(null)
  const [compra, setCompra] = useState<CompraConsulta | null>(null)
  const [historicoCarregado, setHistoricoCarregado] = useState(false)
  const [tentativaHistorico, setTentativaHistorico] = useState(0)
  const [historico, setHistorico] = useState<CompraConsulta[]>([])
  const [ocupado, setOcupado] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const chaves = useRef(new Map<string, string>())
  const tokenAtual = useRef(sessao?.token)
  tokenAtual.current = sessao?.token
  useEffect(() => {
    setCompra(null); setHistorico([]); setErro(null); setOcupado(false); setSaldo(null); setHistoricoCarregado(false); chaves.current.clear()
    if (!sessao || !prospeccao.disponivel) return
    let vivo = true
    prospeccao.compras().then((h) => { if (vivo) { setHistorico(h); setHistoricoCarregado(true) } }, (e: Error) => vivo && setErro(e.message))
    return () => { vivo = false }
  }, [sessao?.token, tentativaHistorico])
  useEffect(() => {
    if (!prospeccao.disponivel) return
    let vivo = true
    prospeccao.planos().then((p) => vivo && setPlanos(p), (e: Error) => vivo && setErro(e.message))
    if (sessao) prospeccao.saldo().then((s) => vivo && setSaldo(s), (e: Error) => vivo && setErro(e.message))
    else setSaldo(null)
    return () => { vivo = false }
  }, [sessao?.token, revisao, tentativaHistorico])
  async function comprar(id: string) {
    const pendente = historico.find((c) => c.plano === id && c.estado === "pendente")
    if (pendente) { setCompra(pendente); return }
    const token = sessao?.token
    setOcupado(true); setErro(null)
    // Repetir depois de falha de rede não cria outra cobrança.
    if (!chaves.current.has(id)) chaves.current.set(id, crypto.randomUUID())
    try {
      const c = await prospeccao.comprar(id, chaves.current.get(id)!)
      if (tokenAtual.current !== token) return
      setCompra(c)
      setHistorico((h) => [c, ...h.filter((x) => x.id !== c.id)])
      if (c.estado !== "pendente") chaves.current.delete(id)
    }
    catch (e) { if (tokenAtual.current === token) setErro((e as Error).message) }
    finally { if (tokenAtual.current === token) setOcupado(false) }
  }
  async function conferir() {
    if (!compra) return
    const token = sessao?.token
    setOcupado(true); setErro(null)
    try {
      const c = await prospeccao.compra(compra.id)
      if (tokenAtual.current !== token) return
      setCompra(c)
      setHistorico((h) => h.map((x) => x.id === c.id ? c : x))
      if (c.estado !== "pendente") chaves.current.delete(c.plano)
      if (c.estado === "paga") { const s = await prospeccao.saldo(); if (tokenAtual.current === token) setSaldo(s) }
    } catch (e) { if (tokenAtual.current === token) setErro((e as Error).message) }
    finally { if (tokenAtual.current === token) setOcupado(false) }
  }
  return <section className="creditos-consulta" aria-labelledby="creditos-titulo">
    <h2 id="creditos-titulo">Créditos para consultar fichas</h2>
    <p>O agregado e a situação básica no mapa são abertos. Cada ficha completa usa {planos?.custo_ficha ?? 1} crédito de consulta pago. Consultar uma ficha já desbloqueada não cobra outra vez.</p>
    {saldo && <p role="status"><strong>{numeroTerra(saldo.creditos)} créditos disponíveis</strong>. {numeroTerra(saldo.fichas_desbloqueadas)} {saldo.fichas_desbloqueadas === 1 ? "ficha desbloqueada" : "fichas desbloqueadas"}.</p>}
    {!prospeccao.disponivel ? <p>Compras e fichas completas estarão disponíveis quando a conexão com a Raíz estiver ativa.</p> : <>
      {planos?.mensagem && <p>{planos.mensagem}</p>}
      {!!planos?.planos.length && <ul className="planos-consulta">{planos.planos.map((p) => <li key={p.id}>
        <strong>{p.nome}</strong><span>{numeroTerra(p.creditos)} {p.creditos === 1 ? "crédito" : "créditos"}{p.valor_rs == null || p.status === "provisorio" ? ": preço a definir pelo fundador" : ` por ${p.valor_rs.toLocaleString("pt-BR", { style: "currency", currency: "BRL" })}`}</span>{p.aviso_preco && <small>{p.aviso_preco}</small>}
        <button className="botao" type="button" disabled={!sessao || !planos.pagamento_disponivel || p.valor_rs == null || p.status === "provisorio" || !historicoCarregado || ocupado} onClick={() => comprar(p.id)}>Comprar pelo Pix</button>
      </li>)}</ul>}
      {!!sessao && !historicoCarregado && <p>Conferindo compras anteriores antes de criar outro Pix. {erro && <button className="botao" type="button" onClick={() => setTentativaHistorico((n) => n + 1)}>Tentar carregar minhas compras</button>}</p>}
      {!sessao && <a href="#/entrar">Entrar para comprar créditos</a>}
    </>}
    {!!historico.length && <details><summary>Minhas compras de créditos</summary><ul className="planos-consulta">{historico.map((c) => <li key={c.id}><span>Compra {c.id}: {numeroTerra(c.creditos)} créditos, {c.estado === "paga" ? "paga" : c.estado === "pendente" ? "aguardando pagamento" : "encerrada"}.</span><button className="botao" type="button" disabled={ocupado} onClick={() => setCompra(c)}>Ver compra</button></li>)}</ul></details>}
    {compra && <div className="compra-consulta" role="status">
      <h3>{compra.estado === "paga" ? "Pagamento confirmado" : compra.estado === "pendente" ? "Pix aguardando pagamento" : "Cobrança encerrada"}</h3>
      <p>{numeroTerra(compra.creditos)} créditos. Valor: {compra.valor_rs.toLocaleString("pt-BR", { style: "currency", currency: "BRL" })}.</p>
      {compra.estado === "pendente" && <>
        <p>Vence em {dataTerra(compra.expira_em)}. O saldo muda depois da confirmação do pagamento.</p>
        {compra.pix_copia_cola && <label className="campo"><span>Pix copia e cola</span><textarea readOnly value={compra.pix_copia_cola} onFocus={(e) => e.target.select()} /></label>}
        <button className="botao" type="button" disabled={ocupado} onClick={conferir}>{ocupado ? "Conferindo" : "Conferir pagamento"}</button>
      </>}
    </div>}
    {erro && <p className="erro-campo" role="alert">{erro}</p>}
  </section>
}
