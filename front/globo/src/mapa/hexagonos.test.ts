import { cellToBoundary, cellToChildren, cellToLatLng, cellToParent, latLngToCell, polygonToCells } from "h3-js"
import { describe, expect, it } from "vitest"
import type { Geo } from "../../../compartilhado/dados"
import { CORES_HEXAGONOS, IndiceHexagonos, LIMITES_FAZENDAS, projetarAreaAutorizada, type CaixaHexagonos } from "./hexagonos"

const mundo: CaixaHexagonos = [-180, -90, 180, 90]
const pai = cellToParent(latLngToCell(-6, -50, 5), 4)
const filhos = cellToChildren(pai, 5)
const ponto = (h3: string, fazendas = 5, hectares: number | null = 10): Geo["features"][number] => {
  const [lat, lng] = cellToLatLng(h3)
  return { type: "Feature", geometry: { type: "Point", coordinates: [lng, lat] },
    properties: { h3, fazendas, potencial_ha: hectares, cod_imovel: "NAO-PUBLICAR", nome: "NAO-PUBLICAR", lote: "PRIVADO" } }
}
const geo = (features: Geo["features"]): Geo => ({ type: "FeatureCollection", features })
const recortePequeno = (h3: string): number[][][] => {
  const [lat, lng] = cellToLatLng(h3), [vx, vy] = cellToBoundary(h3, true)[0]
  const x = (lng + vx) / 2, y = (lat + vy) / 2, d = 0.0001
  return [[[x - d, y - d], [x + d, y - d], [x + d, y + d], [x - d, y + d], [x - d, y - d]]]
}
const area = (h3: string): Geo => geo([{ type: "Feature", id: "CAR-PRIVADO", properties: { cod_imovel: "CAR-PRIVADO", nome: "NAO-PUBLICAR" }, geometry: { type: "Polygon", coordinates: recortePequeno(h3) } }])

describe("hexágonos públicos calculados no worker", () => {
  it("agrega r5 em r4, deduplica células de fronteira e conserva hectares parcialmente conhecidos", () => {
    const primeiro = ponto(filhos[0], 8, 12.5)
    const indice = new IndiceHexagonos(geo([primeiro, { ...primeiro }, ponto(filhos[1], 5, null), ponto(filhos[2], 4, 100)]))
    expect(indice.resumo).toMatchObject({ celulas: 2, fazendas: 13, hectares: 12.5, semMedida: 1, parcial: true, metrica: "fazendas" })
    const nacional = indice.consultar(mundo, 4.99)
    expect(nacional.hexagonos).toMatchObject([{ h3: pai, resolucao: 4, fazendas: 13, hectares: 12.5, semMedida: 1, parcial: true }])
    expect(nacional.legenda.limites).toEqual(LIMITES_FAZENDAS[4])
    expect(nacional.legenda.titulo).toBe("Fazendas cadastradas por hexágono")
    const estadual = indice.consultar(mundo, 5)
    expect(estadual.hexagonos).toHaveLength(2)
    expect(estadual.hexagonos.map(c => c.h3)).toEqual([filhos[0], filhos[1]])
    expect(estadual.legenda.limites).toEqual(LIMITES_FAZENDAS[5])
    expect(indice.consultar(mundo, 8.99).hexagonos).toHaveLength(2)
    expect(indice.consultar(mundo, 9)).toMatchObject({ hexagonos: [], geo: { features: [] } })
  })

  it("calcula escala de hectares só com medidas completas em toda a fonte e diferencia zero de desconhecido", () => {
    const completo = new IndiceHexagonos(geo([ponto(filhos[0], 8, 0), ponto(filhos[1], 10, 120)]))
    expect(completo.resumo).toMatchObject({ hectares: 120, semMedida: 0, parcial: false, metrica: "potencial_ha" })
    expect(completo.consultar(mundo, 5).geo.features.map(f => f.properties.valor)).toEqual([120, 0])
    expect(completo.resumo.legendas[5]).toMatchObject({ limites: [0, 20, 40, 60, 80, 100], unidade: "ha conhecidos", cores: CORES_HEXAGONOS })
    expect(completo.resumo.legendas[5].areaAproximadaKm2).toBeGreaterThan(200)
    const parcial = new IndiceHexagonos(geo([ponto(filhos[0], 8, 0), ponto(filhos[1], 10, null)]))
    expect(parcial.consultar(mundo, 4).hexagonos[0]).toMatchObject({ hectares: 0, parcial: true, semMedida: 1 })
    expect(parcial.resumo.metrica).toBe("fazendas")
    const distante = latLngToCell(-25, -40, 5)
    const global = new IndiceHexagonos(geo([ponto(filhos[0], 8, 10), ponto(distante, 10, null)]))
    expect(global.consultar([-51, -7, -49, -5], 5).legenda.metrica).toBe("fazendas")
    expect(new IndiceHexagonos(geo([ponto(filhos[0], 5, null)])).resumo.hectares).toBeNull()
  })

  it("devolve polígonos fechados, geometria H3 e apenas a lista positiva de campos públicos", () => {
    const entrada = ponto(filhos[0])
    const indice = new IndiceHexagonos(geo([{ ...entrada, geometry: { type: "Point", coordinates: [0, 0] } }]))
    const consulta = indice.consultar(mundo, 5)
    const f = consulta.geo.features[0]
    const anel = (f.geometry.coordinates as number[][][])[0]
    expect(f.geometry.type).toBe("Polygon")
    expect(anel[0]).toEqual(anel.at(-1))
    expect(consulta.hexagonos[0].centro).toEqual(cellToLatLng(filhos[0]).reverse())
    expect(Object.keys(f.properties).sort()).toEqual(["h3", "resolucao", "fazendas", "potencial_ha", "sem_medida", "parcial", "valor", "selecionado"].sort())
    for (const proibido of ["NAO-PUBLICAR", "cod_imovel", "nome", "PRIVADO", "lote", "aptas"]) expect(JSON.stringify(consulta)).not.toContain(proibido)
  })

  it("recorta pelo enquadramento incluindo a borda visível, antimeridiano e cópias do mundo", () => {
    const a = latLngToCell(0, 179, 5), b = latLngToCell(0, -179, 5), c = latLngToCell(0, 0, 5)
    const indice = new IndiceHexagonos(geo([ponto(a), ponto(b), ponto(c)]))
    const cruzado = indice.consultar([170, -5, -170, 5], 5)
    expect(new Set(cruzado.hexagonos.map(h => h.h3))).toEqual(new Set([a, b]))
    expect(indice.consultar([170, -5, 190, 5], 5)).toEqual(cruzado)
    expect(indice.consultar([530, -5, 550, 5], 5)).toEqual(cruzado)
    expect(indice.consultar([-540, -90, 540, 90], 5).hexagonos).toHaveLength(3)
    const poligono = indice.consultar(mundo, 5).geo.features.find(f => f.id === c)!.geometry.coordinates as number[][][]
    const [x, y] = poligono[0][0]
    expect(indice.consultar([x, y, x, y], 5).hexagonos.map(h => h.h3)).toEqual([c])
    const borda = latLngToCell(0, 179.999, 5)
    const anel = new IndiceHexagonos(geo([ponto(borda)])).consultar(mundo, 5).geo.features[0].geometry.coordinates as number[][][]
    expect(Math.max(...anel[0].map(p => p[0])) - Math.min(...anel[0].map(p => p[0]))).toBeLessThan(1)
  })

  it("destaca somente H3 autorizados que existem na fonte e seus pais r4", () => {
    const indice = new IndiceHexagonos(geo([ponto(filhos[0]), ponto(filhos[1])]))
    expect(indice.consultar(mundo, 5).geo.features.every(f => f.properties.selecionado === false)).toBe(true)
    const destaques = [filhos[0], filhos[2], "incorreto"]
    expect(indice.consultar(mundo, 5, destaques).geo.features.filter(f => f.properties.selecionado).map(f => f.id)).toEqual([filhos[0]])
    expect(indice.consultar(mundo, 4, destaques).geo.features.filter(f => f.properties.selecionado).map(f => f.id)).toEqual([pai])
  })

  it("intersecta um recorte autorizado menor que a célula, sem centro dentro, e null remove a seleção", () => {
    const indice = new IndiceHexagonos(geo([ponto(filhos[0]), ponto(filhos[1])]))
    expect(polygonToCells(recortePequeno(filhos[0]), 5, true)).toEqual([])
    indice.destacarAutorizada(area(filhos[0]))
    const consulta = indice.consultar(mundo, 5)
    expect(consulta.geo.features.filter(f => f.properties.selecionado).map(f => f.id)).toEqual([filhos[0]])
    expect(consulta.geo.features).toHaveLength(2)
    expect(consulta.hexagonos.reduce((n, h) => n + h.fazendas, 0)).toBe(10)
    expect(indice.consultar(mundo, 4).geo.features[0].properties.selecionado).toBe(true)
    for (const proibido of ["NAO-PUBLICAR", "CAR-PRIVADO", "cod_imovel", "nome"]) expect(JSON.stringify(consulta)).not.toContain(proibido)
    expect(projetarAreaAutorizada(area(filhos[0]))!.features[0]).toEqual({ type: "Feature", properties: {}, geometry: area(filhos[0]).features[0].geometry })
    indice.destacarAutorizada(null)
    expect(indice.consultar(mundo, 5).geo.features.every(f => f.properties.selecionado === false)).toBe(true)
  })

  it("aceita MultiPolygon, combina H3 explícitos e não inventa células ausentes da fonte", () => {
    const indice = new IndiceHexagonos(geo([ponto(filhos[0]), ponto(filhos[1]), ponto(filhos[2])]))
    indice.destacarAutorizada(geo([{ type: "Feature", properties: {}, geometry: { type: "MultiPolygon", coordinates: [recortePequeno(filhos[0]), recortePequeno(filhos[1]), recortePequeno(filhos[3])] } }]))
    expect(indice.consultar(mundo, 5).geo.features.filter(f => f.properties.selecionado).map(f => f.id)).toEqual([filhos[0], filhos[1]])
    expect(indice.consultar(mundo, 5, [filhos[2]]).geo.features.filter(f => f.properties.selecionado)).toHaveLength(3)
  })

  it("rejeita área autorizada fora do contrato e limpa a seleção anterior sem expor coordenadas ou propriedades", () => {
    const indice = new IndiceHexagonos(geo([ponto(filhos[0])]))
    for (const geometry of [
      { type: "Point", coordinates: [-50, -6] },
      { type: "Polygon", coordinates: [[[0, 0], [181, 0], [1, 1], [0, 0]]] },
      { type: "Polygon", coordinates: [[[0, 0], [1, Infinity], [1, 1], [0, 0]]] },
      { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1]]] },
      { type: "Polygon", coordinates: [[[0, 0], [1, 1], [2, 2], [0, 0]]] },
      { type: "Polygon", coordinates: [] },
      { type: "MultiPolygon", coordinates: [] },
    ]) {
      indice.destacarAutorizada(area(filhos[0]))
      expect(() => indice.destacarAutorizada(geo([{ type: "Feature", properties: {}, geometry }]))).toThrow("Área autorizada inválida")
      expect(indice.consultar(mundo, 5).geo.features[0].properties.selecionado).toBe(false)
    }
  })

  it("rejeita duplicatas contraditórias, H3 inválido, números impossíveis e enquadramento inválido", () => {
    expect(() => new IndiceHexagonos(geo([ponto(filhos[0], 8, 10), ponto(filhos[0], 8, null)]))).toThrow("inválidos")
    expect(() => new IndiceHexagonos(geo([ponto(filhos[0], 8, 10), ponto(filhos[0], 9, 10)]))).toThrow("inválidos")
    for (const propriedades of [
      { h3: "850000000000001" }, { h3: pai }, { fazendas: NaN }, { fazendas: -1 }, { fazendas: 5.5 },
      { potencial_ha: Infinity }, { potencial_ha: -1 }, { potencial_ha: undefined },
    ]) {
      const entrada = ponto(filhos[0])
      expect(() => new IndiceHexagonos(geo([{ ...entrada, properties: { ...entrada.properties, ...propriedades } }]))).toThrow("inválidos")
    }
    expect(() => new IndiceHexagonos(geo([ponto(filhos[0], Number.MAX_SAFE_INTEGER), ponto(filhos[1], 5)]))).toThrow("inválidos")
    const vazio = new IndiceHexagonos(null)
    expect(vazio.resumo).toMatchObject({ celulas: 0, fazendas: 0, hectares: null, metrica: "fazendas" })
    expect(vazio.consultar(mundo, 3).hexagonos).toEqual([])
    expect(() => vazio.consultar([0, 10, 1, -10], 3)).toThrow("inválido")
    expect(() => vazio.consultar(mundo, Infinity)).toThrow("inválido")
  })
})
