/** Compatibilidade do antigo ponteiro público. Lotes financeiros pertencem à API autenticada.
 * Nunca interpreta um snapshot financeiro local ou um arquivo antigo encontrado no navegador.
 */
import type { PublicacaoLote } from "./tipos"

export function projetarPublicacaoLote(_valor: unknown): PublicacaoLote {
  return {
    estado: "ausente",
    aviso: "Lotes, créditos, TIR e pendências detalhadas são consultados pela API autenticada. O site aberto mostra somente a cobertura regional e a situação básica da terra. Nenhum lote financeiro é baixado do Release público.",
    fonte: "https://github.com/bernardoemmel/Raiz/releases/tag/dados",
    atualizado_em: null,
    cenario: "central_r11",
    modelo_versao: null,
    uf: "PA",
    volume_creditos: null,
    preco_contrato_usd: null,
    pedido_recalculado: false,
    base: {
      fazendas: null, hectares: null, creditos: { p10: null, p50: null, p90: null },
      observacao: "A cobertura abaixo usa somente agregados por estado e município. Os critérios financeiros e os lotes exigem uma consulta autenticada.",
    },
    cobertura: { municipios: null, estados: null, fazendas: null, hectares: null },
    opcoes: [],
  }
}

/** Mesmo um cache legado marcado como publicado não reabre o acesso às camadas pagas. */
export function lerPublicacaoLote(_valor: unknown): PublicacaoLote {
  return projetarPublicacaoLote(null)
}
