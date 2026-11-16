import { useEffect, useId, useRef, useState, type ReactNode } from "react"
import { ErroProspeccao, type FichaTerraDados, type MedidaTerra } from "../../../compartilhado/prospeccao"
import { UFS } from "../../../compartilhado/formato"
import { NOME_RISCO, type Risco } from "../../../compartilhado/terra"
import { useSessao } from "../pedidos"
import { dataTerra, numeroTerra, prospeccao } from "../prospeccao"
import { linkFazenda } from "../rota"
import "./CompararFazendas.css"

/** Valida a seleção sem consultar, desbloquear ou debitar nenhuma ficha. */
export function lerCodigosComparacao(texto: string): { codigos: string[]; erro: string | null } {
  const linhas = texto.split(/[\n,;]+/).map((l) => l.trim()).filter(Boolean)
  const codigos: string[] = []
  for (const linha of linhas) {
    const n = linha.toUpperCase().replace(/[\s.-]/g, "")
    if (!/^[A-Z]{2}\d{7}[A-F0-9]{32}$/.test(n) || !(n.slice(0, 2) in UFS))
      return { codigos: [], erro: "Confira os códigos do CAR: use a sigla do estado, o código do município e os 32 caracteres finais." }
    const car = `${n.slice(0, 2)}-${n.slice(2, 9)}-${n.slice(9)}`
    if (!codigos.includes(car)) codigos.push(car)
  }
  return { codigos, erro: codigos.length < 2 ? "Informe pelo menos dois códigos do CAR diferentes." : codigos.length > 5 ? "Compare no máximo cinco fazendas de cada vez." : null }
}
function MedidaComparada({ dado }: { dado: MedidaTerra | undefined }) {
  if (!dado) return <span>Não informado</span>
  return <div className="comparacao-medida"><strong>{numeroTerra(dado.valor)}{dado.valor === null ? "" : ` ${dado.unidade}`}</strong>
    <small>{dado.estimado ? "Estimativa. " : ""}Fonte: {dado.fonte || "não informada"}.</small>
    <small>{dado.data_referencia ? `Referência: ${dataTerra(dado.data_referencia)}.` : "Data da fonte não informada."}{dado.data_corte ? ` Corte da base: ${dataTerra(dado.data_corte)}.` : ""}</small>
  </div>
}
function Origem({ fonte, data }: { fonte: string; data: string | null }) {
  return <small>Fonte: {fonte || "não informada"}. {data ? `Referência: ${dataTerra(data)}.` : "Data da fonte não informada."}</small>
}
type LinhaComparacao = { chave: string; titulo: string; celula: (ficha: FichaTerraDados) => ReactNode }
function TabelaComparacao({ fichas, linhas, titulo }: { fichas: FichaTerraDados[]; linhas: LinhaComparacao[]; titulo: string }) {
  return <div className="comparacao-rolagem" role="region" aria-label={titulo} tabIndex={0}><table className="comparacao-tabela">
    <caption>{titulo}</caption><thead><tr><th scope="col">Dado da terra</th>{fichas.map((f) => <th scope="col" key={f.codigo_car}><a href={linkFazenda(f.codigo_car)}><code>{f.codigo_car}</code></a><span>{f.municipio}, {f.uf}</span></th>)}</tr></thead>
    <tbody>{linhas.map((l) => <tr key={l.chave}><th scope="row">{l.titulo}</th>{fichas.map((f) => <td key={f.codigo_car}>{l.celula(f)}</td>)}</tr>)}</tbody>
  </table></div>
}
function linhasPrincipais(fichas: FichaTerraDados[]): LinhaComparacao[] {
  const linhas: LinhaComparacao[] = [
    { chave: "bioma", titulo: "Bioma", celula: (f) => f.bioma ?? "Não informado" },
    { chave: "area", titulo: "Área da fazenda", celula: (f) => <MedidaComparada dado={f.area_total} /> },
    { chave: "restauravel", titulo: "Quanto pode voltar a ser mata", celula: (f) => <MedidaComparada dado={f.area_restauravel} /> },
    { chave: "caminho", titulo: "Caminho da terra", celula: (f) => <div className="comparacao-medida"><strong>{f.caminho_terra.rotulo}</strong><Origem fonte={f.caminho_terra.fonte} data={f.caminho_terra.data_referencia} /></div> },
    { chave: "pendencias", titulo: "Pendências", celula: (f) => f.pendencias.length ? <ul>{f.pendencias.map((p) => <li key={p.codigo}>{p.texto}</li>)}</ul> : "Nenhuma pendência registrada." },
    { chave: "embargos", titulo: "Área embargada", celula: (f) => <MedidaComparada dado={f.embargos.area} /> },
    { chave: "risco", titulo: "Risco da terra", celula: (f) => <div className="comparacao-medida"><strong>{NOME_RISCO[f.risco.nivel as Risco] ?? "Não informado"}</strong><Origem fonte={f.risco.fonte} data={f.risco.data_referencia} /></div> },
    { chave: "base_credito", titulo: "Período dos créditos líquidos", celula: (f) => f.credito.base === "liquido_contrato" ? "Ao longo do contrato" : f.credito.base === "liquido_anual" ? "Por ano" : "Ainda não calculado" },
  ]
  for (const p of ["p10", "p50", "p90"] as const) linhas.push({ chave: `credito_${p}`, titulo: `Crédito líquido ${p.toUpperCase()}`, celula: (f) => <MedidaComparada dado={f.credito[p]} /> })
  linhas.push({ chave: "tipo_tir", titulo: "Premissa da TIR", celula: (f) => f.tir.tipo === "com_financiamento" ? "Com financiamento" : "Sem financiamento" })
  for (const p of ["p10", "p50", "p90"] as const) linhas.push({ chave: `tir_${p}`, titulo: `TIR ${p.toUpperCase()}`, celula: (f) => <MedidaComparada dado={f.tir[p]} /> })
  const sobreposicoes = new Map(fichas.flatMap((f) => f.sobreposicoes.map((s) => [s.codigo, s.rotulo] as const)))
  for (const [codigo, rotulo] of sobreposicoes) linhas.push({ chave: `sobreposicao_${codigo}`, titulo: rotulo, celula: (f) => <MedidaComparada dado={f.sobreposicoes.find((s) => s.codigo === codigo)?.area} /> })
  linhas.push({ chave: "agrupar", titulo: "Agrupar com outras fazendas", celula: (f) => f.agrupamento.pequena ? "Fazenda pequena: pode compor um grupo." : f.agrupamento.pequena === null ? "Porte não informado. Pode compor um lote." : "Pode compor um lote." })
  return linhas
}
function linhasHistorico(fichas: FichaTerraDados[]): LinhaComparacao[] {
  const linhas: LinhaComparacao[] = []
  const anos = [...new Set(fichas.flatMap((f) => f.serie_uso.map((s) => s.ano)))].sort((a, b) => a - b)
  for (const ano of anos) for (const [coluna, rotulo] of [["mata", "Mata"], ["pasto", "Pasto"], ["lavoura", "Lavoura"], ["agua", "Água"]] as const)
    linhas.push({ chave: `${ano}_${coluna}`, titulo: `${rotulo} em ${ano}`, celula: (f) => <MedidaComparada dado={f.serie_uso.find((s) => s.ano === ano)?.[coluna]} /> })
  const perdas = new Map(fichas.flatMap((f) => f.perdas.map((p) => [`${p.tipo}:${p.ano}`, p] as const)))
  for (const [chave, perda] of perdas) linhas.push({ chave: `perda_${chave}`, titulo: `${perda.rotulo}${perda.ano === null ? "" : ` em ${perda.ano}`}`, celula: (f) => <MedidaComparada dado={f.perdas.find((p) => p.tipo === perda.tipo && p.ano === perda.ano)?.area} /> })
  return linhas
}
/** A comparação usa somente fichas já liberadas; jamais chama o desbloqueio. */
export function CompararFazendas() {
  const sessao = useSessao()
  const id = useId()
  const [texto, setTexto] = useState("")
  const [fichas, setFichas] = useState<FichaTerraDados[]>([])
  const [erro, setErro] = useState<string | null>(null)
  const [faltam, setFaltam] = useState<string[]>([])
  const [ocupado, setOcupado] = useState(false)
  const chamada = useRef<AbortController | null>(null)
  useEffect(() => {
    chamada.current?.abort(); setFichas([]); setErro(null); setFaltam([]); setOcupado(false)
    return () => { chamada.current?.abort() }
  }, [sessao?.token])
  async function comparar(e: React.FormEvent) {
    e.preventDefault()
    const selecao = lerCodigosComparacao(texto)
    setFichas([]); setFaltam([]); setErro(selecao.erro)
    if (selecao.erro) return
    chamada.current?.abort()
    const ctrl = new AbortController()
    chamada.current = ctrl
    setOcupado(true)
    try {
      const r = await prospeccao.comparar(selecao.codigos, ctrl.signal)
      if (ctrl.signal.aborted) return
      const porCar = new Map(r.fichas.map((f) => [f.codigo_car, f]))
      if (selecao.codigos.some((car) => !porCar.has(car))) throw new Error("A comparação não retornou todas as fichas. Tente novamente.")
      setFichas(selecao.codigos.map((car) => porCar.get(car)!))
    } catch (e) {
      if (ctrl.signal.aborted) return
      setErro((e as Error).message)
      if (e instanceof ErroProspeccao && e.status === 402) setFaltam(selecao.codigos)
    } finally { if (!ctrl.signal.aborted) setOcupado(false) }
  }
  const historico = linhasHistorico(fichas)
  return <section className="comparar-fazendas" aria-labelledby={`${id}-titulo`}>
    <h2 id={`${id}-titulo`}>Comparar fazendas</h2><p>Veja de duas a cinco fichas já desbloqueadas lado a lado. Esta comparação não gasta créditos.</p>
    {!prospeccao.disponivel ? <p>A comparação estará disponível quando a conexão com a Raíz estiver ativa.</p> : !sessao ? <p><a href="#/entrar">Entre na Raíz</a> para comparar as fichas que você desbloqueou.</p> : <form className="formulario" onSubmit={comparar}>
      <label className="campo" htmlFor={`${id}-cars`}><span>Códigos do CAR para comparar</span><textarea id={`${id}-cars`} value={texto} rows={5} autoCapitalize="characters" spellCheck={false} aria-describedby={`${id}-ajuda`} onChange={(e) => {
        chamada.current?.abort(); setOcupado(false); setTexto(e.target.value); setFichas([]); setFaltam([]); setErro(null)
      }} /></label>
      <p id={`${id}-ajuda`} className="legenda-frase">Um código completo por linha. Para liberar uma ficha nova, abra a ficha individual e use um crédito de consulta.</p>
      <button className="botao" type="submit" disabled={ocupado}>{ocupado ? "Comparando" : "Comparar fichas liberadas"}</button>
    </form>}
    {erro && <p className="erro-campo" role="alert">{erro}</p>}
    {!!faltam.length && <div><p>Confira o acesso nas fichas individuais e desbloqueie as que ainda estiverem fechadas:</p><ul>{faltam.map((car) => <li key={car}><a href={linkFazenda(car)}><code>{car}</code></a></li>)}</ul></div>}
    {!!fichas.length && <><p role="status">Comparação pronta. Confira o período de crédito e a premissa de financiamento antes de comparar os valores.</p>
      <p className="legenda-frase">A tabela pode ser deslizada para os lados para ver todas as fazendas.</p>
      <TabelaComparacao fichas={fichas} linhas={linhasPrincipais(fichas)} titulo="Dados e estimativas por fazenda" />
      {!!historico.length && <details><summary>Comparar uso e perdas ao longo dos anos</summary><TabelaComparacao fichas={fichas} linhas={historico} titulo="Histórico de uso e perdas" /></details>}
    </>}
  </section>
}
