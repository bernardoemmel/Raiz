import { Info } from "lucide-react"

/** Enquanto o back-end de pedidos não responde: a tela diz que os números são de exemplo. */
export function AvisoExemplo({ ativo }: { ativo: boolean }) {
  if (!ativo) return null
  return (
    <p className="aviso aviso-exemplo" role="note">
      <Info size={20} aria-hidden="true" />
      <span>
        <strong>Demonstração com dados fictícios.</strong> Fazendas, contornos e números são inventados para conhecer a tela, no mesmo formato da API. Este exemplo fixo não representa os lotes reais do Release nem recalcula seus filtros. Nenhum contato, cobrança ou acesso a dados pagos é iniciado.
      </span>
    </p>
  )
}
