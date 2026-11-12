import { lazy, Suspense, useEffect, useState } from "react"
import { ErroProspeccao, type FichaTerraDados, type MedidaTerra } from "../../../compartilhado/prospeccao"
import { NOME_RISCO, SITUACOES, type Risco } from "../../../compartilhado/terra"
import { LinhaTempoTerra } from "../partes/LinhaTempoTerra"
import { Cabecalho } from "../partes/Cabecalho"
import { CreditosConsulta } from "../partes/CreditosConsulta"
import { Estado } from "../partes/Estado"
import { useSessao } from "../pedidos"
import { dataTerra, numeroTerra, prospeccao } from "../prospeccao"
import { linkMunicipio, linkProspeccao } from "../rota"
import { Entrar } from "./Entrar"

const MapaFichaTerra = lazy(() => import("../mapa/MapaFichaTerra").then((m) => ({ default: m.MapaFichaTerra })))

export function Medida({ dado }: { dado: MedidaTerra }) {
  return <span className="medida-terra">
    <strong>{numeroTerra(dado.valor)}{dado.valor !== null ? ` ${dado.unidade}` : ""}</strong>
    <small>{dado.estimado ? "Estimativa. " : ""}Fonte: {dado.fonte || "Não informada"}.</small>
    <small>{dado.data_referencia ? `Referência: ${dataTerra(dado.data_referencia)}.` : "Data da fonte não informada."}{dado.data_corte ? ` Corte da base: ${dataTerra(dado.data_corte)}.` : ""}</small>
  </span>
}
function Faixas({ titulo, dados }: { titulo: string; dados: { p10: MedidaTerra; p50: MedidaTerra; p90: MedidaTerra } }) {
  return <div className="tabela-terra" tabIndex={0} role="region" aria-label={titulo}><table className="tabela-simples"><caption>{titulo}</caption><thead><tr><th>P10</th><th>P50</th><th>P90</th></tr></thead><tbody><tr>{(["p10", "p50", "p90"] as const).map((p) => <td key={p}><Medida dado={dados[p]} /></td>)}</tr></tbody></table></div>
}
/** A rota antiga da fazenda também entra aqui: nenhum CSV público desbloqueia a ficha. */
export function FichaTerra({ car }: { car: string }) {
  const sessao = useSessao()
  const [ficha, setFicha] = useState<FichaTerraDados | null>(null)
  const [estado, setEstado] = useState<"carregando" | "bloqueada" | "pronta" | "erro">("carregando")
  const [erro, setErro] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const [contato, setContato] = useState<string | null>(null)
  const [revisao, setRevisao] = useState(0)
  useEffect(() => {
    if (!sessao || !prospeccao.disponivel) return
    const abortar = new AbortController()
    setEstado("carregando"); setFicha(null); setErro(null)
    prospeccao.ficha(car, abortar.signal).then((f) => { if (!abortar.signal.aborted) { setFicha(f); setEstado("pronta") } }, (e: Error) => {
      if (abortar.signal.aborted) return
      setEstado(e instanceof ErroProspeccao && e.status === 402 ? "bloqueada" : "erro"); setErro(e.message)
    })
    return () => abortar.abort()
  }, [car, sessao?.token])
  async function desbloquear() {
    setOcupado(true); setErro(null)
    try {
      await prospeccao.desbloquear(car)
      setRevisao((v) => v + 1)
      setFicha(await prospeccao.ficha(car)); setEstado("pronta")
    } catch (e) { setErro((e as Error).message) }
    finally { setOcupado(false) }
  }
  async function pedirContato() {
    setOcupado(true); setErro(null)
    try {
      const pedido = await prospeccao.contato(car)
      setContato(`Pedido ${pedido.id} recebido em ${dataTerra(pedido.criado_em)}. ${pedido.mensagem}`)
    } catch (e) { setErro((e as Error).message) }
    finally { setOcupado(false) }
  }
  if (prospeccao.disponivel && !sessao) return <Entrar token={null} volta={location.hash} />
  return <div className="tela-pedidos">
    <Cabecalho atual="fazendas" linkMapa={ficha?.cod_ibge ? linkMunicipio(String(ficha.cod_ibge)) : "#/"} />
    <main id="conteudo" tabIndex={-1} className="pagina ficha-terra">
      <a href={linkProspeccao}>Buscar fazendas no Brasil</a>
      <h1>Ficha da terra</h1>
      <p className="car-terra">CAR <code>{car}</code></p>
      {!prospeccao.disponivel ? <Estado tipo="vazio" titulo="Ficha completa na área de clientes"><p>A ficha exige créditos pagos e conexão com a Raíz. Consulte os agregados no <a href="#/">mapa aberto</a>.</p></Estado> : estado === "carregando" ? <Estado tipo="carregando" titulo="Conferindo o acesso à ficha" /> : estado === "bloqueada" ? <section>
        <h2>Desbloquear esta ficha</h2><p>Use 1 crédito de consulta para ver os dados da terra, suas fontes e datas. O crédito não é uma tonelada de carbono.</p>
        <button className="botao principal" type="button" disabled={ocupado} onClick={desbloquear}>{ocupado ? "Desbloqueando" : "Desbloquear por 1 crédito"}</button>
      </section> : ficha && <>
        <div className="secao-cabeca"><p className="frase">{ficha.municipio}, {ficha.uf}. {ficha.bioma ?? "Bioma não informado"}.</p>{ficha.cod_ibge && <a className="botao" href={linkMunicipio(String(ficha.cod_ibge))}>Ver município no mapa</a>}</div>
        <Suspense fallback={<p role="status">Abrindo o mapa da fazenda…</p>}><MapaFichaTerra ficha={ficha} /></Suspense>
        <section aria-labelledby="area-terra"><h2 id="area-terra">Área e restauração</h2><dl className="grade-terra"><div><dt>Área da fazenda</dt><dd><Medida dado={ficha.area_total} /></dd></div><div><dt>Quanto pode voltar a ser mata</dt><dd><Medida dado={ficha.area_restauravel} /></dd></div></dl></section>
        <section><h2>Caminho da terra e pendências</h2><p className="frase">{ficha.caminho_terra.rotulo}</p><p>{SITUACOES.find((s) => s.id === ficha.caminho_terra.situacao)?.nome ?? "Situação não informada"}. Fonte: {ficha.caminho_terra.fonte}. {dataTerra(ficha.caminho_terra.data_referencia)}.</p>
          {ficha.pendencias.length ? <ul>{ficha.pendencias.map((p) => <li key={p.codigo}>{p.texto}</li>)}</ul> : <p>Nenhuma pendência registrada nas fontes consultadas.</p>}
          <p>Risco da terra: <strong>{NOME_RISCO[ficha.risco.nivel as Risco] ?? "não informado"}</strong>. Fonte: {ficha.risco.fonte}. {dataTerra(ficha.risco.data_referencia)}.</p>
          {ficha.risco.regra_versao && <p className="legenda-frase">Versão da regra: {ficha.risco.regra_versao}.</p>}
        </section>
        <section><h2>Sobreposições e embargos</h2><dl className="grade-terra">{ficha.sobreposicoes.map((s) => <div key={s.codigo}><dt>{s.rotulo}</dt><dd><Medida dado={s.area} /></dd></div>)}<div><dt>Área embargada</dt><dd><Medida dado={ficha.embargos.area} /></dd></div></dl></section>
        <section><h2>Crédito de carbono estimado</h2><p>{ficha.credito.base === "liquido_contrato" ? "Créditos líquidos ao longo do contrato." : ficha.credito.base === "liquido_anual" ? "Créditos líquidos por ano." : "Créditos líquidos ainda não calculados."}</p><Faixas titulo="Faixa de créditos líquidos" dados={ficha.credito} /><p>{ficha.credito.metodo}</p>{ficha.credito.versao_modelo && <p className="legenda-frase">Versão do modelo: {ficha.credito.versao_modelo}.</p>}
          <Faixas titulo={`TIR ${ficha.tir.tipo === "com_financiamento" ? "com" : "sem"} financiamento`} dados={ficha.tir} />
        </section>
        <section><h2>Linha do tempo da fazenda</h2><LinhaTempoTerra ficha={ficha} /></section>
        <section><h2>Uso da terra ao longo dos anos</h2>{!ficha.serie_uso.length ? <p>Série anual ainda não disponível.</p> : <div className="tabela-terra" tabIndex={0} role="region" aria-label="Uso da terra por ano"><table className="tabela-simples"><thead><tr><th>Ano</th><th>Mata</th><th>Pasto</th><th>Lavoura</th><th>Água</th></tr></thead><tbody>{ficha.serie_uso.map((s) => <tr key={s.ano}><th scope="row">{s.ano}</th>{(["mata", "pasto", "lavoura", "agua"] as const).map((c) => <td key={c}><Medida dado={s[c]} /></td>)}</tr>)}</tbody></table></div>}</section>
        <section><h2>Perdas ao longo dos anos</h2>{!ficha.perdas.length ? <p>Histórico de perdas ainda não disponível.</p> : <div className="tabela-terra" tabIndex={0} role="region" aria-label="Perdas por período"><table className="tabela-simples"><thead><tr><th>Período</th><th>O que foi observado</th><th>Área</th></tr></thead><tbody>{ficha.perdas.map((p, i) => <tr key={`${p.tipo}-${p.ano}-${i}`}><th scope="row">{p.ano ?? "Período da fonte"}</th><td>{p.rotulo}</td><td><Medida dado={p.area} /></td></tr>)}</tbody></table></div>}</section>

        <section><h2>Agrupar fazendas pequenas</h2><p>{ficha.agrupamento.pequena ? "Esta fazenda pode compor um grupo. A viabilidade depende de confirmar a proximidade e as condições das outras áreas." : ficha.agrupamento.pequena === null ? "Porte ainda não informado. A busca não elimina fazendas pequenas." : "Fazendas de qualquer tamanho podem compor um lote."}</p>{ficha.agrupamento.grupo_id && <dl className="grade-terra"><div><dt>Fazendas no grupo indicado</dt><dd><Medida dado={ficha.agrupamento.imoveis} /></dd></div><div><dt>Área do grupo</dt><dd><Medida dado={ficha.agrupamento.area} /></dd></div></dl>}</section>
        <section><h2>Próximo passo</h2><p>O pedido fica registrado na Raíz. O contato será tratado depois.</p><button className="botao principal" type="button" disabled={ocupado || !!contato} onClick={pedirContato}>{contato ? "Pedido de contato recebido" : ocupado ? "Registrando pedido" : "Pedir contato"}</button>{contato && <p role="status">{contato}</p>}</section>
      </>}
      {erro && <p className="erro-campo" role="alert">{erro}</p>}
      <CreditosConsulta revisao={revisao} />
    </main>
  </div>
}
