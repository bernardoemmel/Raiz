/** Projeção de defesa do build: geometria H3 reconstruída, nunca copiada da entrada. */
import fs from "node:fs"
import path from "node:path"
import zlib from "node:zlib"
import { createRequire } from "node:module"
import { AVISO_AGREGADOS } from "./dados/agregados"

// O módulo compartilhado fica fora de globo/node_modules e também participa do build do produtor.
const { cellToBoundary, cellToLatLng, getResolution, isValidCell } = createRequire(new URL("../globo/package.json", import.meta.url))("h3-js") as {
  cellToBoundary(celula: string, geojson: boolean): [number, number][]
  cellToLatLng(celula: string): [number, number]
  getResolution(celula: string): number
  isValidCell(celula: string): boolean
}

const UFS = new Set("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split(" "))
const DOMINIO = [0, 100, 1000, 10000, 50000]
const objeto = (v: unknown): Record<string, unknown> => v && typeof v === "object" && !Array.isArray(v) ? v as Record<string, unknown> : {}
const contagem = (v: unknown): number | null => typeof v === "number" && Number.isSafeInteger(v) && v >= 0 ? v : null
const data = (v: unknown): string | null => typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v) && Number.isFinite(Date.parse(v)) ? new Date(v).toISOString() : null

export function projetarPotencial(valor: unknown) {
  const v = objeto(valor), m = objeto(v.metadados)
  if (v.type !== "FeatureCollection" || !Array.isArray(v.features) || m.contrato !== "potencial_h3" || m.versao !== 1
    || m.resolucao !== 5 || m.metodo !== "ponto_interior_estatistico" || m.minimo_contribuintes !== 5 || m.cobertura !== "parcial") throw new Error("Contrato público H3 inválido")
  const vistos = new Set<string>()
  const features = v.features.map((valor) => {
    const p = objeto(objeto(valor).properties), h = p.h3, n = contagem(p.fazendas), ha = p.potencial_ha
    if (typeof h !== "string" || !isValidCell(h) || getResolution(h) !== 5 || vistos.has(h) || n === null || n < 5
      || (ha !== null && (typeof ha !== "number" || !Number.isFinite(ha) || ha <= 0))) throw new Error("Célula H3 fora do contrato anônimo")
    vistos.add(h)
    return { type: "Feature", properties: { h3: h, potencial_ha: ha as number | null, fazendas: n },
      geometry: { type: "Polygon", coordinates: [cellToBoundary(h, true)] } }
  })
  const c = objeto(m.contagens)
  const contagens = Object.fromEntries(["fazendas_com_geometria", "incluidas", "sem_medida", "com_sobreposicao", "sem_geometria"].map(k => [k, contagem(c[k])]))
  return { type: "FeatureCollection", features, metadados: {
    contrato: "potencial_h3", versao: 1, resolucao: 5, dominio_ha: DOMINIO,
    atualizado_em: data(m.atualizado_em), fonte_mais_antiga_em: data(m.fonte_mais_antiga_em), gerado_em: data(m.gerado_em),
    fonte: "Motor da Raíz: carbono_ha, pasto perto de floresta além da reserva legal.",
    metodo: "ponto_interior_estatistico", cobertura: "parcial", minimo_contribuintes: 5, zoom_maximo: 11,
    contagens, celulas_publicadas: contagem(m.celulas_publicadas),
    aviso: "Potencial conhecido, cobertura parcial. Soma somente áreas positivas de imóveis sem sobreposição detectada, com pelo menos cinco contribuintes por célula. Áreas ausentes ou sobrepostas não entram na soma. O ponto interior localiza o imóvel inteiro: o hexágono não é o desenho da restauração nem mede hectares fisicamente dentro da célula. Células de fronteira são repetidas entre UFs e devem ser contadas uma única vez. Não é área disponível para venda nem prova de elegibilidade.",
  } }
}

/** Nacional leve: deduplica fronteiras antes de contar e não reutiliza coordenadas da entrada. */
export function projetarAgregados(colecoes: unknown[]) {
  const celulas = new Map<string, ReturnType<typeof projetarPotencial>["features"][number]["properties"]>()
  let meta: ReturnType<typeof projetarPotencial>["metadados"] | null = null
  for (const colecao of colecoes) {
    const p = projetarPotencial(colecao)
    if (meta && JSON.stringify(meta) !== JSON.stringify(p.metadados)) throw new Error("Agregados nacionais misturam execuções")
    meta = p.metadados
    for (const f of p.features) {
      const anterior = celulas.get(f.properties.h3)
      if (anterior && (anterior.fazendas !== f.properties.fazendas || anterior.potencial_ha !== f.properties.potencial_ha)) throw new Error("Célula de fronteira contraditória no agregado nacional")
      celulas.set(f.properties.h3, f.properties)
    }
  }
  if (!meta) return null
  const features = [...celulas.values()].sort((a, b) => a.h3.localeCompare(b.h3)).map(p => {
    const [lat, lon] = cellToLatLng(p.h3)
    return { type: "Feature", properties: { h3: p.h3, fazendas: p.fazendas, potencial_ha: p.potencial_ha }, geometry: { type: "Point", coordinates: [lon, lat] } }
  })
  const fazendas = features.reduce((s, f) => s + f.properties.fazendas, 0)
  if (!Number.isSafeInteger(fazendas)) throw new Error("Contagem nacional fora do contrato público")
  return { type: "FeatureCollection", features, metadados: {
    contrato: "agregados_mapa", versao: 1, resolucao: 5, cobertura: "parcial", metodo: "centro_celula_h3", minimo_contribuintes: 5,
    atualizado_em: meta.atualizado_em, fonte_mais_antiga_em: meta.fonte_mais_antiga_em, gerado_em: meta.gerado_em,
    fonte: meta.fonte, aviso: AVISO_AGREGADOS,
    contagens: { celulas: features.length, celulas_sem_medida: features.filter(f => f.properties.potencial_ha === null).length, fazendas_no_agregado: fazendas },
    supressao: { minimo_car_por_celula: 5, minimo_contribuintes_positivos: 5, grupos_pequenos_omitidos: true },
  } }
}

export function potencialPublicado(geo: string) {
  const arquivo = path.join(geo, "potencial_indice.json")
  const indice: Record<string, { arquivo: string; bytes: number }> = {}
  const arquivos: Record<string, Buffer> = {}
  const colecoes: unknown[] = []
  let agregados: { arquivo: string; bytes: number } | null = null
  let metadados: ReturnType<typeof projetarPotencial>["metadados"] | null = null
  if (!fs.existsSync(arquivo)) return { indice, arquivos, metadados, agregados }
  const origem = objeto(JSON.parse(fs.readFileSync(arquivo, "utf8")))
  for (const [uf, item] of Object.entries(objeto(origem.potencial))) {
    if (!UFS.has(uf)) throw new Error("UF inválida no índice H3")
    const nome = `potencial_${uf}.geojson.gz`
    if (objeto(item).arquivo !== nome) throw new Error("Caminho H3 fora do contrato público")
    const bruto = fs.readFileSync(path.join(geo, nome))
    const projetado = projetarPotencial(JSON.parse(zlib.gunzipSync(bruto).toString("utf8")))
    if (metadados && JSON.stringify(metadados) !== JSON.stringify(projetado.metadados)) throw new Error("Células H3 misturam execuções")
    metadados = projetado.metadados
    colecoes.push(projetado)
    arquivos[nome] = zlib.gzipSync(JSON.stringify(projetado), { level: 6 })
    indice[uf] = { arquivo: nome, bytes: arquivos[nome].length }
  }
  const nacional = projetarAgregados(colecoes)
  if (nacional) {
    const nome = "agregados_brasil.geojson.gz", dados = zlib.gzipSync(JSON.stringify(nacional), { level: 6 })
    if (dados.length > 560_000) throw new Error("O agregado nacional excedeu o limite de 560 KB")
    arquivos[nome] = dados
    agregados = { arquivo: nome, bytes: dados.length }
  }
  return { indice, arquivos, metadados, agregados }
}
