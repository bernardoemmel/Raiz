/** Somente na resposta autenticada da ficha do lote. Não publicar no Release aberto. */
export interface ReferenciaResultado {
  classe: "credito_carbono" | "flag"
  metrica: string
  unidade: "tCO2e" | "tCO2e/ha" | "tCO2e/ha/ano" | "tCO2e/ano"
  escala: "por_hectare" | "lote"
  area_base_ha: number
  /** Denominador original documentado, preservado mesmo quando a escala é por hectare. */
  area_elegivel_carteira_ha: number
  escopo_carteira: "titulares" | "titulares_e_reservas"
  inicio: string
  fim: string
  horizonte_dias: number
}
export const FONTES_RESULTADOS = ["Registro de contratos da Raíz", "Registro de emissão de créditos", "Comprovante de entrega de créditos", "Banco de aprendizado da Raíz", "Observação de campo registrada", "Registro Verra", "Registro Gold Standard", "Relatório de monitoramento verificado", "Demonstração sintética"] as const
export interface FonteResultado {
  nome: typeof FONTES_RESULTADOS[number]
  registro_id: string
  data: string
}
export interface MedidaConfirmada {
  natureza: "contrato_assinado" | "emissao_registrada" | "entrega_comprovada"
  valor: number
  fonte: FonteResultado
}
/** Uma etapa documental não pode ser sustentada somente pelo banco de previsões. */
export const FONTES_POR_NATUREZA = {
  contrato_assinado: ["Registro de contratos da Raíz"],
  emissao_registrada: ["Registro de emissão de créditos", "Registro Verra", "Registro Gold Standard"],
  entrega_comprovada: ["Comprovante de entrega de créditos"],
} as const
export interface SerieContrato {
  id: string
  metodo: string
  referencia: ReferenciaResultado
  regime: "acumulado"
  marcos: {
    data: string
    /** Somente contrato assinado, emissão registrada e entrega comprovada. Nunca estimativas. */
    contratado: MedidaConfirmada | null
    emitido: MedidaConfirmada | null
    entregue: MedidaConfirmada | null
  }[]
}
export interface ComparacaoMetodo {
  id: string
  metodo: string
  modelo: string
  versao: string
  avaliacao: "ao_vivo" | "backtest"
  previsao: {
    referencia: ReferenciaResultado
    corte: string
    congelada_em: string
    p10: number
    p50: number
    p90: number
    fonte: FonteResultado
  }
  observado: {
    referencia: ReferenciaResultado
    data: string
    registrado_em: string
    valor: number
    fonte: FonteResultado
  }
}
export interface ResultadosGraficos {
  schema: "raiz.resultados.graficos.v1"
  origem: "real" | "demonstracao"
  gerado_em: string
  contratos: SerieContrato[]
  comparacoes: ComparacaoMetodo[]
}
const registro = (v: unknown): Record<string, unknown> => v && typeof v === "object" && !Array.isArray(v) ? v as Record<string, unknown> : {}
const falha = (): never => { throw new Error("Os resultados não comprovam fonte, período e evidência compatíveis.") }
const id = (v: unknown): string => typeof v === "string" && /^[a-zA-Z0-9][a-zA-Z0-9_.:+/-]{0,119}$/.test(v) ? v : falha()
const numero = (v: unknown): number => typeof v === "number" && Number.isFinite(v) && v >= 0 ? v : falha()
const dia = (v: unknown): string => typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0, 10) === v ? v : falha()
const instante = (v: unknown): string => typeof v === "string" && /^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v)) ? v : falha()
/** As datas civis do contrato usam UTC, independentemente do fuso escrito no instante. */
const diaUtc = (instante: string): string => new Date(instante).toISOString().slice(0, 10)
const lista = (v: unknown): unknown[] => Array.isArray(v) && v.length <= 100 ? v : falha()
function referencia(v: unknown): ReferenciaResultado {
  const r = registro(v), inicio = dia(r.inicio), fim = dia(r.fim), horizonte_dias = numero(r.horizonte_dias), area_base_ha = numero(r.area_base_ha), area_elegivel_carteira_ha = numero(r.area_elegivel_carteira_ha)
  if ((r.classe !== "credito_carbono" && r.classe !== "flag") || !["tCO2e", "tCO2e/ha", "tCO2e/ha/ano", "tCO2e/ano"].includes(String(r.unidade)) || (r.escala !== "por_hectare" && r.escala !== "lote") || area_base_ha <= 0 || horizonte_dias <= 0 || Date.parse(fim) - Date.parse(inicio) !== horizonte_dias * 86400000) return falha()
  if (!["titulares", "titulares_e_reservas"].includes(String(r.escopo_carteira)) || area_elegivel_carteira_ha <= 0 || (r.escala === "lote" && area_base_ha !== area_elegivel_carteira_ha)) return falha()
  if ((r.escala === "por_hectare") !== String(r.unidade).includes("/ha") || (r.escala === "por_hectare" && area_base_ha !== 1)) return falha()
  return { classe: r.classe, metrica: id(r.metrica), unidade: r.unidade as ReferenciaResultado["unidade"], escala: r.escala, area_base_ha, area_elegivel_carteira_ha, escopo_carteira: r.escopo_carteira as ReferenciaResultado["escopo_carteira"], inicio, fim, horizonte_dias }
}
/** Esta chave também impede que a interface reúna classes, bases e períodos diferentes no mesmo eixo. */
export function chaveReferencia(r: ReferenciaResultado): string {
  return JSON.stringify([r.classe, r.metrica, r.unidade, r.escala, r.area_base_ha, r.area_elegivel_carteira_ha, r.escopo_carteira, r.inicio, r.fim, r.horizonte_dias])
}
function fonte(v: unknown, limite: string): FonteResultado {
  const f = registro(v), data = dia(f.data)
  if (typeof f.nome !== "string" || !(FONTES_RESULTADOS as readonly string[]).includes(f.nome) || data > diaUtc(limite)) return falha()
  return { nome: f.nome as FonteResultado["nome"], registro_id: id(f.registro_id), data }
}
function medida(v: unknown, limite: string, natureza: MedidaConfirmada["natureza"]): MedidaConfirmada | null {
  if (v === null) return null
  const m = registro(v)
  if (m.natureza !== natureza) return falha()
  const origem = fonte(m.fonte, limite)
  if (origem.nome !== "Demonstração sintética" && !(FONTES_POR_NATUREZA[natureza] as readonly string[]).includes(origem.nome)) return falha()
  return { natureza, valor: numero(m.valor), fonte: origem }
}
/** Lista positiva: não aceita especificações de gráfico, URLs, CAR ou dados de dono vindos do servidor. */
export function lerResultadosGraficos(v: unknown): ResultadosGraficos {
  const r = registro(v), gerado_em = instante(r.gerado_em)
  if (r.schema !== "raiz.resultados.graficos.v1" || (r.origem !== "real" && r.origem !== "demonstracao")) return falha()
  const contratos = lista(r.contratos).map((valor): SerieContrato => {
    const s = registro(valor)
    if (s.regime !== "acumulado") return falha()
    const marcos = lista(s.marcos).map((valor) => {
      const m = registro(valor), data = dia(m.data)
      if (data > diaUtc(gerado_em)) return falha()
      return { data, contratado: medida(m.contratado, gerado_em, "contrato_assinado"), emitido: medida(m.emitido, gerado_em, "emissao_registrada"), entregue: medida(m.entregue, gerado_em, "entrega_comprovada") }
    })
    if (marcos.some((m, i) => i > 0 && m.data <= marcos[i - 1].data)) return falha()
    return { id: id(s.id), metodo: id(s.metodo), referencia: referencia(s.referencia), regime: "acumulado", marcos }
  })
  const comparacoes = lista(r.comparacoes).map((valor): ComparacaoMetodo => {
    const c = registro(valor), p = registro(c.previsao), o = registro(c.observado)
    if (c.avaliacao !== "ao_vivo" && c.avaliacao !== "backtest") return falha()
    const previa = referencia(p.referencia), real = referencia(o.referencia)
    const corte = dia(p.corte), data = dia(o.data), congelada_em = instante(p.congelada_em), registrado_em = instante(o.registrado_em)
    const p10 = numero(p.p10), p50 = numero(p.p50), p90 = numero(p.p90)
    if (chaveReferencia(previa) !== chaveReferencia(real) || p10 > p50 || p50 > p90 || corte !== previa.inicio || data !== previa.fim || data > diaUtc(gerado_em) || diaUtc(congelada_em) < corte || diaUtc(registrado_em) < data || Date.parse(congelada_em) > Date.parse(gerado_em) || Date.parse(registrado_em) > Date.parse(gerado_em)) return falha()
    if (c.avaliacao === "ao_vivo" && (diaUtc(congelada_em) >= data || Date.parse(congelada_em) > Date.parse(registrado_em))) return falha()
    return { id: id(c.id), metodo: id(c.metodo), modelo: id(c.modelo), versao: id(c.versao), avaliacao: c.avaliacao, previsao: { referencia: previa, corte, congelada_em, p10, p50, p90, fonte: fonte(p.fonte, gerado_em) }, observado: { referencia: real, data, registrado_em, valor: numero(o.valor), fonte: fonte(o.fonte, gerado_em) } }
  })
  const fontes = [...contratos.flatMap((s) => s.marcos.flatMap((m) => [m.contratado, m.emitido, m.entregue].flatMap((n) => n ? [n.fonte] : []))), ...comparacoes.flatMap((c) => [c.previsao.fonte, c.observado.fonte])]
  if (fontes.some((f) => (f.nome === "Demonstração sintética") !== (r.origem === "demonstracao"))) return falha()
  for (const itens of [contratos, comparacoes]) if (new Set(itens.map((i) => i.id)).size !== itens.length) return falha()
  return { schema: "raiz.resultados.graficos.v1", origem: r.origem, gerado_em, contratos, comparacoes }
}
