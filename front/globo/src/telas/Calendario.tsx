import { useState } from "react"
import { dataEvento, formatarDia, hojeNoBrasil, TIPOS_EVENTO, type Evento, type FiltrosEvento } from "../../../compartilhado/calendario"
import { abreviarCar, UFS } from "../../../compartilhado/formato"
import { calendario } from "../calendario"
import { useCarga } from "../dados"
import { Cabecalho } from "../partes/Cabecalho"
import { Estado } from "../partes/Estado"
import { linkFazenda, linkMunicipio } from "../rota"

const POR_PAGINA = 50
function LinhaEvento({ evento: e }: { evento: Evento }) {
  return <li className="calendario-evento">
    <div className="calendario-dia"><time dateTime={dataEvento(e)}>{formatarDia(dataEvento(e))}</time><small>{e.prazo ? "Prazo" : "Data do evento"}</small></div>
    <div>
      <div className="selos"><span className="selo neutro">{TIPOS_EVENTO[e.tipo]}</span>{e.situacao !== "previsto" && <span className="selo conferir">{e.situacao === "cancelado" ? "Cancelado" : "Adiado"}</span>}</div>
      <h2>{e.titulo}</h2>
      <p>{e.uf ? UFS[e.uf] || e.uf : "Abrangência geral"}{e.municipio && <>; <a href={linkMunicipio(e.municipio)}>ver município no mapa</a></>}
        {e.prazo && e.prazo !== e.data && <>. Evento em {formatarDia(e.data)}</>}.</p>
      {e.codigos_car.length > 0 && <ul className="calendario-cars" aria-label="Imóveis ligados ao evento">{e.codigos_car.map((car) => <li key={car}><a href={linkFazenda(car)}>CAR {abreviarCar(car)}</a></li>)}</ul>}
      <p className="calendario-fonte">Fonte: {e.fonte_url ? <a href={e.fonte_url} target="_blank" rel="noopener noreferrer">{e.fonte_nome}</a> : e.fonte_nome}.
        {e.coletado_em && <> Coletado em {formatarDia(e.coletado_em.slice(0, 10))}.</>} Confiança da leitura: {Math.round(e.confianca * 100)}%.</p>
    </div>
  </li>
}

export function Calendario({ car }: { car?: string }) {
  const [filtros, setFiltros] = useState<FiltrosEvento>({ inicio: hojeNoBrasil(), cod_imovel: car })
  const [pagina, setPagina] = useState(0)
  const [tentativa, setTentativa] = useState(0)
  const [agora] = useState(() => Date.now())
  const periodoInvalido = !!(filtros.inicio && filtros.fim && filtros.inicio > filtros.fim)
  const carga = useCarga(() => calendario.listar(filtros, pagina * POR_PAGINA, POR_PAGINA), [filtros.tipo, filtros.estado, filtros.inicio, filtros.fim, pagina, tentativa])
  const agenda = carga.dado
  const mudar = (campo: keyof FiltrosEvento, valor: string) => { setFiltros((f) => ({ ...f, [campo]: valor })); setPagina(0) }
  const falhas = agenda?.fontes.filter((f) => f.situacao !== "ok" && f.situacao !== "sucesso") ?? []
  const antiga = agenda?.coletado_em ? agora - Date.parse(agenda.coletado_em) > 48 * 3600000 : false
  return <>
    <Cabecalho atual="calendario" />
    <main className="pagina calendario">
      <div className="cabeca"><div><h1>Calendário da Raíz</h1><p>Leilões, editais e prazos para acompanhar a terra e os créditos de carbono.</p></div>
        {agenda?.disponivel && <a className="botao" href={calendario.feed(filtros)} download="raiz-eventos.ics">{calendario.api ? "Baixar seleção (.ics)" : "Baixar agenda completa (.ics)"}</a>}</div>
      {car && <p>Eventos do CAR <code>{abreviarCar(car)}</code>. <a href="#/calendario">Ver todos os imóveis</a></p>}
      <form className="calendario-filtros" onSubmit={(e) => e.preventDefault()} aria-label="Filtrar eventos">
        <label>Tipo<select aria-label="Tipo" value={filtros.tipo || ""} onChange={(e) => mudar("tipo", e.target.value)}><option value="">Todos os tipos</option>{Object.entries(TIPOS_EVENTO).map(([tipo, nome]) => <option key={tipo} value={tipo}>{nome}</option>)}</select></label>
        <label>Estado<select aria-label="Estado" value={filtros.estado || ""} onChange={(e) => mudar("estado", e.target.value)}><option value="">Todos os estados</option>{Object.entries(UFS).map(([uf, nome]) => <option key={uf} value={uf}>{nome}</option>)}</select></label>
        <label>De<input type="date" value={filtros.inicio || ""} onChange={(e) => mudar("inicio", e.target.value)} /></label>
        <label>Até<input type="date" value={filtros.fim || ""} min={filtros.inicio} onChange={(e) => mudar("fim", e.target.value)} /></label>
      </form>
      {periodoInvalido && <p role="alert" className="aviso">A data final precisa ser igual ou posterior à inicial.</p>}
      <div aria-live="polite" aria-busy={carga.carregando}>
        {carga.carregando ? <Estado tipo="carregando" titulo="Consultando o calendário" /> : carga.erro ? <Estado tipo="erro" titulo="Não foi possível consultar os eventos agora."><button className="botao" onClick={() => setTentativa((t) => t + 1)}>Tentar de novo</button></Estado> : !agenda?.disponivel ?
          <Estado tipo="vazio" titulo="A coleta do calendário ainda não está disponível aqui."><p>Quando a primeira coleta for publicada, os eventos aparecerão nesta página. A ausência de dados não significa que não haja prazos ou leilões.</p></Estado> : !periodoInvalido && <>
            <p className="calendario-atualizacao">{agenda.total} {agenda.total === 1 ? "evento encontrado" : "eventos encontrados"}.{agenda.coletado_em ? <> Última coleta: {formatarDia(agenda.coletado_em.slice(0, 10))}.</> : " Ainda não há coleta registrada."} A coleta é diária.</p>
            {antiga && <p className="aviso">A última coleta tem mais de dois dias. Confira as datas nas fontes oficiais.</p>}
            {falhas.length > 0 && <p className="aviso">{falhas.length} {falhas.length === 1 ? "fonte não foi atualizada" : "fontes não foram atualizadas"} na última rodada: {falhas.map((f) => f.nome).join(", ")}. Os eventos podem estar incompletos.</p>}
            {agenda.eventos.length ? <ol className="calendario-lista">{agenda.eventos.map((e) => <LinhaEvento key={e.id} evento={e} />)}</ol> : <Estado tipo="vazio" titulo="Nenhum evento encontrado neste filtro."><p>Tente outro período, estado ou tipo. Consulte a fonte oficial antes de tomar uma decisão.</p></Estado>}
            {agenda.total > POR_PAGINA && <nav className="calendario-paginas" aria-label="Páginas de eventos"><button className="botao" disabled={pagina === 0} onClick={() => setPagina((p) => p - 1)}>Anterior</button><span>Página {pagina + 1} de {Math.ceil(agenda.total / POR_PAGINA)}</span><button className="botao" disabled={(pagina + 1) * POR_PAGINA >= agenda.total} onClick={() => setPagina((p) => p + 1)}>Próxima</button></nav>}
          </>}
      </div>
    </main>
  </>
}
