import type { Geo } from "./tipos"

export const AVISO_AGREGADOS = "Cobertura parcial. Cada ponto representa uma célula estatística, nunca a posição de uma fazenda. A contagem reúne as fazendas presentes no agregado; células com menos de cinco CARs foram omitidas. Os hectares conhecidos somam somente contribuintes positivos sem sobreposição detectada, com pelo menos cinco por célula. Sem medida suficiente, o valor permanece desconhecido. Não representa toda a área ou todas as fazendas do território, nem disponibilidade para venda."
export const LIMITE_AGREGADOS_GZIP = 560_000
export const LIMITE_AGREGADOS_NORMAL = 2_500_000
export const LIMITE_AGREGADOS_TOTAL = LIMITE_AGREGADOS_GZIP + LIMITE_AGREGADOS_NORMAL

export interface AgregadosMapa {
  geo?: Geo | null
  url?: string | null
  metadados: {
    resolucao: 5
    cobertura: "parcial"
    metodo: "centro_celula_h3"
    atualizado_em: string | null
    fonte: string
    aviso: string
    minimo_contribuintes: 5
    contagens: { celulas: number; celulas_sem_medida: number; fazendas_no_agregado: number }
  }
}

const objeto = (v: unknown): Record<string, unknown> => v && typeof v === "object" && !Array.isArray(v) ? v as Record<string, unknown> : {}
const contagem = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0
const contrato = (m: Record<string, unknown>) => m.contrato === "agregados_mapa" && m.versao === 1
  && m.resolucao === 5 && m.minimo_contribuintes === 5 && m.cobertura === "parcial" && m.metodo === "centro_celula_h3"

/** Metadados pequenos do índice; as feições já passaram pela projeção positiva no build. */
export function lerMetadadosAgregados(valor: unknown): AgregadosMapa["metadados"] | null {
  const m = objeto(valor), c = objeto(m.contagens)
  if (!contrato(m) || !contagem(c.celulas) || !contagem(c.celulas_sem_medida) || !contagem(c.fazendas_no_agregado)
    || c.celulas_sem_medida > c.celulas || !Number.isSafeInteger(c.celulas * 5) || c.fazendas_no_agregado < c.celulas * 5
    || (c.celulas === 0 && c.fazendas_no_agregado !== 0)) return null
  return {
    resolucao: 5, cobertura: "parcial", metodo: "centro_celula_h3", minimo_contribuintes: 5,
    atualizado_em: typeof m.atualizado_em === "string" && /^\d{4}-\d{2}-\d{2}T/.test(m.atualizado_em) && Number.isFinite(Date.parse(m.atualizado_em)) ? new Date(m.atualizado_em).toISOString() : null,
    fonte: "Motor da Raíz: carbono_ha, pasto perto de floresta além da reserva legal.", aviso: AVISO_AGREGADOS,
    contagens: { celulas: c.celulas, celulas_sem_medida: c.celulas_sem_medida, fazendas_no_agregado: c.fazendas_no_agregado },
  }
}

/** URL pública fixa, sem corpo na thread principal. O SHA é conferido no build, não pelo worker. */
export function lerAgregadosMapaUrl(valor: unknown, base: string, origem: string, pagina = origem): AgregadosMapa | null {
  const item = objeto(valor), normal = objeto(item.normal), metadados = lerMetadadosAgregados(item.metadados)
  const hash = (v: unknown) => typeof v === "string" && v.length === 64 && /^[0-9a-f]{64}$/.test(v)
  if (!metadados || item.arquivo !== "agregados_brasil.geojson.gz" || normal.arquivo !== "agregados_brasil.geojson"
    || !contagem(item.bytes) || item.bytes < 1 || item.bytes > LIMITE_AGREGADOS_GZIP
    || !contagem(normal.bytes) || normal.bytes < 1 || normal.bytes > LIMITE_AGREGADOS_NORMAL
    || item.bytes_total !== item.bytes + normal.bytes || item.bytes_total > LIMITE_AGREGADOS_TOTAL
    || !hash(item.sha256) || !hash(normal.sha256)) return null
  try {
    const raiz = new URL(base.endsWith("/") ? base : base + "/", pagina)
    if (raiz.origin !== origem || raiz.username || raiz.password || raiz.search || raiz.hash) return null
    const url = new URL("geo/agregados_brasil.geojson", raiz)
    return { url: url.href, metadados }
  } catch { return null }
}

/** O navegador só lê o agregado nacional pronto; nunca pede medidas por imóvel para montar grupos. */
export function lerAgregadosMapa(valor: unknown): (AgregadosMapa & { geo: Geo }) | null {
  const v = objeto(valor), m = objeto(v.metadados)
  if (v.type !== "FeatureCollection" || !Array.isArray(v.features) || !contrato(m)) return null
  const vistos = new Set<string>(), features: Geo["features"] = []
  for (const item of v.features) {
    const f = objeto(item), p = objeto(f.properties), g = objeto(f.geometry), c = g.coordinates
    if (f.type !== "Feature" || typeof p.h3 !== "string" || !/^85[0-9a-f]{13}$/.test(p.h3) || vistos.has(p.h3)
      || !Number.isSafeInteger(p.fazendas) || Number(p.fazendas) < 5
      || (p.potencial_ha !== null && (typeof p.potencial_ha !== "number" || !Number.isFinite(p.potencial_ha) || p.potencial_ha <= 0))
      || g.type !== "Point" || !Array.isArray(c) || c.length !== 2 || !c.every(n => typeof n === "number" && Number.isFinite(n))
      || Math.abs(c[0]) > 180 || Math.abs(c[1]) > 90) return null
    vistos.add(p.h3)
    features.push({ type: "Feature", properties: { h3: p.h3, fazendas: p.fazendas, potencial_ha: p.potencial_ha }, geometry: { type: "Point", coordinates: [c[0], c[1]] } })
  }
  const fazendas = features.reduce((s, f) => s + Number(f.properties.fazendas), 0)
  if (!Number.isSafeInteger(fazendas)) return null
  const metadados = lerMetadadosAgregados({ ...m,
    contagens: { celulas: features.length, celulas_sem_medida: features.filter(f => f.properties.potencial_ha === null).length, fazendas_no_agregado: fazendas },
  })
  return metadados ? { geo: { type: "FeatureCollection", features }, metadados } : null
}
