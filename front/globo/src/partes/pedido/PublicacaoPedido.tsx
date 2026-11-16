import { Info } from "lucide-react"
import { fmtHa, fmtInt } from "../../../../compartilhado/formato"
import { dataLonga, ROTULO_OPCAO } from "../../../../compartilhado/pedidos/texto"
import { IDS_OPCAO, type RecorteNacional, type ResumoNacional, type SituacaoSobreposicao } from "../../../../compartilhado/pedidos/lote-nacional"
import type { IdOpcao, Pedido, PublicacaoLote } from "../../../../compartilhado/pedidos/tipos"

const numero = (valor: number | null | undefined, formatar: (n: number) => string = fmtInt) =>
  typeof valor === "number" && Number.isFinite(valor) ? formatar(valor) : "Ainda não publicado"

export function AvisoPublicacao({ publicacao: p, recorte }: { publicacao: PublicacaoLote; recorte?: RecorteNacional | null }) {
  return <div className="aviso fontes-pedido" role="status">
    <Info size={20} aria-hidden="true" />
    <div><strong>{p.estado === "publicado" ? "Resumo público dos três lotes." : "Resumos dos lotes ainda indisponíveis."}</strong><p>{p.aviso}</p>
      {p.estado === "publicado" && !recorte && <p>Referência publicada: {p.uf}, meta de {numero(p.volume_creditos)} créditos. Estes lotes não representam outro estado, bioma ou recorte escolhido no pedido.</p>}
      {recorte && <p>Resumo do lote nacional para {recorte.nome}. Ele responde ao recorte escolhido, não a um estado de referência.</p>}
      <p>Os critérios ficam salvos neste navegador.</p>
      <details><summary>Fonte, data e limites da consulta</summary>
        <p>Fonte: <a href={p.fonte} target="_blank" rel="noreferrer">Publicação da Raíz</a>. Atualização: {p.atualizado_em ? dataLonga(p.atualizado_em) : "ainda não informada"}.</p>
        <p>Cenário de referência: {p.uf}, {p.cenario}. A cobertura usa o recorte por estado e município. Os filtros financeiros, de método e de interesse não são aplicados aos agregados públicos.</p>
      </details>
    </div>
  </div>
}

export function BasePublicada({ publicacao: p }: { publicacao: PublicacaoLote }) {
  return <section className="secao-painel quadro-base" aria-labelledby="base-titulo">
    <h2 id="base-titulo">Quanto existe na nossa base</h2>
    <p>{p.base.observacao}</p>
    <h3>Cobertura dos dados consultados</h3><dl className="ficha-numeros">
      <div><dt>Municípios</dt><dd>{numero(p.cobertura.municipios)}</dd></div>
      <div><dt>Estados</dt><dd>{numero(p.cobertura.estados)}</dd></div>
      <div><dt>Fazendas lidas</dt><dd>{numero(p.cobertura.fazendas)}</dd></div>
      <div><dt>Área com potencial de restauração</dt><dd>{numero(p.cobertura.hectares, fmtHa)}</dd></div>
    </dl>
    {p.cobertura.observacao && <p className="legenda-frase">{p.cobertura.observacao}</p>}
  </section>
}

export function QuadroDestrava({ pedido, opcao }: { pedido: Pedido; opcao: IdOpcao }) {
  const publicada = pedido.opcoes.find((item) => item.id === opcao)
  const itens = publicada?.destrava ?? []
  return <section className="secao-painel quadro-destrava" aria-labelledby="destrava-titulo">
    <h2 id="destrava-titulo">O que destrava</h2>
    <p>Próximos passos para a opção {ROTULO_OPCAO[opcao].nome.toLowerCase()}.</p>
    {!!itens.length && <p className="legenda-frase">Uma fazenda pode aparecer em várias pendências. Não some as linhas. Certidões e regularização são etapas de conferência; não liberam créditos automaticamente.</p>}
    {itens.length ? <ul className="lista-afrouxar">{itens.map((item, indice) => <li key={`${indice}-${item.texto}`}>
      <strong>{item.texto}</strong>
      <span>{item.fazendas !== null && ` ${fmtInt(item.fazendas)} fazendas.`}{item.hectares !== null && ` ${fmtHa(item.hectares)}.`}{item.creditos_faixa ? ` Créditos estimados: P10 ${fmtInt(item.creditos_faixa.p10)}, P50 ${fmtInt(item.creditos_faixa.p50)}, P90 ${fmtInt(item.creditos_faixa.p90)}.` : item.creditos !== null && ` ${fmtInt(item.creditos)} créditos.`}</span>
    </li>)}</ul> : <p>As ações e seus ganhos desta opção exigem a consulta autenticada. A falta do dado não significa que a terra esteja sem pendências.</p>}
    {!!publicada?.o_que_falta?.length && <ul className="lista-afrouxar">{publicada.o_que_falta.map((texto, indice) => <li key={`${indice}-${texto}`}>{texto}</li>)}</ul>}
  </section>
}

/** O endereço conserva o subcaminho do Pages e nunca transforma a sessão fictícia em uma sessão da API. */
export function AcessoDetalhesLote() {
  const demo = new URL(location.href)
  demo.searchParams.set("demonstracao", "lotes")
  demo.hash = "/entrar"
  return <section className="secao-painel acesso-lote" aria-labelledby="acesso-lote-titulo">
    <h2 id="acesso-lote-titulo">Detalhes na área logada</h2>
    <p>Quais fazendas compõem cada lote, seus desenhos, medidas individuais e pendências ficam na área logada, com autorização da API para cada ficha.</p>
    <p>Enquanto o servidor não está conectado, conheça a tela com dados inteiramente fictícios. A demonstração não libera nem identifica fazendas reais.</p>
    <a className="botao" href={demo.href}>Conhecer a demonstração da área logada</a>
  </section>
}


const ROTULO_SOBREPOSICAO: Record<SituacaoSobreposicao, string> = { nao_verificada: "não verificada", verificada: "verificada" }
const textoSobreposicao = (situacao: SituacaoSobreposicao) => situacao === "verificada"
  ? "A camada de terra já comprometida foi cruzada: fazendas já comprometidas saíram do lote e as com risco de sobreposição estão marcadas."
  : "A camada de terra já comprometida ainda não foi cruzada. Ausência de indício não é terra livre; confira antes de contratar."

/** Lotes do recorte do pedido (estado, bioma ou Brasil) vindos do ponteiro do lote nacional. Desconhecido não é zero. */
export function LotesDoRecorte({ nacional }: { nacional: { resumo: ResumoNacional; recorte: RecorteNacional | null } }) {
  const { resumo, recorte: r } = nacional
  if (!r) return <section className="secao-painel lotes-recorte" aria-labelledby="recorte-titulo">
    <h2 id="recorte-titulo">Lotes do seu recorte</h2>
    <p>{resumo.estado === "publicado"
      ? "Município, vários estados ou vários biomas não têm resumo próprio. Escolha um estado, um bioma ou o Brasil inteiro para ver os três lotes."
      : "O resumo por estado, bioma e Brasil ainda não foi publicado. A falta do resumo não significa oferta zero."}</p>
  </section>
  const e = r.terra_em_espera
  return <section className="secao-painel lotes-recorte" aria-labelledby="recorte-titulo">
    <h2 id="recorte-titulo">Lotes em {r.nome}</h2>
    <p className="legenda-frase">{resumo.atualizado_em ? `Atualizado em ${dataLonga(resumo.atualizado_em)}. ` : ""}{resumo.aviso}</p>
    <h3>Terra pronta</h3>
    {r.vazio
      ? <p className="aviso" role="status"><Info size={20} aria-hidden="true" /><span>Nenhum lote pronto neste recorte com o pedido padrão.{e.fazendas ? ` Há ${fmtInt(e.fazendas)} fazendas em espera, abaixo.` : ""} Isso não é falta de terra: veja a terra em espera.</span></p>
      : <div className="tabela-rolagem" role="region" aria-label="Lotes prontos do recorte, deslize para ver todas as opções" tabIndex={0}>
        <table className="tabela-simples tabela-comparacao">
          <caption className="sr">Fazendas, área, créditos e meta de cada lote pronto em {r.nome}</caption>
          <thead><tr><th scope="col">Medida</th>{IDS_OPCAO.map((id) => <th scope="col" key={id}>{ROTULO_OPCAO[id].nome}</th>)}</tr></thead>
          <tbody>
            <tr><th scope="row">Fazendas (titulares e reservas)</th>{IDS_OPCAO.map((id) => <td key={id}>{numero(r.opcoes[id].fazendas)}</td>)}</tr>
            <tr><th scope="row">Pequenas agrupadas</th>{IDS_OPCAO.map((id) => <td key={id}>{numero(r.opcoes[id].pequenas)}</td>)}</tr>
            <tr><th scope="row">Área para restaurar</th>{IDS_OPCAO.map((id) => <td key={id}>{numero(r.opcoes[id].hectares, fmtHa)}</td>)}</tr>
            <tr><th scope="row">Créditos P10 (t CO2e)</th>{IDS_OPCAO.map((id) => <td key={id}>{numero(r.opcoes[id].creditos?.p10)}</td>)}</tr>
            <tr><th scope="row">Créditos P50 (t CO2e)</th>{IDS_OPCAO.map((id) => <td key={id}>{numero(r.opcoes[id].creditos?.p50)}</td>)}</tr>
            <tr><th scope="row">Créditos P90 (t CO2e)</th>{IDS_OPCAO.map((id) => <td key={id}>{numero(r.opcoes[id].creditos?.p90)}</td>)}</tr>
            <tr><th scope="row">Fecha a meta</th>{IDS_OPCAO.map((id) => <td key={id}>{r.opcoes[id].fecha_meta === null ? "Ainda não publicado" : r.opcoes[id].fecha_meta ? "Sim" : "Não"}</td>)}</tr>
          </tbody>
        </table>
      </div>}
    <h3>Terra em espera</h3>
    <p>Cumpre o pedido em tudo, menos no caminho da terra. <strong>Não habilita venda</strong> e não entra nos totais acima. {e.incluida_no_pedido ? "Neste pedido ela foi incluída." : "Para incluí-la, escolha posse em titulação e/ou assentamento no pedido."}</p>
    <dl className="ficha-numeros">
      <div><dt>Fazendas</dt><dd>{numero(e.fazendas)}</dd></div>
      <div><dt>Pequenas agrupadas</dt><dd>{numero(e.pequenas)}</dd></div>
      <div><dt>Área</dt><dd>{numero(e.hectares, fmtHa)}</dd></div>
      <div><dt>Créditos P50 somados</dt><dd>{numero(e.creditos_p50)}</dd></div>
    </dl>
    <p className="legenda-frase">Os créditos são a soma dos P50 de cada fazenda, não um quantil de carteira.</p>
    <h3>Sobreposição</h3>
    <p className={`sobreposicao sobreposicao-${r.sobreposicao}`}><strong>Sobreposição: {ROTULO_SOBREPOSICAO[r.sobreposicao]}.</strong> {textoSobreposicao(r.sobreposicao)}</p>
  </section>
}
