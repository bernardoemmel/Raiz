/**
 * Resumo público do lote nacional por UF, bioma e Brasil (raiz/lotes_publicos.py, docs/lote-nacional.md).
 *
 * Lista positiva: o build e o navegador só repassam contagens e medidas das três opções, a terra em espera separada da
 * pronta e a situação da sobreposição. Nunca fazenda, CAR, caminho de arquivo ou texto livre da origem. Valor ausente é
 * "desconhecido" (null), nunca zero; sobreposição só é "verificada" quando a origem disse isso.
 */

import type { CamposPedido, Faixa, IdOpcao } from "./tipos"

export const IDS_OPCAO: IdOpcao[] = ["barata", "segura", "compacta"]
export type TipoRecorte = "uf" | "bioma" | "brasil"
export type SituacaoSobreposicao = "nao_verificada" | "verificada"

export interface OpcaoNacional {
  fazendas: number | null
  pequenas: number | null
  hectares: number | null
  creditos: Faixa | null
  fecha_meta: boolean | null
  sobreposicao: SituacaoSobreposicao
}

/** Terra que cumpre o pedido em tudo, menos no caminho da terra. Nunca habilita venda. */
export interface EsperaNacional {
  incluida_no_pedido: boolean | null
  fazendas: number | null
  pequenas: number | null
  hectares: number | null
  creditos_p50: number | null
  habilita_venda: false
}

export interface RecorteNacional {
  nome: string
  tipo: TipoRecorte
  opcoes: Record<IdOpcao, OpcaoNacional>
  terra_em_espera: EsperaNacional
  sobreposicao: SituacaoSobreposicao
  vazio: boolean
}

export interface ResumoNacional {
  contrato: "publico_lotes_nacional"
  versao: 1
  estado: "ausente" | "publicado"
  atualizado_em: string | null
  aviso: string
  recortes: RecorteNacional[]
}

const AVISO_PADRAO =
  "Resumo por recorte do lote nacional ainda não publicado. A falta do resumo não significa oferta zero."
const objeto = (v: unknown): Record<string, unknown> => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {})
const numero = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) && v >= 0 ? v : null)
const inteiro = (v: unknown): number | null => (typeof v === "number" && Number.isSafeInteger(v) && v >= 0 ? v : null)
const situacao = (v: unknown): SituacaoSobreposicao => (v === "verificada" ? "verificada" : "nao_verificada")
const data = (v: unknown) => (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v) && Number.isFinite(Date.parse(v)) ? new Date(v).toISOString() : null)

function faixa(v: unknown): Faixa | null {
  const f = objeto(v), p10 = numero(f.p10), p50 = numero(f.p50), p90 = numero(f.p90)
  return p10 === null || p50 === null || p90 === null || !(p10 <= p50 && p50 <= p90) ? null : { p10, p50, p90 }
}

function opcao(v: unknown): OpcaoNacional {
  const o = objeto(v)
  return {
    fazendas: inteiro(o.fazendas), pequenas: inteiro(o.pequenas), hectares: numero(o.hectares), creditos: faixa(o.creditos),
    fecha_meta: typeof o.fecha_meta === "boolean" ? o.fecha_meta : null, sobreposicao: situacao(o.sobreposicao),
  }
}

function espera(v: unknown): EsperaNacional {
  const e = objeto(v)
  return {
    incluida_no_pedido: typeof e.incluida_no_pedido === "boolean" ? e.incluida_no_pedido : null,
    fazendas: inteiro(e.fazendas), pequenas: inteiro(e.pequenas), hectares: numero(e.hectares), creditos_p50: numero(e.creditos_p50),
    habilita_venda: false,
  }
}

export function ausenteNacional(): ResumoNacional {
  return { contrato: "publico_lotes_nacional", versao: 1, estado: "ausente", atualizado_em: null, aviso: AVISO_PADRAO, recortes: [] }
}

/** Nunca lança: arquivo ausente, quebrado ou de outro contrato vira "ausente" (desconhecido, não zero). */
export function projetarResumoNacional(valor: unknown): ResumoNacional {
  const v = objeto(valor)
  if (v.contrato !== "publico_lotes_nacional" || v.versao !== 1 || v.estado !== "publicado" || !Array.isArray(v.recortes)) return ausenteNacional()
  const vistos = new Set<string>(), recortes: RecorteNacional[] = []
  for (const item of v.recortes) {
    const r = objeto(item), ops = objeto(r.opcoes)
    if (typeof r.nome !== "string" || !["uf", "bioma", "brasil"].includes(String(r.tipo)) || vistos.has(r.nome)) continue
    if (!IDS_OPCAO.every((id) => id in ops)) continue
    vistos.add(r.nome)
    const opcoes = Object.fromEntries(IDS_OPCAO.map((id) => [id, opcao(ops[id])])) as Record<IdOpcao, OpcaoNacional>
    recortes.push({
      nome: r.nome, tipo: r.tipo as TipoRecorte, opcoes, terra_em_espera: espera(r.terra_em_espera), sobreposicao: situacao(r.sobreposicao),
      vazio: IDS_OPCAO.every((id) => !(opcoes[id].fazendas ?? 0)),
    })
  }
  return { contrato: "publico_lotes_nacional", versao: 1, estado: recortes.length ? "publicado" : "ausente", atualizado_em: data(v.atualizado_em),
    aviso: typeof v.aviso === "string" && v.aviso.length <= 1000 ? v.aviso : AVISO_PADRAO, recortes }
}

/**
 * O recorte que responde ao pedido: um estado, um bioma ou o Brasil inteiro (sem estado nem bioma escolhido).
 * Município, vários estados ou vários biomas não têm resumo próprio: devolve null e a tela diz isso.
 */
export function recorteDoPedido(resumo: ResumoNacional | null | undefined, onde: CamposPedido["onde"]): RecorteNacional | null {
  if (!resumo?.recortes.length || onde.municipios.length || onde.poligono?.length || onde.raio) return null
  const ufs = onde.ufs ?? [], biomas = onde.biomas ?? []
  const nome = ufs.length === 1 && !biomas.length ? ufs[0] : biomas.length === 1 && !ufs.length ? biomas[0] : !ufs.length && !biomas.length ? "Brasil" : null
  return nome ? resumo.recortes.find((r) => r.nome === nome) ?? null : null
}
