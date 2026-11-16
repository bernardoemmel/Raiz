import { useEffect, useId, useRef, useState } from "react"
import { fmtHa, fmtInt } from "../../../../compartilhado/formato"
import { ROTULO_OPCAO, fmtUsd } from "../../../../compartilhado/pedidos/texto"
import { PARAMETROS_SENSIBILIDADE, conferirParametrosSensibilidade, type ConsultarSensibilidade, type ParametrosSensibilidade, type ResultadoSensibilidade } from "../../../../compartilhado/pedidos/sensibilidade"
import "./sensibilidade.css"

const percentual = (n: number) => new Intl.NumberFormat("pt-BR", { style: "percent", maximumFractionDigits: 2 }).format(n)

/** Só montar na área logada ou na demonstração explícita; a consulta é injetada pelo adaptador da API. */
export function SensibilidadeLote({ consultar, demonstracao = false }: { consultar: ConsultarSensibilidade; demonstracao?: boolean }) {
  const id = useId()
  const [preco, setPreco] = useState("55")
  const [reserva, setReserva] = useState("20")
  const [taxa, setTaxa] = useState("9.2")
  const [pessimista, setPessimista] = useState(false)
  const [resultado, setResultado] = useState<ResultadoSensibilidade | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const sequencia = useRef(0)
  const [alterado, setAlterado] = useState(false)
  useEffect(() => () => { sequencia.current++ }, [])
  function alterar(f: () => void) {
    sequencia.current++
    setOcupado(false)
    setAlterado(true)
    setErro(null)
    f()
  }
  async function calcular(parametros: ParametrosSensibilidade) {
    const atual = ++sequencia.current
    setErro(null)
    setResultado(null)
    try {
      conferirParametrosSensibilidade(parametros)
      setOcupado(true)
      const r = await consultar(parametros)
      if (atual === sequencia.current) {
        setResultado(r)
        setAlterado(false)
      }
    } catch (e) {
      if (atual === sequencia.current) setErro(e instanceof Error ? e.message : "Não foi possível consultar a sensibilidade.")
    } finally {
      if (atual === sequencia.current) setOcupado(false)
    }
  }
  function restaurar() {
    alterar(() => { setPreco("55"); setReserva("20"); setTaxa("9.2"); setPessimista(false) })
    void calcular({ ...PARAMETROS_SENSIBILIDADE })
  }
  return <section className="secao-painel sensibilidade-lote" aria-labelledby={`${id}-titulo`}>
    <h2 id={`${id}-titulo`}>Sensibilidade dos três lotes</h2>
    <p>Mude as premissas e compare os créditos e o retorno de cada opção. A taxa de desconto altera o valor presente líquido (VPL); ela não altera a TIR de um mesmo fluxo.</p>
    {demonstracao && <p className="aviso"><strong>Demonstração com números fictícios. Os resultados não são os lotes do Pará.</strong></p>}
    <form onSubmit={(e) => { e.preventDefault(); void calcular({ preco_credito_usd: Number(preco), reserva_reversao: Number(reserva) / 100, taxa_desconto: Number(taxa) / 100, pessimista }) }}>
      <fieldset>
        <legend>Premissas da comparação</legend>
        <label htmlFor={`${id}-preco`}>Preço do crédito (US$)
          <input id={`${id}-preco`} type="number" min="0.01" max="1000" step="0.01" required value={preco} onChange={(e) => alterar(() => setPreco(e.target.value))} />
        </label>
        <label htmlFor={`${id}-reserva`}>Reserva contra reversão (%)
          <input id={`${id}-reserva`} type="number" min="20" max="90" step="0.1" required value={reserva} onChange={(e) => alterar(() => setReserva(e.target.value))} aria-describedby={`${id}-piso`} />
        </label>
        <p id={`${id}-piso`} className="legenda-frase">Piso de 20%. A parcela reservada não pode ser vendida; riscos específicos podem exigir mais reserva no motor.</p>
        <label htmlFor={`${id}-taxa`}>Taxa de desconto (% ao ano)
          <input id={`${id}-taxa`} type="number" min="0" max="50" step="0.1" required value={taxa} onChange={(e) => alterar(() => setTaxa(e.target.value))} />
        </label>
        <label className="sensibilidade-pessimista"><input type="checkbox" checked={pessimista} onChange={(e) => alterar(() => setPessimista(e.target.checked))} />Cenário pessimista</label>
      </fieldset>
      <div className="sensibilidade-acoes">
        <button className="botao" type="submit" disabled={ocupado}>{ocupado ? "Consultando as três opções" : demonstracao ? "Simular os três exemplos" : "Consultar os três lotes"}</button>
        <button className="botao secundario" type="button" onClick={restaurar}>Restaurar premissas iniciais</button>
      </div>
    </form>
    <div aria-live="polite" aria-atomic="true">
      {erro && <p className="erro-campo" role="alert">{erro}</p>}
      {alterado && <p>Premissas alteradas. Consulte novamente para comparar os resultados.</p>}
      {!resultado && !ocupado && !erro && !alterado && <p>{demonstracao ? "Os controles usam somente dados fictícios desta demonstração." : "A consulta depende da grade de cenários publicada pelo motor. Não estimamos novas respostas a partir do resumo central."}</p>}
      {resultado && !alterado && <p>{resultado.aviso}</p>}
    </div>
    {resultado && !alterado && <>
      <p className="legenda-frase">Fonte: {resultado.fonte}.{resultado.modelo_versao && ` Versão: ${resultado.modelo_versao}.`}{resultado.atualizado_em && ` ${resultado.exemplo ? "Simulação feita" : "Dados publicados"} em ${new Date(resultado.atualizado_em).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" })} (Brasília).`}</p>
      {resultado.estado === "disponivel" && <>
        <p>Premissas aplicadas: {fmtUsd(resultado.parametros.preco_credito_usd)} por crédito; reserva de {percentual(resultado.parametros.reserva_reversao)}; desconto de {percentual(resultado.parametros.taxa_desconto)} ao ano; cenário {resultado.parametros.pessimista ? "pessimista" : "central"}.</p>
        <div className="tabela-rolagem" role="region" tabIndex={0} aria-label="Sensibilidade dos lotes, deslize para comparar">
          <table className="tabela-simples tabela-comparacao">
            <caption>{resultado.exemplo ? "Comparação fictícia, meta ilustrativa de 1 milhão de créditos" : "Comparação nas premissas consultadas"}</caption>
            <thead><tr><th scope="col">Medida</th>{resultado.opcoes.map((o) => <th key={o.id} scope="col">{ROTULO_OPCAO[o.id].nome}</th>)}</tr></thead>
            <tbody>
              {(["p10", "p50", "p90"] as const).map((q) => <tr key={q}><th scope="row">Créditos {q.toUpperCase()} (t CO2e)</th>{resultado.opcoes.map((o) => <td key={o.id}>{fmtInt(o.creditos[q])}</td>)}</tr>)}
              <tr><th scope="row">VPL (US$)</th>{resultado.opcoes.map((o) => <td key={o.id}>{o.vpl_usd === null ? "Não calculado" : fmtUsd(o.vpl_usd)}</td>)}</tr>
              <tr><th scope="row">TIR do projeto</th>{resultado.opcoes.map((o) => <td key={o.id}>{o.tir_projeto === null ? "Não definida" : percentual(o.tir_projeto)}</td>)}</tr>
              <tr><th scope="row">Área para restaurar</th>{resultado.opcoes.map((o) => <td key={o.id}>{fmtHa(o.hectares)}</td>)}</tr>
              <tr><th scope="row">Fazendas no lote</th>{resultado.opcoes.map((o) => <td key={o.id}>{fmtInt(o.fazendas)}</td>)}</tr>
              <tr><th scope="row">Alcança a meta no P50?</th>{resultado.opcoes.map((o) => <td key={o.id}>{o.alcanca_meta ? "Sim" : "Não"}</td>)}</tr>
            </tbody>
          </table>
        </div>
      </>}
    </>}
  </section>
}
