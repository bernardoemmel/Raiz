import { useEffect, useRef, useState } from "react"
import type { FichaTerraDados, HistoricoFicha, MedidaTerra, MudancaTerra } from "../../../compartilhado/prospeccao"
import { dataTerra, numeroTerra, prospeccao } from "../prospeccao"
import { Medida } from "./MedidaTerra"

const nomes: Record<string, string> = {
  pendencias: "Pendências", embargos: "Embargos", caminho_terra: "Caminho da terra", terra_comprometida: "Terra comprometida", sobreposicoes: "Sobreposições", serie_uso: "Uso da terra", credito: "Crédito de carbono", tir: "TIR", risco: "Risco", area_total: "Área total", area_restauravel: "Área que pode virar mata", disponivel: "Disponibilidade da terra", fogo: "Fogo", desmatamento: "Desmatamento", lotes_da_conta: "Lotes desta conta",
  entrou_lote: "Entrou em lote desta conta", saiu_lote: "Saiu de lote desta conta", entrou_filtro: "Passou a atender aos filtros", saiu_filtro: "Deixou de atender aos filtros", nova_fazenda: "Nova fazenda na busca", alteracao_terra: "Alterações na terra", atualizacao_disponivel: "Atualização disponível",
  area: "Área", codigo: "Código", rotulo: "Descrição", situacao: "Situação", nivel: "Nível", fonte: "Fonte", data_referencia: "Data da fonte", data_corte: "Corte da base", regra_versao: "Versão da regra", origem: "Origem", texto: "Descrição", p10: "P10", p50: "P50", p90: "P90", ano: "Ano", tipo: "Tipo", base: "Base", metodo: "Método", versao_modelo: "Versão do modelo", mata: "Mata", pasto: "Pasto", lavoura: "Lavoura", agua: "Água", area_confirmada: "Interseção confirmada", area_indicio: "Área com indícios", evidencias: "Evidências", contexto_jurisdicional: "Contexto jurisdicional", cobertura: "Cobertura", aviso: "Observação", versao: "Versão", objeto_id: "Identificador do registro", fonte_id: "Fonte", fonte_url: "Endereço da fonte", certeza: "Certeza", inicio: "Início", fim: "Fim", registro: "Registro", estado: "Estado da cobertura", escopo: "Escopo", recorte: "Recorte", licenca: "Licença", url: "Endereço da fonte", bbox: "Limites do recorte",
}
export const nomeMudanca = (campo: string) => nomes[campo] ?? campo.replaceAll("_", " ")
const momento = (valor: string) => { const data = new Date(valor); return Number.isNaN(data.getTime()) ? dataTerra(valor) : data.toLocaleString("pt-BR") }

/** Valores vêm da projeção fechada do servidor, sem HTML e sem buscar fontes adicionais. */
function ValorMudanca({ valor, campo = "" }: { valor: unknown; campo?: string }) {
  if (valor == null) return <span>Não informado</span>
  if (typeof valor === "boolean") return <span>{valor ? "Sim" : "Não"}</span>
  if (typeof valor === "number") return <span>{campo === "ano" ? valor : numeroTerra(valor)}</span>
  if (typeof valor === "string") return <span>{campo.startsWith("data_") || campo === "inicio" || campo === "fim" ? dataTerra(valor) : nomes[valor] ?? valor}</span>
  if (Array.isArray(valor)) return valor.length ? <ul>{valor.map((item, i) => <li key={i}><ValorMudanca valor={item} /></li>)}</ul> : <span>Nenhum registro</span>
  if (typeof valor === "object") {
    const dado = valor as Record<string, unknown>
    if ("valor" in dado && typeof dado.unidade === "string" && (typeof dado.valor === "number" || dado.valor === null)) return <Medida dado={dado as unknown as MedidaTerra} />
    return <dl className="valores-mudanca">{Object.entries(dado).map(([chave, item]) => <div key={chave}><dt>{nomeMudanca(chave)}</dt><dd><ValorMudanca valor={item} campo={chave} /></dd></div>)}</dl>
  }
  return <span>Não informado</span>
}
export function MudancasTerra({ mudancas }: { mudancas: MudancaTerra[] }) {
  return <ul className="mudancas-terra">{mudancas.map((m, i) => <li key={`${m.tipo}-${m.campo}-${i}`}><details>
    <summary>{nomeMudanca(m.tipo === "entrou_lote" || m.tipo === "saiu_lote" ? m.tipo : m.campo)}</summary>
    <p className="legenda-frase">Fonte: {m.fonte || "Não informada"}. {m.data_referencia ? `Referência: ${dataTerra(m.data_referencia)}.` : "Data da fonte não informada."}{m.data_corte ? ` Corte da base: ${dataTerra(m.data_corte)}.` : ""}</p>
    <div className="grade-terra antes-depois"><div><strong>Antes</strong><ValorMudanca valor={m.antes} campo={m.campo} /></div><div><strong>Depois</strong><ValorMudanca valor={m.depois} campo={m.campo} /></div></div>
  </details></li>)}</ul>
}
export function VersoesFicha({ ficha }: { ficha: FichaTerraDados }) {
  const [historico, setHistorico] = useState<HistoricoFicha | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [carregando, setCarregando] = useState(false)
  const controle = useRef<AbortController | null>(null)
  useEffect(() => () => controle.current?.abort(), [])
  async function carregar() {
    controle.current?.abort()
    const abortar = new AbortController(); controle.current = abortar
    setCarregando(true); setErro(null)
    try { const h = await prospeccao.historico(ficha.codigo_car, abortar.signal); if (!abortar.signal.aborted) setHistorico(h) }
    catch (e) { if (!abortar.signal.aborted) setErro((e as Error).message) }
    finally { if (!abortar.signal.aborted) setCarregando(false) }
  }
  const mudou = ficha.o_que_mudou
  return <section className="versoes-ficha" aria-labelledby="versoes-titulo">
    <h2 id="versoes-titulo">Versões e o que mudou</h2>
    {ficha.versao_ficha && <p>Versão {ficha.versao_ficha.id}. Registrada em <time dateTime={ficha.versao_ficha.registrada_em}>{momento(ficha.versao_ficha.registrada_em)}</time>.</p>}
    <h3>Desde a última consulta desta conta</h3>
    {!mudou ? <p>Comparação entre consultas ainda não disponível.</p> : mudou.primeira_consulta ? <p>Esta é a primeira consulta desta conta. A versão atual será a referência para as próximas consultas.</p> : <>
      <p>Comparação com a consulta de {mudou.consulta_anterior_em ? momento(mudou.consulta_anterior_em) : "data não informada"}, versão {mudou.versao_anterior_id}.</p>
      {mudou.mudancas.length ? <MudancasTerra mudancas={mudou.mudancas} /> : <p>Nenhuma mudança registrada desde a última consulta desta conta.</p>}
    </>}
    <h3>Histórico da base</h3><p>As versões registradas na base preservam mudanças observadas, inclusive entre consultas. As datas de registro são diferentes das datas das fontes.</p>
    <button className="botao" type="button" disabled={carregando} onClick={() => void carregar()}>{carregando ? "Carregando histórico" : historico ? "Atualizar histórico da ficha" : "Ver histórico da ficha"}</button>
    {historico && <div role="region" aria-label="Histórico da ficha">{historico.historico.length ? <><p>Até 20 registros mais recentes.</p><ol className="historico-ficha">{historico.historico.map((h) => <li key={h.id}>
      <details><summary>Versão {h.versao_id}, {momento(h.registrada_em)}</summary>
        <p>{h.anterior_id === null ? "Primeira versão registrada." : `Versão anterior: ${h.anterior_id}.`} Origem: {nomeMudanca(h.origem)}.</p>
        {h.mudancas.length ? <MudancasTerra mudancas={h.mudancas} /> : <p>Sem mudanças de campos neste registro.</p>}
        <p className="legenda-frase">Identificador de integridade: <code>{h.hash_conteudo}</code></p>
      </details>
    </li>)}</ol></> : <p>Nenhuma versão registrada no histórico disponível.</p>}</div>}
    {erro && <p role="alert" className="erro-campo">{erro}</p>}
  </section>
}
