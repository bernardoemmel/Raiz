import { cellToBoundary, cellToLatLng, cellToParent, getHexagonAreaAvg, getResolution, isValidCell, polygonToCellsExperimental, POLYGON_TO_CELLS_FLAGS, UNITS } from "h3-js"
import type { Geo } from "../../../compartilhado/dados"
import { CORES_H3_V2 } from "../../../compartilhado/cores"

export type ResolucaoHexagonos = 4 | 5
export type MetricaHexagonos = "fazendas" | "potencial_ha"
export type CaixaHexagonos = [oeste: number, sul: number, leste: number, norte: number]
export type EscalaHexagonos = [number, number, number, number, number, number]
export const CORES_HEXAGONOS = CORES_H3_V2
export const LIMITES_FAZENDAS: Record<ResolucaoHexagonos, EscalaHexagonos> = {
  4: [1, 60, 200, 500, 1100, 2500],
  5: [1, 15, 40, 90, 200, 450],
}

export interface LegendaHexagonos {
  resolucao: ResolucaoHexagonos
  metrica: MetricaHexagonos
  limites: EscalaHexagonos
  cores: typeof CORES_HEXAGONOS
  titulo: string
  unidade: "fazendas cadastradas" | "ha conhecidos"
  areaAproximadaKm2: number
}

/** Cada item identifica uma célula estatística, nunca um imóvel ou um lote. */
export interface HexagonoMapa {
  h3: string
  chave: string
  centro: [number, number]
  resolucao: ResolucaoHexagonos
  fazendas: number
  hectares: number | null
  semMedida: number
  parcial: boolean
}

export interface ResumoHexagonos {
  celulas: number
  fazendas: number
  hectares: number | null
  semMedida: number
  parcial: boolean
  metrica: MetricaHexagonos
  legendas: Record<ResolucaoHexagonos, LegendaHexagonos>
}

export interface ConsultaHexagonos {
  geo: Geo
  hexagonos: HexagonoMapa[]
  legenda: LegendaHexagonos
}

interface Celula extends HexagonoMapa {
  poligono: number[][]
  caixa: CaixaHexagonos
}
interface Medidas { h3: string; fazendas: number; hectares: number | null; semMedida: number }
const objeto = (v: unknown): Record<string, unknown> => v && typeof v === "object" && !Array.isArray(v) ? v as Record<string, unknown> : {}
const invalido = () => new Error("Agregados públicos inválidos.")
const longitude = (n: number) => ((n + 180) % 360 + 360) % 360 - 180

/** Aceita só polígonos autorizados e descarta IDs e propriedades antes de retê-los no worker. */
export function projetarAreaAutorizada(valor: unknown): Geo | null {
  if (valor === null) return null
  const falha = () => new Error("Área autorizada inválida.")
  const colecao = objeto(valor)
  if (colecao.type !== "FeatureCollection" || !Array.isArray(colecao.features)) throw falha()
  const poligono = (valor: unknown): number[][][] => {
    if (!Array.isArray(valor) || !valor.length) throw falha()
    return valor.map(entrada => {
      if (!Array.isArray(entrada) || entrada.length < 4) throw falha()
      const anel = entrada.map(ponto => {
        if (!Array.isArray(ponto) || ponto.length !== 2 || !ponto.every(n => typeof n === "number" && Number.isFinite(n))
          || Math.abs(ponto[0]) > 180 || Math.abs(ponto[1]) > 90) throw falha()
        return [ponto[0], ponto[1]]
      })
      if (anel[0][0] !== anel.at(-1)![0] || anel[0][1] !== anel.at(-1)![1]) throw falha()
      const x = anel.map(p => longitude(p[0] - anel[0][0]))
      const area = anel.slice(0, -1).reduce((s, p, i) => s + x[i] * (anel[i + 1][1] - anel[0][1]) - x[i + 1] * (p[1] - anel[0][1]), 0)
      if (!Number.isFinite(area) || area === 0) throw falha()
      return anel
    })
  }
  return { type: "FeatureCollection", features: colecao.features.map(valor => {
    const f = objeto(valor), g = objeto(f.geometry)
    if (f.type !== "Feature") throw falha()
    if (g.type === "Polygon") return { type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: poligono(g.coordinates) } }
    if (g.type === "MultiPolygon" && Array.isArray(g.coordinates) && g.coordinates.length)
      return { type: "Feature", properties: {}, geometry: { type: "MultiPolygon", coordinates: g.coordinates.map(poligono) } }
    throw falha()
  }) }
}

/** A projeção positiva acontece antes da agregação; campos acrescidos à fonte não atravessam o worker. */
function medidasPublicas(valor: unknown): Medidas[] {
  if (valor === null) return []
  const colecao = objeto(valor)
  if (colecao.type !== "FeatureCollection" || !Array.isArray(colecao.features)) throw invalido()
  const vistas = new Map<string, Medidas>()
  for (const entrada of colecao.features) {
    const f = objeto(entrada), p = objeto(f.properties), g = objeto(f.geometry), c = g.coordinates
    if (f.type !== "Feature" || g.type !== "Point" || !Array.isArray(c) || c.length !== 2
      || !c.every(n => typeof n === "number" && Number.isFinite(n)) || Math.abs(c[0]) > 180 || Math.abs(c[1]) > 90
      || typeof p.h3 !== "string" || !/^85[0-9a-f]{13}$/.test(p.h3) || !isValidCell(p.h3) || getResolution(p.h3) !== 5
      || typeof p.fazendas !== "number" || !Number.isSafeInteger(p.fazendas) || p.fazendas < 0
      || (p.potencial_ha !== null && (typeof p.potencial_ha !== "number" || !Number.isFinite(p.potencial_ha) || p.potencial_ha < 0))) throw invalido()
    const medida: Medidas = { h3: p.h3, fazendas: p.fazendas, hectares: p.potencial_ha as number | null, semMedida: p.potencial_ha === null ? 1 : 0 }
    const anterior = vistas.get(medida.h3)
    if (anterior && (anterior.fazendas !== medida.fazendas || anterior.hectares !== medida.hectares)) throw invalido()
    vistas.set(medida.h3, medida)
  }
  // Mantém o limiar público de privacidade mesmo quando uma entrada em memória não passou pelo adaptador.
  return [...vistas.values()].filter(m => m.fazendas >= 5)
}

function somar(a: Medidas, b: Medidas): void {
  a.fazendas += b.fazendas
  a.semMedida += b.semMedida
  if (b.hectares !== null) a.hectares = (a.hectares ?? 0) + b.hectares
  if (!Number.isSafeInteger(a.fazendas) || (a.hectares !== null && !Number.isFinite(a.hectares))) throw invalido()
}

function celula(m: Medidas, resolucao: ResolucaoHexagonos): Celula {
  const [lat, lng] = cellToLatLng(m.h3)
  // Desembrulha a borda em torno do centro: uma célula no antimeridiano não pode atravessar o mundo inteiro.
  const poligono = cellToBoundary(m.h3, true).map(([x, y]) => [lng + longitude(x - lng), y])
  if (poligono[0][0] !== poligono.at(-1)![0] || poligono[0][1] !== poligono.at(-1)![1]) poligono.push([...poligono[0]])
  return { ...m, chave: m.h3, resolucao, centro: [lng, lat], parcial: m.semMedida > 0, poligono,
    caixa: [Math.min(...poligono.map(p => p[0])), Math.min(...poligono.map(p => p[1])), Math.max(...poligono.map(p => p[0])), Math.max(...poligono.map(p => p[1]))] }
}

function legenda(celulas: Celula[], resolucao: ResolucaoHexagonos, metrica: MetricaHexagonos): LegendaHexagonos {
  // Intervalos iguais de hectares, calculados do conjunto completo nessa resolução. Nunca reutiliza cortes de cadastros.
  const maior = celulas.reduce((n, c) => Math.max(n, c.hectares ?? 0), 0)
  const passo = (maior || 1) / 6
  const limites: EscalaHexagonos = metrica === "fazendas" ? [...LIMITES_FAZENDAS[resolucao]] : [0, passo, passo * 2, passo * 3, passo * 4, passo * 5]
  return { resolucao, metrica, limites, cores: CORES_HEXAGONOS,
    titulo: metrica === "fazendas" ? "Fazendas cadastradas por hexágono" : "Hectares conhecidos por hexágono",
    unidade: metrica === "fazendas" ? "fazendas cadastradas" : "ha conhecidos",
    areaAproximadaKm2: getHexagonAreaAvg(resolucao, UNITS.km2) }
}

function visivel(celula: Celula, bbox: CaixaHexagonos): boolean {
  const [oeste, sul, leste, norte] = bbox, [minX, minY, maxX, maxY] = celula.caixa
  if (maxY < sul || minY > norte) return false
  const amplitude = leste - oeste
  if (Math.abs(amplitude) >= 360) return true
  const inicio = longitude(oeste), fim = inicio + (amplitude < 0 ? amplitude + 360 : amplitude)
  return [-360, 0, 360].some(deslocamento => maxX + deslocamento >= inicio && minX + deslocamento <= fim)
}

/** O índice e as duas resoluções vivem no worker. A interface recebe só o enquadramento solicitado. */
export class IndiceHexagonos {
  readonly resumo: ResumoHexagonos
  private readonly celulas: Record<ResolucaoHexagonos, Celula[]>
  private readonly idsPublicos: Set<string>
  private idsAutorizados = new Set<string>()

  constructor(dados: unknown) {
    const medidas = medidasPublicas(dados), pais = new Map<string, Medidas>()
    this.idsPublicos = new Set(medidas.map(m => m.h3))
    const totais: Medidas = { h3: "", fazendas: 0, hectares: null, semMedida: 0 }
    for (const medida of medidas) {
      somar(totais, medida)
      const h3 = cellToParent(medida.h3, 4)
      const pai = pais.get(h3) ?? { h3, fazendas: 0, hectares: null, semMedida: 0 }
      somar(pai, medida)
      pais.set(h3, pai)
    }
    this.celulas = { 4: [...pais.values()].map(m => celula(m, 4)), 5: medidas.map(m => celula(m, 5)) }
    for (const lista of Object.values(this.celulas)) lista.sort((a, b) => b.fazendas - a.fazendas || a.h3.localeCompare(b.h3))
    const metrica: MetricaHexagonos = medidas.length > 0 && totais.semMedida === 0 ? "potencial_ha" : "fazendas"
    this.resumo = { celulas: medidas.length, fazendas: totais.fazendas, hectares: totais.hectares, semMedida: totais.semMedida,
      parcial: totais.semMedida > 0, metrica, legendas: { 4: legenda(this.celulas[4], 4, metrica), 5: legenda(this.celulas[5], 5, metrica) } }
  }

  /** A interseção vem do desenho autorizado; não usa centro de lote, contagem ou percentuais para supor fazendas. */
  destacarAutorizada(geo: Geo | null): void {
    this.idsAutorizados.clear()
    const projetado = projetarAreaAutorizada(geo)
    const permitidos = new Set<string>()
    for (const f of projetado?.features ?? []) {
      const poligonos = f.geometry.type === "Polygon" ? [f.geometry.coordinates as number[][][]] : f.geometry.coordinates as number[][][][]
      for (const poligono of poligonos) {
        // containmentCenter perde imóveis menores que uma célula. Overlapping considera a interseção do polígono real.
        const ids = polygonToCellsExperimental(poligono, 5, POLYGON_TO_CELLS_FLAGS.containmentOverlapping, true)
        for (const h3 of ids) if (this.idsPublicos.has(h3)) permitidos.add(h3)
      }
    }
    this.idsAutorizados = permitidos
  }

  consultar(bbox: CaixaHexagonos, zoom: number, destaques: readonly string[] = []): ConsultaHexagonos {
    if (!Array.isArray(bbox) || bbox.length !== 4 || !bbox.every(Number.isFinite) || bbox[1] > bbox[3] || !Number.isFinite(zoom))
      throw new Error("Enquadramento dos hexágonos inválido.")
    const resolucao = zoom < 5 ? 4 : 5
    const autorizadas = new Set([...destaques, ...this.idsAutorizados].filter(h3 => this.idsPublicos.has(h3)).map(h3 => resolucao === 4 ? cellToParent(h3, 4) : h3))
    const selecionadas = zoom >= 9 ? [] : this.celulas[resolucao].filter(c => visivel(c, bbox))
    const metrica = this.resumo.metrica
    return { legenda: this.resumo.legendas[resolucao],
      hexagonos: selecionadas.map(({ h3, chave, centro, resolucao, fazendas, hectares, semMedida, parcial }) => ({ h3, chave, centro, resolucao, fazendas, hectares, semMedida, parcial })),
      geo: { type: "FeatureCollection", features: selecionadas.map(c => ({ type: "Feature", id: c.h3,
        properties: { h3: c.h3, resolucao, fazendas: c.fazendas, potencial_ha: c.hectares, sem_medida: c.semMedida, parcial: c.parcial,
          valor: metrica === "fazendas" ? c.fazendas : c.hectares, selecionado: autorizadas.has(c.h3) },
        geometry: { type: "Polygon", coordinates: [c.poligono] } })) } }
  }
}
