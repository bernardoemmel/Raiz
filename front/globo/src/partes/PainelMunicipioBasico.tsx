import { useState } from "react"
import { SITUACAO } from "../../../compartilhado/cores"
import { SITUACOES_BASICAS, type ImovelBasico, type SituacaoBasica } from "../../../compartilhado/dados/basico"
import type { FunilMunicipio } from "../../../compartilhado/dados"
import { abreviarCar, fmtHa, fmtInt, UFS } from "../../../compartilhado/formato"
import { linkEstado, linkFazenda } from "../rota"
import { MiniBrasil } from "./MiniBrasil"
import { Estado } from "./Estado"

const CORES = { apto: SITUACAO.apta, com_pendencia: SITUACAO.pendencia, nao_apto: SITUACAO.naoApta }
const POR_PAGINA = 50

/** A lista aberta só recebe o contrato básico, sem acesso ao objeto completo de um imóvel. */
export function PainelMunicipioBasico({ nome, uf, centro, funil, imoveis, situacao, mudarSituacao, aoPassar, atualizadoEm }: {
  nome: string; uf: string; centro: [number, number] | null; funil: FunilMunicipio | null
  imoveis: ImovelBasico[] | null | undefined; situacao: SituacaoBasica | null
  mudarSituacao: (s: SituacaoBasica | null) => void; aoPassar: (cod: string | null) => void
  atualizadoEm?: string
}) {
  const [pagina, setPagina] = useState(0)
  const [ultimaSituacao, setUltimaSituacao] = useState(situacao)
  if (ultimaSituacao !== situacao) { setUltimaSituacao(situacao); setPagina(0) }
  const lista = (imoveis ?? []).filter((i) => !situacao || i.situacao_basica === situacao)
  const data = atualizadoEm && !Number.isNaN(Date.parse(atualizadoEm))
    ? new Intl.DateTimeFormat("pt-BR", { timeZone: "UTC" }).format(new Date(atualizadoEm)) : "não informada"
  return <div className="painel-conteudo">
    <ol className="migalhas" aria-label="Onde você está">
      <li><a href="#/">Brasil</a></li><li><a href={linkEstado(uf)}>{UFS[uf] ?? uf}</a></li><li aria-current="page">{nome}</li>
    </ol>
    <div className="painel-titulo"><h1>{nome}</h1><MiniBrasil uf={uf} lon={centro?.[0]} lat={centro?.[1]} titulo={`Localização de ${nome}`} className="mini-titulo" /></div>
    <p className="frase">A situação básica da terra é aberta. Todas as fazendas entram, inclusive as pequenas.</p>
    {funil && funil.linha.dados_suprimidos !== "true" && <p>{fmtInt(funil.imoveis)} imóveis no município. {fmtHa(funil.ha_carbono)} com potencial de restauração no agregado municipal.</p>}
    <p className="legenda-frase">Fonte: CAR e classificação territorial da Raíz. Publicação: {data}. A situação básica não substitui uma análise da terra.</p>
    {imoveis === undefined ? <Estado tipo="carregando" titulo="Carregando a situação das fazendas" /> : imoveis === null ? <Estado tipo="vazio" titulo="A camada básica deste município ainda não foi publicada." /> : <>
      <ul className="legenda-lista" aria-label="Situação básica no mapa">{Object.entries(SITUACOES_BASICAS).map(([id, rotulo]) => <li key={id}><i style={{ background: CORES[id as SituacaoBasica] }} />{rotulo}</li>)}</ul>
      <section className="secao-painel" aria-labelledby="lista-basica-titulo">
        <h2 id="lista-basica-titulo">Fazendas</h2>
        <div className="ordem-restauro"><label>Situação básica<select value={situacao ?? ""} onChange={(e) => mudarSituacao((e.target.value || null) as SituacaoBasica | null)}>
          <option value="">Todas as situações</option>{Object.entries(SITUACOES_BASICAS).map(([id, rotulo]) => <option key={id} value={id}>{rotulo}</option>)}
        </select></label></div>
        <p>{fmtInt(lista.length)} fazendas nesta seleção. A ficha completa exige conta e créditos pagos.</p>
        <ul className="lista-basica">{lista.slice(pagina * POR_PAGINA, (pagina + 1) * POR_PAGINA).map((i) => <li key={i.cod_imovel} onMouseEnter={() => aoPassar(i.cod_imovel)} onMouseLeave={() => aoPassar(null)}>
          <a href={linkFazenda(i.cod_imovel)} onFocus={() => aoPassar(i.cod_imovel)} onBlur={() => aoPassar(null)} title={i.cod_imovel}><span>CAR {abreviarCar(i.cod_imovel)}</span><span>{SITUACOES_BASICAS[i.situacao_basica]}</span><small>Abrir ficha completa</small></a>
        </li>)}</ul>
        {lista.length > POR_PAGINA && <nav className="acoes" aria-label="Páginas das fazendas"><button className="botao" disabled={!pagina} onClick={() => setPagina(pagina - 1)}>Anterior</button><span>{pagina + 1} de {Math.ceil(lista.length / POR_PAGINA)}</span><button className="botao" disabled={(pagina + 1) * POR_PAGINA >= lista.length} onClick={() => setPagina(pagina + 1)}>Próxima</button></nav>}
      </section>
    </>}
    <p className="legenda-frase">Certidão com IA, terra comprometida, valor, créditos P10/P50/P90, TIR, risco e histórico detalhado ficam na ficha completa.</p>
    <a className="botao" href="#/prospeccao">Buscar e consultar fichas</a>
  </div>
}
