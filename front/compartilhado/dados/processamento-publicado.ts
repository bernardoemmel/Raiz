import type { ProcessamentoEstado } from "./processamento-estados.ts"

const UFS = new Set("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split(" "))
const CAMPOS = ["versao", "escopo", "unidade", "municipios_total", "municipios", "observado_em", "ultima_mudanca_em", "valido_ate"]
const CONTAGENS = ["prontos", "em_execucao", "com_erro", "pendentes", "desconhecidos"] as const
const HORA = 60 * 60 * 1000

function objeto(valor: unknown): valor is Record<string, unknown> {
  return valor !== null && typeof valor === "object" && !Array.isArray(valor)
}

function chaves(valor: unknown, campos: readonly string[]): valor is Record<string, unknown> {
  return objeto(valor) && Object.keys(valor).length === campos.length && campos.every((campo) => Object.hasOwn(valor, campo))
}

function inteiro(valor: unknown): valor is number {
  return typeof valor === "number" && Number.isSafeInteger(valor) && valor >= 0 && valor <= 6000
}

/** Confere calendário e fuso sem normalizar nem renovar a observação publicada. */
function instante(valor: unknown): number | null {
  if (typeof valor !== "string") return null
  const m = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d{1,9})?(Z|([+-])(\d{2}):(\d{2}))$/.exec(valor)
  if (!m) return null
  const ms = Date.parse(valor)
  if (!Number.isFinite(ms)) return null
  const horas = Number(m[4] || 0), minutos = Number(m[5] || 0)
  if (horas > 23 || minutos > 59) return null
  const fuso = (horas * 60 + minutos) * (m[3] === "-" ? -1 : 1)
  return new Date(ms + fuso * 60_000).toISOString().slice(0, 19) === m[1] ? ms : null
}

/**
 * Origem pública estrita: um bloco malformado inteiro é indisponível. Extras,
 * CARs e mensagens livres não são descartados silenciosamente pelo downloader.
 * O DTO retorna só campos nomeados; seu consumidor decide o frescor pelo relógio.
 */
export function lerProcessamentoPublicado(valor: unknown, uf: string): ProcessamentoEstado | null {
  if (!UFS.has(uf) || !chaves(valor, CAMPOS) || valor.versao !== 1) return null
  if (valor.escopo !== "uf" && valor.escopo !== "unidade") return null
  if (typeof valor.unidade !== "string" ||
      (valor.escopo === "uf" ? valor.unidade !== uf : !new RegExp(`^${uf}(?:-[1-9][0-9]?)?$`).test(valor.unidade))) return null
  if (!inteiro(valor.municipios_total) || !chaves(valor.municipios, CONTAGENS)) return null
  const n = valor.municipios
  if (!CONTAGENS.every((campo) => inteiro(n[campo]))) return null
  const municipios = {
    prontos: n.prontos as number, em_execucao: n.em_execucao as number, com_erro: n.com_erro as number,
    pendentes: n.pendentes as number, desconhecidos: n.desconhecidos as number,
  }
  const soma = Object.values(municipios).reduce((a, b) => a + b, 0)
  if (!Number.isSafeInteger(soma) || soma !== valor.municipios_total) return null
  const observado = instante(valor.observado_em), mudanca = instante(valor.ultima_mudanca_em), validade = instante(valor.valido_ate)
  if (observado === null || mudanca === null || validade === null || mudanca > observado ||
      validade <= observado || validade - observado > HORA) return null
  return {
    uf, escopo: valor.escopo, unidade: valor.unidade, municipios_total: valor.municipios_total, municipios,
    observado_em: valor.observado_em as string, ultima_mudanca_em: valor.ultima_mudanca_em as string,
    valido_ate: valor.valido_ate as string, situacao: "atual",
  }
}
