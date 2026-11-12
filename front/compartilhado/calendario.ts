/** Eventos públicos: somente campos do calendário, sem titulares nem texto bruto de editais. */
import { mascarar } from "./privacidade"
import FONTES_OFICIAIS from "./calendario-fontes.json"

export const TIPOS_EVENTO = {
  leilao_imovel: "Leilão de imóvel rural",
  penhora: "Penhora",
  edital_bndes: "Edital do BNDES",
  profloresta: "ProFloresta+",
  fundo_amazonia: "Fundo Amazônia",
  concessao: "Concessão",
  leilao_credito: "Leilão de créditos",
  sbce: "SBCE",
  verra: "Verra",
  icvcm: "ICVCM",
  sbti: "SBTi",
  eudr: "EUDR",
} as const
export type TipoEvento = keyof typeof TIPOS_EVENTO
export interface Evento {
  id: string
  tipo: TipoEvento
  titulo: string
  data: string
  prazo: string | null
  uf: string | null
  municipio: string | null
  codigos_car: string[]
  fonte_url: string | null
  fonte_nome: string
  coletado_em: string
  confianca: number
  situacao: "previsto" | "cancelado" | "adiado"
}
export interface FonteEvento { id: string; nome: string; coletado_em: string | null; situacao: string }
export interface Agenda { eventos: Evento[]; total: number; coletado_em: string | null; fontes: FonteEvento[]; disponivel: boolean }
export interface FiltrosEvento { tipo?: string; estado?: string; inicio?: string; fim?: string; cod_imovel?: string }
const DIA = /^\d{4}-\d{2}-\d{2}$/
const CAR = /^[A-Z]{2}-\d{7}-[A-F0-9]{32}$/
const ID_EVENTO = /^[a-f0-9]{24}$/
const MARCOS: Record<string, string> = { evento: "data do evento", propostas: "entrega de propostas", inscricoes: "inscrições", consulta: "fim da consulta", vigencia: "início da aplicação", penhora: "registro da penhora" }
const ESTADOS_FONTE = new Set(["ok", "parcial", "erro", "sem_data"])
const instante = (v: unknown): string | null => typeof v === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v)) ? v : null
function tituloEvento(tipo: TipoEvento, marco: unknown, referencia: unknown): string {
  const rotulo = Object.hasOwn(MARCOS, String(marco)) ? MARCOS[String(marco)] : MARCOS.evento
  const ref = typeof referencia === "string" && /^\d{1,5}(?:[/.\-]\d{1,4}){0,3}$/.test(referencia) ? `, edital ${referencia}` : ""
  return `${TIPOS_EVENTO[tipo]}: ${rotulo}${ref}`
}

export function hojeNoBrasil(agora = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo", year: "numeric", month: "2-digit", day: "2-digit" }).format(agora)
}
export function normalizarCar(car: string): string { return car.toUpperCase().replace(/[^A-Z0-9]/g, "") }
export function dataEvento(e: Evento): string { return e.prazo ?? e.data }
export function formatarDia(dia: string): string { return DIA.test(dia) ? dia.split("-").reverse().join("/") : "Sem data" }

/** Links recebidos de fontes nunca podem executar código nem transportar identificadores pessoais. */
export function linkPublico(valor: unknown): string | null {
  if (typeof valor !== "string") return null
  try {
    const u = new URL(valor)
    if (!["http:", "https:"].includes(u.protocol) || u.username || u.password || !FONTES_OFICIAIS.some((f) => f.hosts.includes(u.hostname))) return null
    let decodificado = u.href
    for (let n = 0; n < 3; n++) {
      const proximo = decodeURIComponent(decodificado)
      if (proximo === decodificado) break
      decodificado = proximo
    }
    const pessoal = /(?:cpf|cnpj|nome|proprietario|dono|contato|telefone|celular|whatsapp|email|senha|password|token|secret|chave)/i
    if ([...u.searchParams.keys()].some((k) => pessoal.test(k)) || mascarar(decodificado) !== decodificado || /[\w.+-]+@[\w.-]+\.[a-z]{2,}/i.test(decodificado) || /(?:\+55[\s.-]*)?\(\d{2}\)[\s.-]*9?\d{4}[- ]\d{4}/.test(decodificado)) return null
    u.hash = ""
    return u.href
  } catch { return null }
}

export function lerAgenda(valor: unknown): Agenda {
  if (!valor || typeof valor !== "object" || !Array.isArray((valor as Record<string, unknown>).eventos)) throw new Error("Calendário indisponível.")
  const v = valor as Record<string, unknown>
  if (v.disponivel === false) return { eventos: [], total: 0, coletado_em: null, fontes: [], disponivel: false }
  const eventos = (v.eventos as Record<string, unknown>[]).flatMap((e): Evento[] => {
    if (!e || typeof e !== "object" || !Object.hasOwn(TIPOS_EVENTO, String(e.tipo)) || !DIA.test(String(e.data)) || !ID_EVENTO.test(String(e.id))) return []
    const tipo = e.tipo as TipoEvento
    const link = linkPublico(e.fonte_url)
    const fonte = FONTES_OFICIAIS.find((f) => f.id === e.fonte_id) ?? FONTES_OFICIAIS.find((f) => link && f.hosts.includes(new URL(link).hostname))
    return [{
      id: String(e.id), tipo, titulo: tituloEvento(tipo, e.marco, e.referencia), data: String(e.data),
      prazo: DIA.test(String(e.prazo)) ? String(e.prazo) : null,
      uf: typeof e.uf === "string" && /^[A-Z]{2}$/.test(e.uf) ? e.uf : null,
      municipio: typeof e.municipio === "string" && /^\d{7}$/.test(e.municipio) ? e.municipio : null,
      codigos_car: Array.isArray(e.codigos_car) ? e.codigos_car.filter((c): c is string => typeof c === "string" && CAR.test(c)) : [],
      fonte_url: link, fonte_nome: fonte?.nome ?? "Fonte oficial",
      coletado_em: instante(e.coletado_em) ?? "",
      confianca: Math.max(0, Math.min(1, Number(e.confianca) || 0)),
      situacao: e.situacao === "cancelado" || e.situacao === "adiado" ? e.situacao : "previsto",
    }]
  })
  const fontes = Array.isArray(v.fontes) ? v.fontes.flatMap((f): FonteEvento[] => {
    if (!f || typeof f !== "object") return []
    const fonte = FONTES_OFICIAIS.find((oficial) => oficial.id === f.id)
    if (!fonte) return []
    return [{ id: fonte.id, nome: fonte.nome, coletado_em: instante(f.coletado_em), situacao: ESTADOS_FONTE.has(f.situacao) ? f.situacao : "desconhecida" }]
  }) : []
  return { eventos, total: Math.max(eventos.length, Number(v.total) || 0), coletado_em: instante(v.coletado_em), fontes, disponivel: true }
}

export function filtrarEventos(eventos: Evento[], f: FiltrosEvento): Evento[] {
  return eventos.filter((e) => (!f.tipo || e.tipo === f.tipo) && (!f.estado || !e.uf || e.uf === f.estado) &&
    (!f.inicio || dataEvento(e) >= f.inicio) && (!f.fim || dataEvento(e) <= f.fim) &&
    (!f.cod_imovel || e.codigos_car.some((car) => normalizarCar(car) === normalizarCar(f.cod_imovel!))))
    .sort((a, b) => dataEvento(a).localeCompare(dataEvento(b)) || a.id.localeCompare(b.id))
}
export function codigosEmLeilao(eventos: Evento[], hoje = hojeNoBrasil()): Set<string> {
  return new Set(eventos.filter((e) => e.tipo === "leilao_imovel" && e.situacao === "previsto" && dataEvento(e) >= hoje).flatMap((e) => e.codigos_car.map(normalizarCar)))
}

const VAZIA: Agenda = { eventos: [], total: 0, coletado_em: null, fontes: [], disponivel: false }
export function fonteCalendario(opcoes: { api?: string; token?: string; json?: string; ics?: string; base?: string }, buscar: typeof fetch = fetch) {
  const api = opcoes.api?.replace(/\/$/, "")
  const json = opcoes.json || `${opcoes.base || "/"}calendario/eventos.json`
  const cabecalhos: HeadersInit = api && opcoes.token ? { Authorization: `Bearer ${opcoes.token}` } : {}
  let copia: { quando: number; agenda: Promise<Agenda> } | null = null
  const parametros = (f: FiltrosEvento) => new URLSearchParams(Object.entries(f).filter(([, v]) => !!v) as [string, string][])
  async function ler(url: string): Promise<Agenda> {
    const r = await buscar(url, { headers: cabecalhos })
    if (r.status === 404 || (!api && r.ok && !r.headers.get("content-type")?.includes("json"))) return VAZIA
    if (!r.ok) throw new Error("Não foi possível consultar o calendário.")
    return lerAgenda(await r.json())
  }
  return {
    api: !!api,
    feed(f: FiltrosEvento = {}) { return api ? `${api}/eventos.ics?${parametros(f)}` : opcoes.ics || json.replace(/\.json(?:\?.*)?$/, ".ics") },
    async listar(f: FiltrosEvento = {}, deslocamento = 0, limite = 50): Promise<Agenda> {
      if (api) {
        const q = parametros(f)
        q.set("deslocamento", String(deslocamento)); q.set("limite", String(limite))
        return ler(`${api}/eventos?${q}`)
      }
      if (!copia || Date.now() - copia.quando > 60000) copia = { quando: Date.now(), agenda: ler(json) }
      const a = await copia.agenda.catch((e) => { copia = null; throw e })
      const eventos = filtrarEventos(a.eventos, f)
      return { ...a, eventos: eventos.slice(deslocamento, deslocamento + limite), total: eventos.length }
    },
    async leiloes(f: FiltrosEvento = {}): Promise<Agenda> {
      // Percorre as páginas: um imóvel não some do mapa porque seu leilão ficou depois do centésimo evento.
      const filtro = { ...f, tipo: "leilao_imovel" }
      let a = await this.listar(filtro, 0, 100)
      const eventos = [...a.eventos]
      while (eventos.length < a.total) {
        const pagina = await this.listar(filtro, eventos.length, 100)
        if (!pagina.eventos.length) break
        eventos.push(...pagina.eventos)
        a = pagina
      }
      return { ...a, eventos }
    },
  }
}
