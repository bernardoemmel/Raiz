import { Info } from "lucide-react"

/** Enquanto o back-end de pedidos não responde: a tela diz que os números são de exemplo. */
export function AvisoExemplo({ ativo }: { ativo: boolean }) {
  if (!ativo) return null
  return (
    <p className="aviso aviso-exemplo" role="note">
      <Info size={20} aria-hidden="true" />
      <span>
        <strong>Resposta de exemplo.</strong> O back-end de pedidos ainda não está ligado: o lote sai de fazendas aptas de
        verdade, mas custo, TIR, chance e o andamento dos contatos são simulados, no mesmo formato da resposta final.
      </span>
    </p>
  )
}
