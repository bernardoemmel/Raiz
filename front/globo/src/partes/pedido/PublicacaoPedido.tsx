import { Info } from "lucide-react"
import { fmtHa, fmtInt } from "../../../../compartilhado/formato"
import { dataLonga, ROTULO_OPCAO } from "../../../../compartilhado/pedidos/texto"
import type { IdOpcao, Pedido, PublicacaoLote } from "../../../../compartilhado/pedidos/tipos"

const numero = (valor: number | null | undefined, formatar: (n: number) => string = fmtInt) =>
  typeof valor === "number" && Number.isFinite(valor) ? formatar(valor) : "Ainda não publicado"

export function AvisoPublicacao({ publicacao: p }: { publicacao: PublicacaoLote }) {
  return <div className="aviso fontes-pedido" role="status">
    <Info size={20} aria-hidden="true" />
    <div><strong>Lotes na área autenticada.</strong><p>{p.aviso}</p>
      <p>Os critérios ficam salvos neste navegador. Para calcular e comparar os lotes do pedido, a conexão com a API da Raíz precisa estar ativa.</p>
      <details><summary>Fonte, data e limites da consulta</summary>
        <p>Fonte: <a href={p.fonte} target="_blank" rel="noreferrer">Publicação básica da Raíz</a>. Atualização: {p.atualizado_em ? dataLonga(p.atualizado_em) : "ainda não informada"}.</p>
        <p>A cobertura usa o recorte por estado e município. Os filtros financeiros, de método e de interesse não são aplicados aos agregados públicos.</p>
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
  const publicada = pedido.publicacao?.opcoes.find((item) => item.id === opcao)
  const itens = publicada?.destrava ?? pedido.base.afrouxar.map((item) => ({ texto: item.texto, fazendas: null, hectares: null, creditos: item.ganho, creditos_faixa: null, tipo: "regularizacao" as const, somavel: false as const }))
  return <section className="secao-painel quadro-destrava" aria-labelledby="destrava-titulo">
    <h2 id="destrava-titulo">O que destrava</h2>
    <p>Próximos passos para a opção {ROTULO_OPCAO[opcao].nome.toLowerCase()}.</p>
    {!!itens.length && <p className="legenda-frase">Uma fazenda pode aparecer em várias pendências. Não some as linhas. Certidões e regularização são etapas de conferência; não liberam créditos automaticamente.</p>}
    {itens.length ? <ul className="lista-afrouxar">{itens.map((item, indice) => <li key={`${indice}-${item.texto}`}>
      <strong>{item.texto}</strong>
      <span>{item.fazendas !== null && ` ${fmtInt(item.fazendas)} fazendas.`}{item.hectares !== null && ` ${fmtHa(item.hectares)}.`}{item.creditos_faixa ? ` Créditos estimados: P10 ${fmtInt(item.creditos_faixa.p10)}, P50 ${fmtInt(item.creditos_faixa.p50)}, P90 ${fmtInt(item.creditos_faixa.p90)}.` : item.creditos !== null && ` ${fmtInt(item.creditos)} créditos.`}</span>
    </li>)}</ul> : <p>As ações e seus ganhos desta opção exigem a consulta autenticada. A falta do dado não significa que a terra esteja sem pendências.</p>}
    {!!publicada?.o_que_falta.length && <ul className="lista-afrouxar">{publicada.o_que_falta.map((texto, indice) => <li key={`${indice}-${texto}`}>{texto}</li>)}</ul>}
  </section>
}
