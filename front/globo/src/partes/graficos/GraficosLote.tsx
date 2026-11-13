import { Component, lazy, Suspense, useId, useMemo, useState, type ReactNode } from "react"
import { chaveReferencia, lerResultadosGraficos, type ComparacaoMetodo, type FonteResultado, type MedidaConfirmada, type ReferenciaResultado, type ResultadosGraficos } from "../../../../compartilhado/graficos-resultados"
import { dataResultado, nomeMetodo, numeroResultado, TITULOS_SERIES } from "./modelos"
import "./graficos.css"

const ContratosECharts = lazy(() => import("./ContratosECharts"))
const FaixasVega = lazy(() => import("./FaixasVega"))
const CAMPOS = ["contratado", "emitido", "entregue"] as const
class ProtecaoGrafico extends Component<{ children: ReactNode }, { erro: boolean }> {
  state = { erro: false }
  static getDerivedStateFromError() { return { erro: true } }
  render() { return this.state.erro ? <p role="alert">O gráfico não carregou. Os dados continuam na tabela. Recarregue a página para tentar novamente.</p> : this.props.children }
}
function AbrirGrafico({ titulo, children }: { titulo: string; children: ReactNode }) {
  const [aberto, setAberto] = useState(false), id = useId()
  return <div className="painel-grafico"><button type="button" className="botao" aria-expanded={aberto} aria-controls={id} onClick={() => setAberto(!aberto)}>{aberto ? "Fechar gráfico" : `Abrir gráfico: ${titulo}`}</button><div id={id}>{aberto && <ProtecaoGrafico><Suspense fallback={<p role="status">Carregando o gráfico…</p>}>{children}</Suspense></ProtecaoGrafico>}</div></div>
}
function Referencia({ dado }: { dado: ReferenciaResultado }) {
  return <p className="resultado-referencia">{dado.classe === "flag" ? "Meta FLAG" : "Crédito de carbono"}. {dado.metrica.replaceAll("_", " ")}, {dado.unidade}. {dado.escala === "por_hectare" ? "Por hectare" : `Base de ${numeroResultado(dado.area_base_ha)} ha do lote`}. De {dataResultado(dado.inicio)} a {dataResultado(dado.fim)}; horizonte de {numeroResultado(dado.horizonte_dias)} dias.</p>
}
function Fonte({ dado }: { dado: FonteResultado }) {
  return <small>Fonte: {dado.nome}. Data: <time dateTime={dado.data}>{dataResultado(dado.data)}</time>. Registro: <code>{dado.registro_id}</code>.</small>
}
function Medida({ dado }: { dado: MedidaConfirmada | null }) { return dado ? <><strong>{numeroResultado(dado.valor)}</strong><Fonte dado={dado.fonte} /></> : <>Sem registro comprovado</> }
function agrupar(comparacoes: ComparacaoMetodo[]) {
  const grupos = new Map<string, ComparacaoMetodo[]>()
  for (const c of comparacoes) { const chave = `${chaveReferencia(c.previsao.referencia)}:${c.avaliacao}`; const grupo = grupos.get(chave) ?? []; grupo.push(c); grupos.set(chave, grupo) }
  return [...grupos].map(([id, itens]) => ({ id, itens }))
}
/** A ficha só monta este componente depois de confirmar acesso. Não consulta endpoint público nem arquivo estático. */
export function GraficosLote({ dados, demonstracao = false }: { dados?: ResultadosGraficos | null; demonstracao?: boolean }) {
  const estado = useMemo(() => {
    if (!dados) return { dado: null, erro: false }
    try { const dado = lerResultadosGraficos(dados); return demonstracao !== (dado.origem === "demonstracao") ? { dado: null, erro: true } : { dado, erro: false } }
    catch { return { dado: null, erro: true } }
  }, [dados, demonstracao])
  const [serieId, setSerieId] = useState(""), [grupoId, setGrupoId] = useState("")
  const series = estado.dado?.contratos.filter((s) => s.marcos.length) ?? []
  const serie = series.find((s) => s.id === serieId) ?? series[0]
  const grupos = useMemo(() => agrupar(estado.dado?.comparacoes ?? []), [estado.dado])
  const grupo = grupos.find((g) => g.id === grupoId) ?? grupos[0], faixa = grupo?.itens[0]
  return <section className="graficos-lote" aria-label="Acompanhamento dos resultados">
    <h2>Acompanhamento dos resultados</h2>
    <p>Estimativa, contrato, emissão e entrega são etapas diferentes. As séries usam somente registros comprovados; ausência não é zero.</p>
    {(demonstracao || estado.dado?.origem === "demonstracao") && <p className="aviso"><strong>Demonstração sintética.</strong> Estes registros não representam contratos, emissões, entregas ou observações reais.</p>}
    {estado.erro && <p role="alert">Os registros recebidos não comprovam fontes e períodos compatíveis. Nenhum número foi desenhado.</p>}
    {estado.dado && <p>Dados preparados em <time dateTime={estado.dado.gerado_em}>{dataResultado(estado.dado.gerado_em)}</time>. O gráfico usa os mesmos valores das tabelas.</p>}
    <section aria-label="Contratado, emitido e entregue"><h3>Contratado, emitido e entregue</h3>
      {!serie?.marcos.length ? <p>A série ainda não foi fornecida pela API autorizada. A previsão de créditos não comprova contrato assinado, emissão no registro ou entrega ao comprador.</p> : <>
        {series.length > 1 && <label className="campo">Série do contrato<select value={serie.id} onChange={(e) => setSerieId(e.target.value)}>{series.map((s) => <option key={s.id} value={s.id}>{nomeMetodo(s.metodo)}: {s.id}</option>)}</select></label>}
        <p><strong>{nomeMetodo(serie.metodo)}</strong>. Valores acumulados em cada data, sem somar as três etapas.</p><Referencia dado={serie.referencia} />
        <AbrirGrafico key={serie.id} titulo="contratado, emitido e entregue"><ContratosECharts serie={serie} /></AbrirGrafico>
        <div className="tabela-resultados" tabIndex={0} role="region" aria-label="Tabela de contratos, emissões e entregas"><table className="tabela-simples"><caption>Registros acumulados, em {serie.referencia.unidade}</caption><thead><tr><th scope="col">Data do retrato</th>{TITULOS_SERIES.map((t) => <th scope="col" key={t}>{t}</th>)}</tr></thead><tbody>{serie.marcos.map((m) => <tr key={m.data}><th scope="row"><time dateTime={m.data}>{dataResultado(m.data)}</time></th>{CAMPOS.map((c) => <td key={c}><Medida dado={m[c]} /></td>)}</tr>)}</tbody></table></div>
      </>}
    </section>
    <section aria-label="Faixa prevista e resultado real por método"><h3>Faixa prevista e resultado real por método</h3>
      {!faixa ? <p>Ainda não há pares de previsão e observação compatíveis nesta ficha. O placar público informa notas agregadas; ele não contém os valores por método necessários para desenhar esta comparação.</p> : <>
        {grupos.length > 1 && <label className="campo">Período e medida comparáveis<select value={grupo.id} onChange={(e) => setGrupoId(e.target.value)}>{grupos.map((g, i) => { const r = g.itens[0].previsao.referencia; return <option key={g.id} value={g.id}>{i + 1}. {r.metrica.replaceAll("_", " ")}, {r.unidade}, {dataResultado(r.inicio)} a {dataResultado(r.fim)}, {g.itens[0].avaliacao === "ao_vivo" ? "ao vivo" : "retrospectiva"}</option> })}</select></label>}
        <Referencia dado={faixa.previsao.referencia} />
        <p><strong>{faixa.avaliacao === "ao_vivo" ? "Avaliação ao vivo" : "Avaliação retrospectiva"}.</strong> {faixa.avaliacao === "ao_vivo" ? "As previsões foram congeladas antes do dia observado." : "A reexecução declarada não comprova separação entre treino e teste nem acerto em operação ao vivo."} Só comparamos a mesma classe, unidade, área de referência e período. Imóveis e versões diferentes podem explicar as diferenças; o gráfico não escolhe o melhor método.</p>
        <p className="legenda-resultados"><span className="legenda-faixa">Faixa P10 a P90</span><span className="legenda-mediana">Ponto redondo: P50</span><span className="legenda-real">Losango: resultado observado</span></p>
        <AbrirGrafico key={grupo.id} titulo="faixa prevista e resultado real"><FaixasVega comparacoes={grupo.itens} /></AbrirGrafico>
        <div className="tabela-resultados" tabIndex={0} role="region" aria-label="Tabela de previsões e observações"><table className="tabela-simples"><caption>Previsão e observação, em {faixa.previsao.referencia.unidade}</caption><thead><tr><th scope="col">Método e versão</th><th scope="col">P10</th><th scope="col">P50</th><th scope="col">P90</th><th scope="col">Observado</th></tr></thead><tbody>{grupo.itens.map((c, i) => <tr key={c.id}><th scope="row">{i + 1}. {nomeMetodo(c.metodo)}<small>{c.modelo}, versão {c.versao}</small><small>Corte: {dataResultado(c.previsao.corte)}. Congelada em {dataResultado(c.previsao.congelada_em)}.</small><Fonte dado={c.previsao.fonte} /></th><td>{numeroResultado(c.previsao.p10)}</td><td>{numeroResultado(c.previsao.p50)}</td><td>{numeroResultado(c.previsao.p90)}</td><td><strong>{numeroResultado(c.observado.valor)}</strong><small>Observado em {dataResultado(c.observado.data)}; registrado em {dataResultado(c.observado.registrado_em)}.</small><Fonte dado={c.observado.fonte} /></td></tr>)}</tbody></table></div>
      </>}
    </section>
  </section>
}
