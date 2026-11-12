/** Contrato da sensibilidade: resultados do motor ou exemplo fictício, nunca inferidos do resumo público. */
import type { Faixa, IdOpcao } from "./tipos"

export interface ParametrosSensibilidade {
  preco_credito_usd: number
  reserva_reversao: number
  taxa_desconto: number
  pessimista: boolean
}
export const PARAMETROS_SENSIBILIDADE: ParametrosSensibilidade = {
  preco_credito_usd: 55, reserva_reversao: 0.2, taxa_desconto: 0.092, pessimista: false,
}
export interface OpcaoSensibilidade {
  id: IdOpcao
  creditos: Faixa
  hectares: number
  fazendas: number
  vpl_usd: number | null
  tir_projeto: number | null
  alcanca_meta: boolean
}
export interface ResultadoSensibilidade {
  estado: "disponivel" | "indisponivel"
  exemplo: boolean
  parametros: ParametrosSensibilidade
  fonte: string
  atualizado_em: string | null
  modelo_versao: string | null
  aviso: string
  opcoes: OpcaoSensibilidade[]
}
export type ConsultarSensibilidade = (parametros: ParametrosSensibilidade) => Promise<ResultadoSensibilidade>

export function conferirParametrosSensibilidade(p: ParametrosSensibilidade): void {
  if (!Number.isFinite(p.preco_credito_usd) || p.preco_credito_usd <= 0 || p.preco_credito_usd > 1000)
    throw new Error("Informe um preço maior que zero e até US$ 1.000.")
  if (!Number.isFinite(p.reserva_reversao) || p.reserva_reversao < 0.2 || p.reserva_reversao > 0.9)
    throw new Error("A reserva contra reversão deve ficar entre 20% e 90%.")
  if (!Number.isFinite(p.taxa_desconto) || p.taxa_desconto < 0 || p.taxa_desconto > 0.5)
    throw new Error("A taxa de desconto deve ficar entre 0% e 50% ao ano.")
  if (typeof p.pessimista !== "boolean") throw new Error("Escolha se deseja o cenário pessimista.")
}

export function sensibilidadeIndisponivel(parametros: ParametrosSensibilidade): ResultadoSensibilidade {
  return {
    estado: "indisponivel", exemplo: false, parametros, fonte: "Lote e números, Release privado",
    atualizado_em: null, modelo_versao: null, opcoes: [],
    aviso: "A grade de sensibilidade dos três lotes ainda não está disponível. O cenário central do Pará não foi recalculado. São necessárias saídas do motor para estas premissas.",
  }
}

/** A sessão é fornecida pelo adaptador autenticado. Sem servidor não há tentativa de buscar rota no Pages. */
export function consultarSensibilidadeApi(api: string | undefined, pedido: string, token: () => string | null): ConsultarSensibilidade {
  return async (parametros) => {
    conferirParametrosSensibilidade(parametros)
    if (!api) return sensibilidadeIndisponivel(parametros)
    const credencial = token()
    if (!credencial) throw new Error("Entre na área logada para consultar a sensibilidade do lote.")
    const resposta = await fetch(`${api.replace(/\/$/, "")}/pedidos/${encodeURIComponent(pedido)}/sensibilidade`, {
      method: "POST", cache: "no-store", headers: { "Content-Type": "application/json", Authorization: `Bearer ${credencial}` },
      body: JSON.stringify(parametros),
    })
    if (resposta.status === 401 || resposta.status === 403) throw new Error("Sua conta não tem acesso a esta sensibilidade. Entre de novo e confira a liberação do pedido.")
    if (!resposta.ok) throw new Error("Não foi possível consultar a sensibilidade. Tente novamente.")
    return conferirResultadoSensibilidade(await resposta.json(), parametros)
  }
}

/** Recusa resposta incompleta ou de premissas diferentes; não deixa números antigos parecerem recalculados. */
export function conferirResultadoSensibilidade(valor: unknown, parametros: ParametrosSensibilidade): ResultadoSensibilidade {
  const r = valor as ResultadoSensibilidade
  const numero = (v: unknown) => typeof v === "number" && Number.isFinite(v)
  const naoNegativo = (v: unknown) => numero(v) && (v as number) >= 0
  if (!r || !["disponivel", "indisponivel"].includes(r.estado) || typeof r.exemplo !== "boolean" || !r.parametros
      || Object.keys(PARAMETROS_SENSIBILIDADE).some((k) => r.parametros[k as keyof ParametrosSensibilidade] !== parametros[k as keyof ParametrosSensibilidade])
      || typeof r.fonte !== "string" || !r.fonte.trim() || typeof r.aviso !== "string" || !Array.isArray(r.opcoes)
      || (r.atualizado_em !== null && (typeof r.atualizado_em !== "string" || !Number.isFinite(Date.parse(r.atualizado_em))))
      || (r.modelo_versao !== null && (typeof r.modelo_versao !== "string" || !r.modelo_versao.trim())))
    throw new Error("A resposta de sensibilidade não corresponde às premissas enviadas.")
  if (r.estado === "indisponivel" && r.opcoes.length) throw new Error("A sensibilidade indisponível não pode apresentar resultados.")
  if (r.estado === "disponivel" && (r.opcoes.length !== 3 || new Set(r.opcoes.map((o) => o.id)).size !== 3
      || !r.atualizado_em || !Number.isFinite(Date.parse(r.atualizado_em)) || !r.modelo_versao
      || r.opcoes.some((o) => !["barata", "segura", "compacta"].includes(o.id) || !o.creditos
        || ![o.creditos.p10, o.creditos.p50, o.creditos.p90, o.hectares, o.fazendas].every(naoNegativo)
        || o.creditos.p10 > o.creditos.p50 || o.creditos.p50 > o.creditos.p90 || !Number.isInteger(o.fazendas)
        || (o.vpl_usd !== null && !numero(o.vpl_usd)) || (o.tir_projeto !== null && (!numero(o.tir_projeto) || o.tir_projeto <= -1)) || typeof o.alcanca_meta !== "boolean")))
    throw new Error("A resposta de sensibilidade está incompleta. Aguarde os três lotes do motor.")
  // Projeção positiva: mesmo que a API acrescente campos, a sensibilidade não transporta detalhes por fazenda.
  return { estado: r.estado, exemplo: r.exemplo, parametros: { ...parametros }, fonte: r.fonte,
    atualizado_em: r.atualizado_em, modelo_versao: r.modelo_versao, aviso: r.aviso,
    opcoes: r.opcoes.map((o) => ({ id: o.id, creditos: { p10: o.creditos.p10, p50: o.creditos.p50, p90: o.creditos.p90 },
      hectares: o.hectares, fazendas: o.fazendas, vpl_usd: o.vpl_usd, tir_projeto: o.tir_projeto, alcanca_meta: o.alcanca_meta })) }
}
