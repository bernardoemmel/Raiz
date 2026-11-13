import { fmtInt, UFS } from "../../../compartilhado/formato"
import { situacaoProcessamento, type ProcessamentoEstado } from "../../../compartilhado/dados/processamento-estados"
import type { CargaProcessamento } from "../processamento-estados"
import { linkEstado } from "../rota"
import "./PainelProcessamentoEstados.css"

function Data({ valor }: { valor: string | null }) {
  if (!valor || !Number.isFinite(Date.parse(valor))) return <>não informada</>
  return <time dateTime={valor}>{new Date(valor).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo", dateStyle: "short", timeStyle: "short" })}</time>
}

function numero(valor: number | null): string {
  return valor === null ? "Não informado" : fmtInt(valor)
}

function Linha({ estado, agora }: { estado: ProcessamentoEstado; agora: number }) {
  const situacao = situacaoProcessamento(estado, agora)
  const recente = situacao === "atual"
  const informado = situacao !== "sem_telemetria"
  const n = estado.municipios
  return <li className="processamento-estado">
    <div className="processamento-cabecalho">
      <a href={linkEstado(estado.uf)}>{UFS[estado.uf]}</a>
      <span className="processamento-situacao">{recente ? "Atualizado" : informado ? "Sem atualização recente" : "Sem informação de processamento"}</span>
    </div>
    {estado.escopo === "unidade" && <p className="processamento-parcial">Cobertura parcial{estado.unidade ? `: unidade ${estado.unidade}` : " de uma unidade"}. As contagens não representam o estado inteiro.</p>}
    {estado.escopo === "uf" && estado.municipios_total !== null && <p className="processamento-total">{fmtInt(estado.municipios_total)} municípios no estado.</p>}
    {!recente && informado && <p className="processamento-parcial">Contagens da última observação, que já venceu.</p>}
    <dl className="processamento-contagens">
      <div><dt>Municípios prontos</dt><dd>{numero(informado ? n.prontos : null)}</dd></div>
      <div><dt>Rodando agora</dt><dd>{numero(recente ? n.em_execucao : null)}</dd></div>
      <div><dt>Com erro</dt><dd>{numero(informado ? n.com_erro : null)}</dd></div>
    </dl>
    <p className="processamento-datas">Última mudança: <Data valor={estado.ultima_mudanca_em} /><br />Observado em: <Data valor={estado.observado_em} /></p>
    {informado && <details className="processamento-detalhes"><summary>Outras contagens de municípios</summary>
      <p>Pendentes: {numero(n.pendentes)}. Sem situação conhecida: {numero(n.desconhecidos)}.</p>
    </details>}
  </li>
}

export function PainelProcessamentoEstados({ carga, uf }: { carga: CargaProcessamento; uf?: string | null }) {
  const estados = (carga.dado?.estados ?? []).filter((e) => !uf || e.uf === uf).sort((a, b) => UFS[a.uf].localeCompare(UFS[b.uf], "pt-BR"))
  return <section className="secao-painel processamento-estados" aria-labelledby="processamento-titulo">
    <h2 id="processamento-titulo">Processamento dos municípios</h2>
    <p className="processamento-legenda">{uf ? "Andamento neste estado." : "Andamento por estado."} Horários de Brasília.</p>
    {carga.erro && <p role="status" className="processamento-aviso">Não foi possível atualizar o processamento.{carga.dado ? " A última observação recebida continua abaixo." : " As contagens ainda não foram informadas."}</p>}
    {!carga.dado && !carga.erro && <p role="status">{carga.carregando ? "Consultando o processamento dos municípios." : "As contagens ainda não foram informadas."}</p>}
    {estados.length > 0 && <ol className="processamento-lista">{estados.map((estado) => <Linha key={estado.uf} estado={estado} agora={carga.agora} />)}</ol>}
  </section>
}
