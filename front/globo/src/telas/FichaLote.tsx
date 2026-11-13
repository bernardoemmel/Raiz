import { useEffect, useState } from "react"
import { lerFichaCredito } from "../../../compartilhado/ficha-credito"
import type { IdOpcao, Pedido } from "../../../compartilhado/pedidos/tipos"
import { ROTULO_OPCAO, tituloDoPedido } from "../../../compartilhado/pedidos/texto"
import { pedidos } from "../pedidos"
import { dataTerra } from "../prospeccao"
import { linkPedido } from "../rota"
import { Cabecalho } from "../partes/Cabecalho"
import { Estado } from "../partes/Estado"
import { AvisoExemplo } from "../partes/pedido/AvisoExemplo"
import { FichaBanco } from "../partes/ficha-credito/FichaBanco"
import { GraficosLote } from "../partes/graficos/GraficosLote"
import "../partes/ficha-credito/ficha-credito.css"

/** A ficha do banco usa somente a opção autorizada do pedido, nunca os resumos abertos do Release. */
export function FichaLote({ id, opcao: opcaoId }: { id: string; opcao: IdOpcao }) {
  const [pedido, setPedido] = useState<Pedido | null | undefined>()
  const [erro, setErro] = useState<string | null>(null)
  useEffect(() => {
    document.title = `Ficha do lote ${ROTULO_OPCAO[opcaoId].nome.toLocaleLowerCase("pt-BR")}: Raíz`
    if (pedidos.publica) return
    let ativo = true
    setPedido(undefined); setErro(null)
    pedidos.pedido(id).then((valor) => { if (ativo) setPedido(valor) }, (e: Error) => { if (ativo) { setPedido(null); setErro(e.message) } })
    return () => { ativo = false }
  }, [id, opcaoId])

  const opcao = pedido?.opcoes.find((o) => o.id === opcaoId)
  const recebida = opcao?.ficha_credito
  // Mesmo um documento válido fica indisponível se pertencer à composição anterior ou a outra opção.
  const ficha = lerFichaCredito(recebida, { opcao_id: opcaoId, revisao_lote: pedido?.revisao_lote ?? null, exemplo: !!pedido?.exemplo })
  const bloqueada = pedidos.publica || !!pedido?.publicacao

  return <div className="tela-pedidos">
    <Cabecalho atual="pedidos" />
    <main id="conteudo" tabIndex={-1} className="pagina ficha-lote-credito">
      <a className="ficha-lote-voltar" href={linkPedido(id)}>Voltar ao pedido</a>
      <header className="ficha-lote-cabeca"><h1>Ficha resumida do lote</h1><p className="frase">{ROTULO_OPCAO[opcaoId].nome}</p><p className="criterio">Título, método, perdas, garantias e risco para a análise de crédito.</p></header>
      {bloqueada ? <Estado tipo="vazio" titulo="Ficha do lote na área de clientes"><p>O site aberto mostra somente o resumo das opções. Esta ficha exige a resposta autorizada da API para o seu pedido.</p></Estado>
        : pedido === undefined ? <Estado tipo="carregando" titulo="Conferindo a ficha autorizada do lote" />
          : !pedido || !opcao ? <Estado tipo="erro" titulo="Ficha do lote indisponível"><p>{erro || "Esta opção não foi publicada para o pedido desta conta."}</p></Estado>
            : <>
              <p>{tituloDoPedido(pedido.campos)}</p>
              <AvisoExemplo ativo={!!pedido.exemplo} />
              {ficha.estado === "indisponivel" && <p className="aviso" role="status">{ficha.aviso}</p>}
              {ficha.estado === "disponivel" && ficha.aviso && <p>{ficha.aviso}</p>}
              <details className="ficha-lote-identidade"><summary>Identidade e publicação da ficha</summary><dl>
                <dt>Versão do documento</dt><dd>{ficha.documento_versao ? <code>{ficha.documento_versao}</code> : "Ainda não publicada"}</dd>
                <dt>Publicação</dt><dd>{dataTerra(ficha.publicada_em)}. A publicação não substitui a revisão técnica de cada seção.</dd>
                <dt>Revisão do lote</dt><dd>{ficha.revisao_lote ? <code>{ficha.revisao_lote}</code> : "Ainda não informada"}</dd>
              </dl></details>
              <FichaBanco ficha={ficha} />
              <GraficosLote dados={ficha.resultados} demonstracao={!!pedido.exemplo} />
            </>}
    </main>
  </div>
}
