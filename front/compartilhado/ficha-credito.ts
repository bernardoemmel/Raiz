/** Ficha agregada privada do lote. Ausência não autoriza derivar números dos resumos públicos. */
import { lerResultadosGraficos, type ResultadosGraficos } from "./graficos-resultados"
export type SecaoFichaCreditoId = "titulo" | "metodo" | "perdas" | "garantias" | "risco_nao_entrega"
export interface SecaoFichaCredito {
  texto: string | null
  fonte: string | null
  data_referencia: string | null
  /** Revisão técnica desta seção, nunca a data de publicação, consulta ou build. */
  revisado_em: string | null
}
export interface BaseFichaCredito {
  horizonte_anos: number
  unidade: "tCO2e"
  /** Declara quais imóveis compõem tanto o numerador como a área elegível. */
  escopo_carteira: "titulares" | "titulares_e_reservas"
  inicio: string | null
  fim: string | null
  classe_ativo: "credito_carbono" | "flag"
  classe_evidencia: "estimativa_modelo" | "verificado" | "emitido" | "entregue"
  metodo: string
  modelo_versao: string
  fonte: string
  data_referencia: string
  evidencia_id: string
}
export interface ExclusaoFichaCredito {
  motivo: "embargo" | "terra_indigena" | "uc_protecao_integral" | "projeto_carbono" | "inelegivel_metodo" | "outra"
  hectares: number | null
  fonte: string | null
  data_referencia: string | null
}
export interface FichaCredito {
  contrato: "ficha_credito"
  versao: 1
  estado: "disponivel" | "indisponivel"
  /** Hash do conteúdo validado do documento, quando existe. Não é código de fazenda. */
  documento_versao: string | null
  publicada_em: string | null
  revisao_lote: string | null
  opcao_id: "barata" | "segura" | "compacta"
  exemplo: boolean
  aviso: string
  /** Uma única base para ambos os lados da tabela. */
  base: BaseFichaCredito | null
  creditos_lote: { p10: number; p50: number; p90: number } | null
  /** Divisão dos mesmos quantis pela área elegível fixa documentada. Nunca pela área total do CAR. */
  creditos_por_ha: { p10: number; p50: number; p90: number } | null
  area_total_ha: number | null
  area_elegivel_ha: number | null
  fonte_area: string | null
  data_referencia_area: string | null
  evidencia_area_id: string | null
  /** null: exclusões não documentadas. []: conferidas e nenhuma identificada. Áreas podem se sobrepor. */
  exclusoes: ExclusaoFichaCredito[] | null
  secoes: Record<SecaoFichaCreditoId, SecaoFichaCredito>
  resultados?: ResultadosGraficos | null
}

export const SECOES_FICHA_CREDITO: readonly SecaoFichaCreditoId[] = ["titulo", "metodo", "perdas", "garantias", "risco_nao_entrega"]
export const FONTES_FICHA_CREDITO = ["Raíz, motor de lotes", "Raíz, revisão técnica", "SICAR, polígono do CAR", "Ibama, embargos", "Funai, terras indígenas", "CNUC, unidades de conservação", "Registro de projeto de carbono", "Registro de emissão", "Registro de entrega", "Contrato assinado"] as const
export const TEXTOS_SECAO_FICHA: Record<SecaoFichaCreditoId, readonly string[]> = {
  titulo: ["Documentação da terra ainda não conferida.", "Documentação da terra conferida; acompanhar a validade das certidões.", "Há pendências documentais no lote."],
  metodo: ["Estimativa agregada do motor para a composição e o horizonte desta ficha.", "Resultado verificado para a composição e o horizonte desta ficha."],
  perdas: ["Perdas incorporadas na estimativa do motor; conferir as premissas na fonte.", "Perdas ainda não documentadas para este horizonte."],
  garantias: ["Garantias ainda não documentadas.", "Garantias documentadas; conferir escopo, validade e condições na fonte."],
  risco_nao_entrega: ["Risco de não entrega ainda não avaliado.", "Risco de não entrega avaliado; conferir as condições e limitações na fonte."],
}

export function fichaCreditoIndisponivel(opcao_id: FichaCredito["opcao_id"], revisao_lote: string | null = null, exemplo = false): FichaCredito {
  return {
    contrato: "ficha_credito", versao: 1, estado: "indisponivel", documento_versao: null, publicada_em: null,
    revisao_lote, opcao_id, exemplo,
    aviso: "O motor ainda não publicou uma ficha com horizonte, evidência e área elegível compatíveis. Os totais disponíveis não foram convertidos em créditos por hectare.",
    base: null, creditos_lote: null, creditos_por_ha: null, area_total_ha: null, area_elegivel_ha: null,
    fonte_area: null, data_referencia_area: null, evidencia_area_id: null, exclusoes: null,
    secoes: Object.fromEntries(SECOES_FICHA_CREDITO.map(id => [id, { texto: null, fonte: null, data_referencia: null, revisado_em: null }])) as FichaCredito["secoes"],
  }
}

const registro = (v: unknown): Record<string, unknown> => v && typeof v === "object" && !Array.isArray(v) ? v as Record<string, unknown> : {}
const falha = (): never => { throw new Error("Ficha sem evidência compatível.") }
const numero = (v: unknown): number => typeof v === "number" && Number.isFinite(v) && v >= 0 ? v : falha()
const texto = (v: unknown): string => typeof v === "string" && v.trim().length > 0 && v.length <= 1200 && !/[<>\u0000-\u001f]/.test(v) ? v : falha()
const id = (v: unknown): string => typeof v === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:+/-]{0,119}$/.test(v) ? v : falha()
const dia = (v: unknown): string => typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0, 10) === v ? v : falha()
const opcional = <T>(v: unknown, ler: (v: unknown) => T): T | null => v === null ? null : ler(v)
function faixa(v: unknown) {
  const r = registro(v), p10 = numero(r.p10), p50 = numero(r.p50), p90 = numero(r.p90)
  if (p10 > p50 || p50 > p90) return falha()
  return { p10, p50, p90 }
}

/** Projeção positiva; legado, inconsistência e revisão antiga viram desconhecido, jamais zero. */
export function lerFichaCredito(valor: unknown, esperado: { opcao_id: FichaCredito["opcao_id"]; revisao_lote: string | null; exemplo: boolean }): FichaCredito {
  const ausente = fichaCreditoIndisponivel(esperado.opcao_id, esperado.revisao_lote, esperado.exemplo)
  try {
    const r = registro(valor), b = registro(r.base)
    if (r.contrato !== "ficha_credito" || r.versao !== 1 || r.estado !== "disponivel"
      || r.opcao_id !== esperado.opcao_id || r.revisao_lote !== esperado.revisao_lote || r.exemplo !== esperado.exemplo) return ausente
    if (!esperado.exemplo && (typeof r.revisao_lote !== "string" || !/^[a-f0-9]{64}$/.test(r.revisao_lote))) return ausente
    const documento_versao = typeof r.documento_versao === "string" && (/^[a-f0-9]{64}$/.test(r.documento_versao) || (esperado.exemplo && r.documento_versao === `demonstracao-ficha-v1-${esperado.opcao_id}`)) ? r.documento_versao : falha()
    const publicada_em = typeof r.publicada_em === "string" && /^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(r.publicada_em) && Number.isFinite(Date.parse(r.publicada_em)) && Date.parse(r.publicada_em) <= Date.now() ? r.publicada_em : falha()
    const limite = publicada_em.slice(0, 10)
    const referencia = (v: unknown) => { const d = dia(v); return d <= limite ? d : falha() }
    const origem = (v: unknown) => { const t = texto(v); return (FONTES_FICHA_CREDITO as readonly string[]).includes(t) || (esperado.exemplo && t === "Demonstração fictícia") ? t : falha() }
    const horizonte_anos = numero(b.horizonte_anos), inicio = opcional(b.inicio, dia), fim = opcional(b.fim, dia)
    if (!Number.isInteger(horizonte_anos) || horizonte_anos < 1 || horizonte_anos > 100 || (inicio === null) !== (fim === null)) return ausente
    if (inicio !== null && fim !== null) {
      const esperadoFim = new Date(inicio)
      esperadoFim.setUTCFullYear(esperadoFim.getUTCFullYear() + horizonte_anos)
      // O aniversário de 29/02 é 28/02 quando o ano final não for bissexto.
      if (inicio.slice(5) === "02-29" && esperadoFim.getUTCMonth() === 2) esperadoFim.setUTCDate(0)
      if (esperadoFim.toISOString().slice(0, 10) !== fim) return ausente
    }
    if (b.unidade !== "tCO2e" || !["titulares", "titulares_e_reservas"].includes(String(b.escopo_carteira))
      || !["credito_carbono", "flag"].includes(String(b.classe_ativo))
      || !["estimativa_modelo", "verificado", "emitido", "entregue"].includes(String(b.classe_evidencia))
      || (b.classe_ativo === "flag" && ["emitido", "entregue"].includes(String(b.classe_evidencia)))) return ausente
    const base: BaseFichaCredito = { horizonte_anos, inicio, fim, unidade: "tCO2e", escopo_carteira: b.escopo_carteira as BaseFichaCredito["escopo_carteira"], classe_ativo: b.classe_ativo as BaseFichaCredito["classe_ativo"], classe_evidencia: b.classe_evidencia as BaseFichaCredito["classe_evidencia"], metodo: id(b.metodo), modelo_versao: id(b.modelo_versao), fonte: origem(b.fonte), data_referencia: referencia(b.data_referencia), evidencia_id: id(b.evidencia_id) }
    if (base.classe_evidencia !== "estimativa_modelo" && (fim === null || fim > base.data_referencia)) return ausente
    const creditos_lote = faixa(r.creditos_lote), area_total_ha = opcional(r.area_total_ha, numero), area_elegivel_ha = opcional(r.area_elegivel_ha, numero)
    const fonte_area = opcional(r.fonte_area, origem), data_referencia_area = opcional(r.data_referencia_area, referencia), evidencia_area_id = opcional(r.evidencia_area_id, id)
    if (area_elegivel_ha !== null && (area_elegivel_ha <= 0 || (area_total_ha !== null && area_elegivel_ha > area_total_ha) || !fonte_area || !data_referencia_area || !evidencia_area_id)) return ausente
    if ((area_total_ha !== null || area_elegivel_ha !== null) && (!fonte_area || !data_referencia_area || !evidencia_area_id)) return ausente
    if (area_total_ha === null && area_elegivel_ha === null && (fonte_area !== null || data_referencia_area !== null || evidencia_area_id !== null)) return ausente
    if (area_elegivel_ha === null && r.creditos_por_ha !== null) return ausente
    const creditos_por_ha = opcional(r.creditos_por_ha, faixa)
    if (area_elegivel_ha !== null) {
      if (!creditos_por_ha) return ausente
      for (const q of ["p10", "p50", "p90"] as const) {
        const calculado = creditos_lote[q] / area_elegivel_ha
        if (!Number.isFinite(calculado) || Math.abs(creditos_por_ha[q] - calculado) > 1e-9 * Math.max(1, calculado)) return ausente
      }
    }
    const exclusoes = r.exclusoes === null ? null : Array.isArray(r.exclusoes) && r.exclusoes.length <= 100 ? r.exclusoes.map((v): ExclusaoFichaCredito => {
      const e = registro(v), hectares = opcional(e.hectares, numero), fonte = opcional(e.fonte, origem), data_referencia = opcional(e.data_referencia, referencia)
      if (!["embargo", "terra_indigena", "uc_protecao_integral", "projeto_carbono", "inelegivel_metodo", "outra"].includes(String(e.motivo)) || (hectares !== null && (!fonte || !data_referencia || (area_total_ha !== null && hectares > area_total_ha)))) return falha()
      return { motivo: e.motivo as ExclusaoFichaCredito["motivo"], hectares, fonte, data_referencia }
    }) : falha()
    const secoes = Object.fromEntries(SECOES_FICHA_CREDITO.map(id => {
      const s = registro(registro(r.secoes)[id]), t = opcional(s.texto, texto), fonte = opcional(s.fonte, origem), data_referencia = opcional(s.data_referencia, referencia), revisado_em = opcional(s.revisado_em, referencia)
      if ((t !== null && fonte === null) || (revisado_em !== null && data_referencia !== null && revisado_em < data_referencia)) return falha()
      if (t !== null && !TEXTOS_SECAO_FICHA[id].includes(t)) return falha()
      return [id, { texto: t, fonte, data_referencia, revisado_em }]
    })) as FichaCredito["secoes"]
    const resultados = r.resultados == null ? null : lerResultadosGraficos(r.resultados)
    if (resultados && (resultados.origem === "demonstracao") !== esperado.exemplo) return ausente
    return { contrato: "ficha_credito", versao: 1, estado: "disponivel", documento_versao, publicada_em, revisao_lote: esperado.revisao_lote, opcao_id: esperado.opcao_id, exemplo: esperado.exemplo, aviso: texto(r.aviso), base, creditos_lote, creditos_por_ha, area_total_ha, area_elegivel_ha, fonte_area, data_referencia_area, evidencia_area_id, exclusoes, secoes, resultados }
  } catch { return ausente }
}
