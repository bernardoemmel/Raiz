/** Somente no modo ?demonstracao=lotes. Estes documentos e datas são inteiramente fictícios. */
import { fichaCreditoIndisponivel, SECOES_FICHA_CREDITO, TEXTOS_SECAO_FICHA, type FichaCredito } from "../ficha-credito"
import type { Opcao } from "./tipos"
import { resultadosDemonstracao } from "./graficos-demonstracao"

export function fichaCreditoDemonstracao(opcao: Pick<Opcao, "id" | "creditos" | "hectares">): FichaCredito {
  // Um denominador inventado, explicitamente documentado na demonstração; não é inferência sobre o Release.
  const elegivel = opcao.hectares * 0.8
  return {
    ...fichaCreditoIndisponivel(opcao.id, null, true), estado: "disponivel",
    documento_versao: `demonstracao-ficha-v1-${opcao.id}`, publicada_em: "2026-11-12T12:00:00Z",
    aviso: "Demonstração inteiramente fictícia. Números, fontes, datas de revisão e documentos abaixo não pertencem a fazendas reais, ao Release ou a uma oferta de crédito.",
    base: { horizonte_anos: 25, unidade: "tCO2e", metrica: "credito_liquido", escopo_carteira: "titulares", inicio: "2000-01-01", fim: "2025-01-01", classe_ativo: "credito_carbono", classe_evidencia: "estimativa_modelo", metodo: "regeneracao_assistida", modelo_versao: "demonstracao-ficticia-v1", fonte: "Demonstração fictícia", data_referencia: "2026-11-10", evidencia_id: `demonstracao-creditos-${opcao.id}` },
    creditos_lote: { ...opcao.creditos },
    creditos_por_ha: { p10: opcao.creditos.p10 / elegivel, p50: opcao.creditos.p50 / elegivel, p90: opcao.creditos.p90 / elegivel },
    area_total_ha: opcao.hectares, area_elegivel_ha: elegivel,
    fonte_area: "Demonstração fictícia", data_referencia_area: "2026-11-10", evidencia_area_id: `demonstracao-area-${opcao.id}`,
    exclusoes: [{ motivo: "inelegivel_metodo", hectares: opcao.hectares - elegivel, fonte: "Demonstração fictícia", data_referencia: "2026-11-10" }],
    secoes: Object.fromEntries(SECOES_FICHA_CREDITO.map((id, i) => [id, { texto: TEXTOS_SECAO_FICHA[id][0], fonte: "Demonstração fictícia", data_referencia: id === "metodo" ? "2026-11-10" : "2026-11-09", revisado_em: i === 3 ? null : "2026-11-11" }])) as FichaCredito["secoes"],
    resultados: resultadosDemonstracao({ area_ha: elegivel, escopo_carteira: "titulares", inicio: "2000-01-01", fim: "2025-01-01", creditos: opcao.creditos }),
  }
}
