import type { Geo } from "./tipos"

export const AVISO_AGREGADOS = "Cobertura parcial. Cada ponto representa uma célula estatística, nunca a posição de uma fazenda. A contagem reúne as fazendas presentes no agregado; células com menos de cinco CARs foram omitidas. Os hectares conhecidos somam somente contribuintes positivos sem sobreposição detectada, com pelo menos cinco por célula. Sem medida suficiente, o valor permanece desconhecido. Não representa toda a área ou todas as fazendas do território, nem disponibilidade para venda."

export interface AgregadosMapa {
  geo: Geo
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

/** O navegador só lê o agregado nacional pronto; nunca pede medidas por imóvel para montar grupos. */
export function lerAgregadosMapa(valor: unknown): AgregadosMapa | null {
  const v = objeto(valor), m = objeto(v.metadados)
  if (v.type !== "FeatureCollection" || !Array.isArray(v.features) || m.contrato !== "agregados_mapa" || m.versao !== 1
    || m.resolucao !== 5 || m.minimo_contribuintes !== 5 || m.cobertura !== "parcial" || m.metodo !== "centro_celula_h3") return null
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
  return { geo: { type: "FeatureCollection", features }, metadados: {
    resolucao: 5, cobertura: "parcial", metodo: "centro_celula_h3", minimo_contribuintes: 5,
    atualizado_em: typeof m.atualizado_em === "string" && Number.isFinite(Date.parse(m.atualizado_em)) ? m.atualizado_em : null,
    fonte: "Motor da Raíz: carbono_ha, pasto perto de floresta além da reserva legal.", aviso: AVISO_AGREGADOS,
    contagens: { celulas: features.length, celulas_sem_medida: features.filter(f => f.properties.potencial_ha === null).length, fazendas_no_agregado: fazendas },
  } }
}
