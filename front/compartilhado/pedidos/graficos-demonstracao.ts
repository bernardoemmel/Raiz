import type { Faixa } from "./tipos"
import type { FonteResultado, MedidaConfirmada, ReferenciaResultado, ResultadosGraficos } from "../graficos-resultados"

/** Só o modo simulado chama esta função. Todas as etapas e observações são fictícias. */
export function resultadosDemonstracao({ area_ha, inicio, fim, creditos }: { area_ha: number; inicio: string; fim: string; creditos: Faixa }): ResultadosGraficos {
  const horizonte = (Date.parse(fim) - Date.parse(inicio)) / 86400000
  const depois = new Date(Date.parse(fim) + 86400000).toISOString()
  const meio = new Date(Date.parse(inicio) + Math.floor(horizonte / 2) * 86400000).toISOString().slice(0, 10)
  const referencia: ReferenciaResultado = { classe: "credito_carbono", metrica: "credito_liquido", unidade: "tCO2e", escala: "lote", area_base_ha: area_ha, inicio, fim, horizonte_dias: horizonte }
  const fonte = (id: string, data: string): FonteResultado => ({ nome: "Demonstração sintética", registro_id: `sintetico-${id}`, data })
  const valor = (n: number) => Math.round(n * 100) / 100
  const medida = (n: number, natureza: MedidaConfirmada["natureza"], data: string): MedidaConfirmada => ({ natureza, valor: valor(n), fonte: fonte(`${natureza}-${data}`, data) })
  return {
    schema: "raiz.resultados.graficos.v1", origem: "demonstracao", gerado_em: depois,
    contratos: [{ id: "serie-sintetica", metodo: "regeneracao_assistida", referencia, regime: "acumulado", marcos: [
      { data: inicio, contratado: medida(creditos.p50, "contrato_assinado", inicio), emitido: null, entregue: null },
      { data: meio, contratado: medida(creditos.p50, "contrato_assinado", meio), emitido: medida(0, "emissao_registrada", meio), entregue: null },
      { data: fim, contratado: medida(creditos.p50, "contrato_assinado", fim), emitido: medida(creditos.p50 * .8, "emissao_registrada", fim), entregue: medida(creditos.p50 * .5, "entrega_comprovada", fim) },
    ] }],
    comparacoes: ["regeneracao_assistida", "semeadura_direta", "plantio_total"].map((metodo, i) => ({
      id: `metodo-sintetico-${i + 1}`, metodo, modelo: "ensaio_interface", versao: "v1-sintetica", avaliacao: "ao_vivo",
      previsao: { referencia, corte: inicio, congelada_em: `${inicio}T00:00:00Z`, p10: creditos.p10, p50: creditos.p50, p90: creditos.p90, fonte: fonte(`previsao-${i + 1}`, inicio) },
      observado: { referencia, data: fim, registrado_em: depois, valor: valor(creditos.p50 * [.75, .9, 1.1][i]), fonte: fonte(`observacao-${i + 1}`, fim) },
    })),
  }
}
