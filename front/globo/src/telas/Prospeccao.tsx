import { useEffect, useState } from "react"
import { normalizar, UFS } from "../../../compartilhado/formato"
import { CAMINHOS, NOME_RISCO, SITUACOES, type Risco } from "../../../compartilhado/terra"
import type { BuscaProspeccao, FiltrosProspeccao } from "../../../compartilhado/prospeccao"
import type { FunilMunicipio } from "../../../compartilhado/dados/tipos"
import { fonte } from "../dados"
import { Cabecalho } from "../partes/Cabecalho"
import { CreditosConsulta } from "../partes/CreditosConsulta"
import { Estado } from "../partes/Estado"
import { useSessao } from "../pedidos"
import { dataTerra, numeroTerra, prospeccao } from "../prospeccao"
import { linkFazenda, linkMunicipio } from "../rota"

const BIOMAS = ["Amazônia", "Caatinga", "Cerrado", "Mata Atlântica", "Pampa", "Pantanal"]
export function Prospeccao() {
  const sessao = useSessao()
  const [campos, setCampos] = useState<FiltrosProspeccao>({})
  const [consulta, setConsulta] = useState<{ filtros: FiltrosProspeccao; pagina: number }>({ filtros: {}, pagina: 1 })
  const [resultado, setResultado] = useState<BuscaProspeccao | null>(null)
  const [resumos, setResumos] = useState<FunilMunicipio[] | null>(null)
  const [car, setCar] = useState("")
  const [erro, setErro] = useState<string | null>(null)
  const [lendo, setLendo] = useState(false)
  useEffect(() => {
    const abortar = new AbortController()
    setLendo(true); setErro(null); setResultado(null)
    if (prospeccao.disponivel) {
      const { area_min_ha: _amin, area_max_ha: _amax, credito_min: _cmin, credito_max: _cmax, ...publicos } = consulta.filtros
      const pedido = sessao ? prospeccao.buscar(consulta.filtros, consulta.pagina, abortar.signal) : prospeccao.agregado(publicos, abortar.signal)
      pedido.then((r) => { setResultado(r); setLendo(false) }, (e: Error) => { if (!abortar.signal.aborted) { setErro(e.message); setLendo(false) } })
    } else {
      fonte.municipios().then((m) => { if (!abortar.signal.aborted) { setResumos(m); setLendo(false) } }, (e: Error) => { if (!abortar.signal.aborted) { setErro(e.message); setLendo(false) } })
    }
    return () => abortar.abort()
  }, [consulta, sessao?.token])
  const mudar = (campo: keyof FiltrosProspeccao, valor: string) => setCampos((c) => ({ ...c, [campo]: valor }))
  const resumoLocal = resumos?.filter((m) => (!consulta.filtros.uf || m.uf === consulta.filtros.uf) && (!consulta.filtros.cod_ibge || m.cod_ibge === consulta.filtros.cod_ibge) && (!consulta.filtros.q || normalizar(m.municipio).includes(normalizar(consulta.filtros.q))))
  const numerico = (chave: keyof FiltrosProspeccao, nome: string) => <label className="campo"><span>{nome}</span><input type="number" min="0" step="any" value={campos[chave] ?? ""} onChange={(e) => mudar(chave, e.target.value)} disabled={!prospeccao.disponivel || !sessao} /></label>
  return <div className="tela-pedidos"><Cabecalho atual="fazendas" /><main id="conteudo" tabIndex={-1} className="pagina prospeccao">
    <div className="secao-cabeca"><h1>Prospectar terras no Brasil</h1><a className="botao" href="#/">Abrir o mapa</a></div>
    <p className="frase">Encontre áreas para restaurar, compare o caminho da terra e veja as pequenas fazendas que podem compor um grupo.</p>
    <form className="formulario abrir-car" onSubmit={(e) => { e.preventDefault(); if (car.trim()) location.hash = linkFazenda(car.trim()) }}>
      <label className="campo"><span>Abrir ficha pelo código do CAR</span><input value={car} onChange={(e) => setCar(e.target.value)} placeholder="Código completo do CAR" required /></label><button className="botao" type="submit">Abrir ficha</button>
    </form>
    <form className="formulario filtros-prospeccao" onSubmit={(e) => { e.preventDefault(); setConsulta({ filtros: { ...campos }, pagina: 1 }) }}>
      <h2>Filtrar a base</h2>
      {!prospeccao.disponivel && <p>O site aberto mostra resumos por estado e município. Os demais filtros e fichas precisam da conexão com a Raíz.</p>}
      <div className="grade-filtros">
        <label className="campo"><span>Estado</span><select value={campos.uf ?? ""} onChange={(e) => mudar("uf", e.target.value)}><option value="">Brasil inteiro</option>{Object.entries(UFS).map(([uf, nome]) => <option key={uf} value={uf}>{nome}</option>)}</select></label>
        <label className="campo"><span>Nome do município</span><input value={campos.q ?? ""} onChange={(e) => mudar("q", e.target.value)} placeholder="Ex.: São Félix do Xingu" /></label>
        <label className="campo"><span>Município, código IBGE</span><input inputMode="numeric" pattern="[0-9]{7}" value={campos.cod_ibge ?? ""} placeholder="7 dígitos" onChange={(e) => mudar("cod_ibge", e.target.value)} /></label>
        <label className="campo"><span>Bioma</span><select value={campos.bioma ?? ""} disabled={!prospeccao.disponivel} onChange={(e) => mudar("bioma", e.target.value)}><option value="">Todos os biomas</option>{BIOMAS.map((b) => <option key={b}>{b}</option>)}</select></label>
        <label className="campo"><span>Caminho da terra</span><select value={campos.caminho_terra ?? ""} disabled={!prospeccao.disponivel} onChange={(e) => mudar("caminho_terra", e.target.value)}><option value="">Todos os caminhos</option>{CAMINHOS.map((c) => <option key={c.id} value={c.id}>{c.nome}</option>)}</select></label>
        <label className="campo"><span>Situação da terra</span><select value={campos.situacao_terra ?? ""} disabled={!prospeccao.disponivel} onChange={(e) => mudar("situacao_terra", e.target.value)}><option value="">Todas as situações</option>{SITUACOES.map((s) => <option key={s.id} value={s.id}>{s.nome}</option>)}<option value="sem_dados">Sem informação</option></select></label>
        <label className="campo"><span>Risco</span><select value={campos.risco ?? ""} disabled={!prospeccao.disponivel} onChange={(e) => mudar("risco", e.target.value)}><option value="">Todos os riscos</option><option value="baixo">Baixo</option><option value="medio">Médio</option><option value="alto">Alto</option><option value="sem_dados">Sem informação</option></select></label>
        {numerico("area_min_ha", "Área mínima, ha")}{numerico("area_max_ha", "Área máxima, ha")}
        {numerico("credito_min", "Crédito líquido mínimo, tCO₂e por contrato")}{numerico("credito_max", "Crédito líquido máximo, tCO₂e por contrato")}
      </div>
      <p className="legenda-frase">Sem área mínima por padrão. As pequenas continuam na busca. O filtro de crédito usa o P50 do total do contrato, quando calculado.</p>
      {prospeccao.disponivel && !sessao && <p><a href="#/entrar">Entre para filtrar por tamanho e crédito</a>. Agregados muito pequenos são ocultados para proteger o acesso às fichas.</p>}
      <div className="acoes-prospeccao"><button className="botao principal" type="submit" disabled={lendo}>{lendo ? "Consultando" : "Aplicar filtros"}</button><button className="botao" type="button" onClick={() => { setCampos({}); setConsulta({ filtros: {}, pagina: 1 }) }}>Limpar filtros</button></div>
    </form>
    <section aria-live="polite" aria-busy={lendo}>
      {lendo ? <Estado tipo="carregando" titulo="Consultando a base" /> : erro ? <p className="erro-campo" role="alert">{erro}</p> : resultado ? <>
        <h2>Quanto existe na base</h2>
        <p className="frase"><strong>{resultado.contagem ?? numeroTerra(resultado.totais.fazendas)} fazendas</strong>, {numeroTerra(resultado.totais.area_ha)} ha. {numeroTerra(resultado.totais.pequenas)} pequenas incluídas.</p>
        <dl className="grade-terra"><div><dt>Área que pode voltar a ser mata</dt><dd>{numeroTerra(resultado.totais.area_restauravel_ha)} ha</dd></div><div><dt>Crédito líquido por contrato, P10 / P50 / P90</dt><dd>{numeroTerra(resultado.totais.credito_p10)} / {numeroTerra(resultado.totais.credito_p50)} / {numeroTerra(resultado.totais.credito_p90)} tCO₂e</dd></div></dl>
        <p className="legenda-frase">Estimativas de crédito disponíveis em {numeroTerra(resultado.totais.com_credito)} fazendas. Fonte: {resultado.totais.fonte}. Corte da base: {dataTerra(resultado.totais.data_corte_min)} a {dataTerra(resultado.totais.data_corte_max)}.</p>
        <p>{resultado.aviso}</p>
        {!!resultado.agrupamentos.length && <><h3>Pequenas fazendas para estudar em conjunto</h3>{resultado.agrupamentos_limitados && <p>Mostrando {numeroTerra(resultado.agrupamentos.length)} de {numeroTerra(resultado.total_agrupamentos)} grupos. Refine a região para explorar os demais.</p>}<ul className="grupos-prospeccao">{resultado.agrupamentos.map((g) => <li key={`${g.cod_ibge}-${g.bioma}`}><a href={linkMunicipio(String(g.cod_ibge))}>{g.municipio}, {g.uf}</a>: {numeroTerra(g.fazendas)} fazendas, {numeroTerra(g.area_ha)} ha. {g.bioma ?? "Bioma não informado"}. {g.criterio}</li>)}</ul></>}
        {!sessao ? <p><a href="#/entrar">Entre para ver a lista de fazendas</a>. A ficha completa usa créditos pagos.</p> : resultado.imoveis?.length ? <>
          <div className="tabela-terra" tabIndex={0} role="region" aria-label="Fazendas encontradas"><table className="tabela-simples"><thead><tr><th>Fazenda pelo CAR</th><th>Área</th><th>Caminho e risco</th><th>Crédito P50</th><th>Fonte e corte</th></tr></thead><tbody>{resultado.imoveis.map((i) => <tr key={i.codigo_car}>
            <th scope="row"><a href={linkFazenda(i.codigo_car)} className="car-terra">{i.codigo_car}</a><small>{i.municipio}, {i.uf}. {i.bioma ?? "Bioma não informado"}</small>{i.agrupar && <small>{i.pequena ? "Pequena fazenda para agrupar" : "Área para estudar em grupo"}</small>}</th><td>{numeroTerra(i.area_ha)} ha</td><td>{CAMINHOS.find((c) => c.id === i.caminho_terra)?.nome ?? "Caminho não informado"}<small>Risco {NOME_RISCO[i.risco as Risco] ?? "não informado"}</small></td><td>{numeroTerra(i.credito_p50)} tCO₂e por contrato</td><td>{i.fonte}<small>{dataTerra(i.data_corte)}</small></td>
          </tr>)}</tbody></table></div>
          <div className="acoes-prospeccao"><button className="botao" type="button" disabled={consulta.pagina === 1} onClick={() => setConsulta((c) => ({ ...c, pagina: c.pagina - 1 }))}>Anterior</button><span>Página {resultado.pagina}</span><button className="botao" type="button" disabled={!resultado.tem_mais} onClick={() => setConsulta((c) => ({ ...c, pagina: c.pagina + 1 }))}>Próxima</button></div>
        </> : sessao && <p>Nenhuma fazenda corresponde aos filtros. Amplie o recorte ou retire uma condição.</p>}
      </> : resumoLocal && <>
        <h2>Agregado público disponível</h2><p className="frase">{numeroTerra(resumoLocal.length)} municípios com dados. {resumoLocal.some((m) => m.linha.dados_suprimidos === "true") ? "Os totais deste recorte foram ocultados porque incluem grupos pequenos." : `${numeroTerra(resumoLocal.reduce((s, m) => s + m.imoveis, 0))} fazendas no cadastro.`}</p>
        <p>Fonte: resumos do motor da Raíz. A data de referência por fonte não está disponível neste resumo. Abra o mapa para conferir a cobertura.</p>
        <p><a href={consulta.filtros.cod_ibge ? linkMunicipio(consulta.filtros.cod_ibge) : "#/"}>Ver este recorte no mapa</a></p>
      </>}
    </section>
    <CreditosConsulta />
  </main></div>
}
