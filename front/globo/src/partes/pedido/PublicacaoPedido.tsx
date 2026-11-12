import { Info } from "lucide-react"
import { fmtHa, fmtInt, UFS } from "../../../../compartilhado/formato"
import { dataLonga, fmtUsd, ROTULO_OPCAO } from "../../../../compartilhado/pedidos/texto"
import type { IdOpcao, Pedido, PublicacaoLote } from "../../../../compartilhado/pedidos/tipos"

const numero = (valor: number | null | undefined, formatar: (n: number) => string = fmtInt) =>
  typeof valor === "number" && Number.isFinite(valor) ? formatar(valor) : "Ainda não publicado"

export function AvisoPublicacao({ publicacao: p }: { publicacao: PublicacaoLote }) {
  return <div className="aviso fontes-pedido" role="status">
    <Info size={20} aria-hidden="true" />
    <div><strong>{p.estado === "publicado" ? "Cenário publicado no Release." : "O lote ainda não foi publicado."}</strong>
      {p.estado !== "publicado" && <p>{p.aviso}</p>}
      <p>Os filtros deste pedido ainda não foram recalculados pelo motor. A comparação abaixo mantém os valores do cenário publicado, quando disponíveis.</p>
      <details><summary>Fonte, data e limites do cenário</summary>
      {p.estado === "publicado" && <p>{p.aviso}</p>}
      {p.estado === "publicado" && <p>{UFS[p.uf] ?? p.uf}, cenário {p.cenario}. Meta publicada: {numero(p.volume_creditos)} créditos. Preço do contrato: {numero(p.preco_contrato_usd, fmtUsd)} por crédito.</p>}
      <p>Fonte: <a href={p.fonte} target="_blank" rel="noreferrer">Release de dados da Raíz</a>. Atualização: {p.atualizado_em ? dataLonga(p.atualizado_em) : "ainda não informada"}. Modelo: {p.modelo_versao ?? "ainda não informado"}.</p>
      </details>
    </div>
  </div>
}

export function BasePublicada({ publicacao: p }: { publicacao: PublicacaoLote }) {
  const b = p.base
  return <section className="secao-painel quadro-base" aria-labelledby="base-titulo">
    <h2 id="base-titulo">Quanto existe na nossa base</h2>
    <p>{b.observacao}</p>
    <dl className="ficha-numeros">
      <div><dt>Fazendas com oferta pronta</dt><dd>{numero(b.fazendas)}</dd></div>
      <div><dt>Área da oferta pronta</dt><dd>{numero(b.hectares, fmtHa)}</dd></div>
      <div><dt>Créditos líquidos P10</dt><dd>{numero(b.creditos.p10)}</dd></div>
      <div><dt>Créditos líquidos P50</dt><dd>{numero(b.creditos.p50)}</dd></div>
      <div><dt>Créditos líquidos P90</dt><dd>{numero(b.creditos.p90)}</dd></div>
    </dl>
    {p.estado === "publicado" && <p className="legenda-frase">Oferta do cenário publicado. Para saber quanto atende exatamente aos filtros do pedido, falta recalcular o lote.</p>}
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
  const publicada = pedido.publicacao?.opcoes.find((item) => item.id === opcao)
  const itens = publicada?.destrava ?? pedido.base.afrouxar.map((item) => ({ texto: item.texto, fazendas: null, hectares: null, creditos: item.ganho, creditos_faixa: null, tipo: "regularizacao" as const, somavel: false as const }))
  return <section className="secao-painel quadro-destrava" aria-labelledby="destrava-titulo">
    <h2 id="destrava-titulo">O que destrava</h2>
    <p>Próximos passos para a opção {ROTULO_OPCAO[opcao].nome.toLowerCase()}.</p>
    {!!itens.length && <p className="legenda-frase">Uma fazenda pode aparecer em várias pendências. Não some as linhas. Certidões e regularização são etapas de conferência; não liberam créditos automaticamente.</p>}
    {itens.length ? <ul className="lista-afrouxar">{itens.map((item, indice) => <li key={`${indice}-${item.texto}`}>
      <strong>{item.texto}</strong>
      <span>{item.fazendas !== null && ` ${fmtInt(item.fazendas)} fazendas.`}{item.hectares !== null && ` ${fmtHa(item.hectares)}.`}{item.creditos_faixa ? ` Créditos estimados: P10 ${fmtInt(item.creditos_faixa.p10)}, P50 ${fmtInt(item.creditos_faixa.p50)}, P90 ${fmtInt(item.creditos_faixa.p90)}.` : item.creditos !== null && ` ${fmtInt(item.creditos)} créditos.`}</span>
    </li>)}</ul> : <p>As ações e seus ganhos ainda não foram publicados para esta opção. A falta do dado não significa que a terra esteja sem pendências.</p>}
    {!!publicada?.o_que_falta.length && <ul className="lista-afrouxar">{publicada.o_que_falta.map((texto, indice) => <li key={`${indice}-${texto}`}>{texto}</li>)}</ul>}
  </section>
}
