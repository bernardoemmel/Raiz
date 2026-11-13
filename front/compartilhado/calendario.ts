/** Eventos públicos: somente campos do calendário, sem titulares nem texto bruto de editais. */
import { mascarar } from "./privacidade"

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
  car_fonte_url?: string | null
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
    if (!["http:", "https:"].includes(u.protocol) || u.username || u.password) return null
    const decodificado = decodeURIComponent(u.href)
    if (mascarar(decodificado) !== decodificado) return null
    return u.href
  } catch { return null }
}

export function lerAgenda(valor: unknown): Agenda {
  if (!valor || typeof valor !== "object" || !Array.isArray((valor as Record<string, unknown>).eventos)) throw new Error("Calendário indisponível.")
  const v = valor as Record<string, unknown>
  if (v.disponivel === false) return { eventos: [], total: 0, coletado_em: null, fontes: [], disponivel: false }
  const eventos = (v.eventos as Record<string, unknown>[]).flatMap((e): Evento[] => {
    if (!e || typeof e !== "object" || !Object.hasOwn(TIPOS_EVENTO, String(e.tipo)) || !DIA.test(String(e.data)) || !e.id) return []
    const tipo = e.tipo as TipoEvento
    return [{
      id: mascarar(String(e.id)), tipo, titulo: mascarar(String(e.titulo || TIPOS_EVENTO[tipo])), data: String(e.data),
      prazo: DIA.test(String(e.prazo)) ? String(e.prazo) : null,
      uf: typeof e.uf === "string" && /^[A-Z]{2}$/.test(e.uf) ? e.uf : null,
      municipio: typeof e.municipio === "string" && /^\d{7}$/.test(e.municipio) ? e.municipio : null,
      codigos_car: Array.isArray(e.codigos_car) ? e.codigos_car.filter((c): c is string => typeof c === "string" && CAR.test(c)) : [],
      fonte_url: linkPublico(e.fonte_url), fonte_nome: mascarar(String(e.fonte_nome || "Fonte oficial")),
      car_fonte_url: Array.isArray(e.codigos_car) && e.codigos_car.some((c) => typeof c === "string" && CAR.test(c)) ? linkPublico(e.car_fonte_url) : null,
      coletado_em: typeof e.coletado_em === "string" ? e.coletado_em : "",
      confianca: Math.max(0, Math.min(1, Number(e.confianca) || 0)),
      situacao: e.situacao === "cancelado" || e.situacao === "adiado" ? e.situacao : "previsto",
    }]
  })
  const fontes = Array.isArray(v.fontes) ? v.fontes.flatMap((f): FonteEvento[] => !f || typeof f !== "object" ? [] : [{
    id: String(f.id || ""), nome: mascarar(String(f.nome || "Fonte oficial")),
    coletado_em: typeof f.coletado_em === "string" ? f.coletado_em : null, situacao: String(f.situacao || "desconhecida"),
  }]) : []
  return { eventos, total: Math.max(eventos.length, Number(v.total) || 0), coletado_em: typeof v.coletado_em === "string" ? v.coletado_em : null, fontes, disponivel: true }
}

export function filtrarEventos(eventos: Evento[], f: FiltrosEvento): Evento[] {
  return eventos.filter((e) => (!f.tipo || e.tipo === f.tipo) && (!f.estado || !e.uf || e.uf === f.estado) &&
    (!f.inicio || dataEvento(e) >= f.inicio) && (!f.fim || dataEvento(e) <= f.fim) &&
    (!f.cod_imovel || e.codigos_car.some((car) => normalizarCar(car) === normalizarCar(f.cod_imovel!))))
    .sort((a, b) => dataEvento(a).localeCompare(dataEvento(b)) || a.id.localeCompare(b.id))
}
export function codigosEmLeilao(eventos: Evento[], hoje = hojeNoBrasil()): Set<string> {
  return new Set(eventos.filter((e) => e.tipo === "leilao_imovel" && e.situacao === "previsto" && e.data >= hoje).flatMap((e) => e.codigos_car.map(normalizarCar)))
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
