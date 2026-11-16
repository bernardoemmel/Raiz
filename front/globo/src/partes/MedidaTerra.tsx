import type { MedidaTerra } from "../../../compartilhado/prospeccao"
import { dataTerra, numeroTerra } from "../prospeccao"

export function Medida({ dado }: { dado: MedidaTerra }) {
  return <span className="medida-terra">
    <strong>{numeroTerra(dado.valor)}{dado.valor !== null ? ` ${dado.unidade}` : ""}</strong>
    <small>{dado.estimado ? "Estimativa. " : ""}Fonte: {dado.fonte || "Não informada"}.</small>
    <small>{dado.data_referencia ? `Referência: ${dataTerra(dado.data_referencia)}.` : "Data da fonte não informada."}{dado.data_corte ? ` Corte da base: ${dataTerra(dado.data_corte)}.` : ""}</small>
  </span>
}
