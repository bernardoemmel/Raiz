import { UFS } from "../formato.ts"

export type SituacaoProcessamento = "atual" | "desatualizado" | "sem_telemetria"
export interface ProcessamentoEstado {
  uf: string
  escopo: "uf" | "unidade" | "indisponivel"
  unidade: string | null
  municipios_total: number | null
  municipios: {
    prontos: number | null
    em_execucao: number | null
    com_erro: number | null
    pendentes: number | null
    desconhecidos: number | null
  }
  observado_em: string | null
  ultima_mudanca_em: string | null
  valido_ate: string | null
  situacao: SituacaoProcessamento
}

export interface ProcessamentoEstados {
  versao: 1
  gerado_em: string
  estados: ProcessamentoEstado[]
}

function objeto(valor: unknown): Record<string, unknown> {
  if (!valor || typeof valor !== "object" || Array.isArray(valor)) throw new Error("Resposta de processamento inválida")
  return valor as Record<string, unknown>
}

/** Datas de telemetria precisam identificar o fuso; nunca interpretar no fuso do aparelho. */
function data(valor: unknown): string | null {
  return typeof valor === "string" && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(valor) && Number.isFinite(Date.parse(valor)) ? valor : null
}

function contagem(valor: unknown): number | null {
  return typeof valor === "number" && Number.isSafeInteger(valor) && valor >= 0 && valor <= 6000 ? valor : null
}

/** Projeta apenas os agregados públicos. Zero é informação; ausência nunca vira zero. */
export function lerProcessamentoEstados(valor: unknown): ProcessamentoEstados {
  const raiz = objeto(valor)
  const gerado = data(raiz.gerado_em)
  if (raiz.versao !== 1 || !gerado || !Array.isArray(raiz.estados)) throw new Error("Resposta de processamento inválida")
  const vistos = new Set<string>()
  const estados = raiz.estados.map((item): ProcessamentoEstado => {
    const e = objeto(item)
    if (typeof e.uf !== "string" || !Object.hasOwn(UFS, e.uf) || vistos.has(e.uf)) throw new Error("Estado de processamento inválido")
    vistos.add(e.uf)
    if (e.escopo !== "uf" && e.escopo !== "unidade" && e.escopo !== "indisponivel") throw new Error("Escopo de processamento inválido")
    if (e.situacao !== "atual" && e.situacao !== "desatualizado" && e.situacao !== "sem_telemetria") throw new Error("Situação de processamento inválida")
    const n = objeto(e.municipios)
    const unidade = typeof e.unidade === "string" && new RegExp(`^${e.uf}(?:-[1-9][0-9]{0,3})?$`).test(e.unidade)
      && (e.escopo !== "uf" || e.unidade === e.uf) ? e.unidade : null
    const estado: ProcessamentoEstado = {
      uf: e.uf,
      escopo: e.escopo,
      unidade,
      municipios_total: contagem(e.municipios_total),
      municipios: {
        prontos: contagem(n.prontos), em_execucao: contagem(n.em_execucao), com_erro: contagem(n.com_erro),
        pendentes: contagem(n.pendentes), desconhecidos: contagem(n.desconhecidos),
      },
      observado_em: data(e.observado_em), ultima_mudanca_em: data(e.ultima_mudanca_em), valido_ate: data(e.valido_ate),
      situacao: e.situacao,
    }
    const valores = Object.values(estado.municipios)
    if (estado.situacao === "atual" && valores.every((v) => v !== null)
      && (estado.municipios_total === null || valores.reduce((s, v) => s + v, 0) !== estado.municipios_total)) throw new Error("Contagens de municípios divergentes")
    const observado = estado.observado_em ? Date.parse(estado.observado_em) : NaN
    const validade = estado.valido_ate ? Date.parse(estado.valido_ate) : NaN
    const mudanca = estado.ultima_mudanca_em ? Date.parse(estado.ultima_mudanca_em) : NaN
    if (mudanca > observado || validade <= observado || validade - observado > 3_600_000) throw new Error("Prazo da observação inválido")
    return estado
  })
  if (vistos.size !== Object.keys(UFS).length) throw new Error("Cobertura de estados incompleta")
  return { versao: 1, gerado_em: gerado, estados }
}

/** O relógio da publicação não renova a validade da observação de cada estado. */
export function situacaoProcessamento(estado: ProcessamentoEstado, agora = Date.now()): SituacaoProcessamento {
  if (estado.escopo === "indisponivel" || estado.situacao === "sem_telemetria" || !estado.observado_em) return "sem_telemetria"
  const observado = Date.parse(estado.observado_em)
  const validade = estado.valido_ate ? Date.parse(estado.valido_ate) : NaN
  if (estado.situacao === "desatualizado" || !Number.isFinite(observado) || !Number.isFinite(validade) || validade <= agora || observado > agora || validade < observado) return "desatualizado"
  return "atual"
}

export function urlProcessamento(env: { VITE_RAIZ_PROCESSAMENTO_URL?: string; VITE_RAIZ_API?: string; BASE_URL?: string }): string {
  if (env.VITE_RAIZ_PROCESSAMENTO_URL?.trim()) return env.VITE_RAIZ_PROCESSAMENTO_URL.trim()
  if (env.VITE_RAIZ_API?.trim()) return `${env.VITE_RAIZ_API.trim().replace(/\/+$/, "")}/processamento/publico`
  return "https://raw.githubusercontent.com/bernardoemmel/Raiz/status-processamento/processamento.json"
}

export async function buscarProcessamento(url: string, signal: AbortSignal): Promise<ProcessamentoEstados> {
  const [base, fragmento] = url.split("#", 2)
  const atual = `${base}${base.includes("?") ? "&" : "?"}_raiz_t=${Math.floor(Date.now() / 30_000)}${fragmento ? `#${fragmento}` : ""}`
  const resposta = await fetch(atual, { signal, credentials: "omit", cache: "no-store" })
  if (!resposta.ok || (resposta.headers.get("content-type") ?? "").includes("text/html")) throw new Error("Processamento indisponível")
  return lerProcessamentoEstados(await resposta.json())
}
