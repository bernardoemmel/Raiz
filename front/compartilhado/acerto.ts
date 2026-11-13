/** Contrato público: nenhum imóvel, linha de observação ou dado de proprietário. */
export const METRICAS_ACERTO = {
  wis: { nome: "Erro da faixa (WIS)", ajuda: "Combina largura e erros fora de P10 a P90. Menor é melhor; na unidade do alvo.", percentual: false },
  ae_mediana: { nome: "Erro absoluto da mediana", ajuda: "Distância entre P50 e o observado. Menor é melhor; na unidade do alvo.", percentual: false },
  cobertura_80: { nome: "Observações dentro de P10 a P90", ajuda: "Uma faixa calibrada inclui perto de 80% das observações.", percentual: true },
  ae: { nome: "Erro absoluto médio", ajuda: "Distância entre previsão e observação. Menor é melhor; na unidade do alvo.", percentual: false },
  eq: { nome: "Erro quadrático médio", ajuda: "Penaliza mais os erros grandes. Menor é melhor; na unidade do alvo ao quadrado.", percentual: false },
  brier: { nome: "Erro de probabilidade (Brier)", ajuda: "Menor é melhor. A escala depende do tipo de previsão; não compare alvos diferentes.", percentual: false },
  log_score: { nome: "Erro de probabilidade (log score)", ajuda: "Penaliza previsões confiantes que erraram. Menor é melhor.", percentual: false },
  acerto: { nome: "Categorias corretas", ajuda: "Parcela de classificações corretas. Em chances, usa o corte de 50%; não mede calibração.", percentual: true },
} as const
export type MetricaAcerto = keyof typeof METRICAS_ACERTO
const POR_TIPO: Record<string, MetricaAcerto[]> = { faixa: ["wis", "ae_mediana", "cobertura_80"], numero: ["ae", "eq"], chance: ["brier", "log_score", "acerto"], categoria: ["acerto", "brier"] }
export interface VersaoAcerto {
  modelo: string; versao: string; alvo: string; horizonte_dias: number; tipo: string
  avaliacao: "ao_vivo" | "backtest"
  criterio_temporal: "observacao_na_data_alvo"
  cronologia: "congelada_antes_da_observacao" | "backtest_declarado"
  comparacoes: number; imoveis_observados: number
  primeiro_corte: string; ultimo_corte: string; ultima_observacao: string
  metricas: Partial<Record<MetricaAcerto, number>>
}
export interface ResumoAcerto {
  schema: "raiz.acerto.publico.v1"
  gerado_em: string | null
  fonte: "Banco de aprendizado da Raíz"
  minimo_imoveis: number
  versoes: VersaoAcerto[]
}
export const ACERTO_AUSENTE: ResumoAcerto = { schema: "raiz.acerto.publico.v1", gerado_em: null, fonte: "Banco de aprendizado da Raíz", minimo_imoveis: 5, versoes: [] }
const inteiro = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0
const id = (v: unknown): v is string => typeof v === "string" && /^[a-z0-9][a-z0-9_.+:-]{0,119}$/i.test(v)
const dia = (v: unknown): v is string => typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0, 10) === v
const objeto = (v: unknown): Record<string, unknown> => v && typeof v === "object" && !Array.isArray(v) ? v as Record<string, unknown> : {}

/** Reconstrói a allowlist em vez de espalhar a resposta da API no arquivo público. */
export function lerResumoAcerto(valor: unknown): ResumoAcerto {
  const r = objeto(valor)
  if (r.schema !== ACERTO_AUSENTE.schema || r.fonte !== ACERTO_AUSENTE.fonte || !inteiro(r.minimo_imoveis) || r.minimo_imoveis < 5 || !Array.isArray(r.versoes)) throw new Error("Formato do resumo de acerto inválido.")
  if (r.gerado_em !== null && (typeof r.gerado_em !== "string" || !Number.isFinite(Date.parse(r.gerado_em)))) throw new Error("Data do resumo de acerto inválida.")
  if (r.gerado_em === null && r.versoes.length) throw new Error("As observações precisam da data de publicação.")
  const versoes = r.versoes.map((valor) => {
    const v = objeto(valor)
    if ((v.avaliacao !== "ao_vivo" && v.avaliacao !== "backtest") || !id(v.modelo) || !id(v.versao) || !id(v.alvo) || (!inteiro(v.horizonte_dias) || v.horizonte_dias === 0) || typeof v.tipo !== "string" || !Object.hasOwn(POR_TIPO, v.tipo) || !inteiro(v.comparacoes) || !inteiro(v.imoveis_observados) || v.imoveis_observados < (r.minimo_imoveis as number) || v.comparacoes < v.imoveis_observados || !dia(v.primeiro_corte) || !dia(v.ultimo_corte) || !dia(v.ultima_observacao) || v.primeiro_corte > v.ultimo_corte || v.ultima_observacao <= v.primeiro_corte) throw new Error("Grupo do resumo de acerto inválido ou pequeno demais.")
    if (v.criterio_temporal !== "observacao_na_data_alvo" || v.cronologia !== (v.avaliacao === "ao_vivo" ? "congelada_antes_da_observacao" : "backtest_declarado")) throw new Error("O grupo não comprova a referência temporal da avaliação.")
    const dataAlvo = Date.parse(v.ultimo_corte) + v.horizonte_dias * 86400000
    if (Date.parse(v.ultima_observacao) !== dataAlvo) throw new Error("A observação não corresponde ao horizonte avaliado.")
    const publicado = Date.parse(r.gerado_em as string)
    if (Date.parse(v.ultima_observacao) > publicado || Date.parse(v.ultimo_corte) + v.horizonte_dias * 86400000 > publicado) throw new Error("O grupo tem observação futura ou previsão ainda não maturada.")
    const metricas: Partial<Record<MetricaAcerto, number>> = {}
    const medidas = objeto(v.metricas)
    for (const nome of POR_TIPO[v.tipo]) {
      const n = medidas[nome]
      if (typeof n !== "number" || !Number.isFinite(n) || n < 0 || (METRICAS_ACERTO[nome].percentual && n > 1)) throw new Error("Métrica de acerto inválida.")
      metricas[nome] = n
    }
    return { modelo: v.modelo, versao: v.versao, alvo: v.alvo, horizonte_dias: v.horizonte_dias, tipo: v.tipo, avaliacao: v.avaliacao as "ao_vivo" | "backtest", criterio_temporal: "observacao_na_data_alvo" as const, cronologia: v.cronologia as VersaoAcerto["cronologia"], comparacoes: v.comparacoes, imoveis_observados: v.imoveis_observados, primeiro_corte: v.primeiro_corte, ultimo_corte: v.ultimo_corte, ultima_observacao: v.ultima_observacao, metricas }
  })
  return { schema: ACERTO_AUSENTE.schema, fonte: ACERTO_AUSENTE.fonte, gerado_em: r.gerado_em as string | null, minimo_imoveis: r.minimo_imoveis, versoes }
}

export function fonteAcerto({ api, base = "/", pedir = fetch }: { api?: string; base?: string; pedir?: typeof fetch }) {
  return async () => {
    const url = api ? `${api.replace(/\/$/, "")}/acerto/resumo` : `${base.replace(/\/$/, "")}/acerto/placar.json`
    const resposta = await pedir(url, { headers: { Accept: "application/json" }, cache: "no-store" })
    if (!resposta.ok) throw new Error("Não foi possível consultar o aprendizado agora.")
    return lerResumoAcerto(await resposta.json())
  }
}
