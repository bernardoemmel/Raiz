import { SECOES_FICHA_CREDITO, type FichaCredito, type SecaoFichaCreditoId } from "../../../../compartilhado/ficha-credito"
import { dataTerra } from "../../prospeccao"
import { FatosCredito } from "./FatosCredito"

const TITULOS: Record<SecaoFichaCreditoId, string> = { titulo: "Título", metodo: "Método", perdas: "Perdas", garantias: "Garantias", risco_nao_entrega: "Risco de não entrega" }
const AUSENCIAS: Record<SecaoFichaCreditoId, string> = {
  titulo: "A situação dos títulos e os documentos que sustentam esta carteira ainda não foram publicados nesta ficha.",
  metodo: "O método, o horizonte e a classe de evidência compatíveis ainda não foram publicados nesta ficha.",
  perdas: "As perdas, suas causas e o que foi descontado do resultado ainda não foram publicados nesta ficha.",
  garantias: "As garantias e suas condições ainda não foram publicadas nesta ficha.",
  risco_nao_entrega: "A avaliação de risco de não entrega e seus limites ainda não foram publicados nesta ficha.",
}

/** Mesma sequência em toda opção; revisão técnica nunca é substituída pela data em que a tela foi aberta. */
export function FichaBanco({ ficha }: { ficha: FichaCredito }) {
  return <div className="ficha-banco">
    {SECOES_FICHA_CREDITO.map((id) => {
      const secao = ficha.secoes[id]
      return <section key={id} className="secao-ficha-banco" aria-labelledby={`ficha-banco-${id}`}>
        <h2 id={`ficha-banco-${id}`}>{TITULOS[id]}</h2>
        <p className="revisao-ficha">{secao.revisado_em ? <>Revisão da seção: <time dateTime={secao.revisado_em}>{dataTerra(secao.revisado_em)}</time>.</> : "Data de revisão da seção não informada."}</p>
        <p>{secao.texto || AUSENCIAS[id]}</p>
        <p className="fonte-ficha">Fonte: {secao.fonte || "não informada"}. Referência: {dataTerra(secao.data_referencia)}.</p>
        {id === "metodo" && <FatosCredito ficha={ficha} />}
      </section>
    })}
  </div>
}
