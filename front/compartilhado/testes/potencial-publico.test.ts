import { describe, expect, it } from "vitest"
import { gzipSync } from "node:zlib"
import { polygonToCells } from "../../globo/node_modules/h3-js"
import { LIMITE_AGREGADOS_GZIP, LIMITE_AGREGADOS_NORMAL } from "../dados/agregados"
import { projetarAgregados, projetarPotencial } from "../potencial-publico"

const exemplo = () => ({ type: "FeatureCollection", metadados: {
  contrato: "potencial_h3", versao: 1, resolucao: 5, minimo_contribuintes: 5,
  metodo: "ponto_interior_estatistico", cobertura: "parcial", atualizado_em: "2026-11-13T01:00:00Z",
  fonte: "FONTE-PRIVADA", aviso: "AVISO-PRIVADO", contagens: { incluidas: 5, nomes: ["NOME-PRIVADO"] },
}, features: [{ type: "Feature", properties: { h3: "8581b16bfffffff", potencial_ha: 10.5, fazendas: 5,
  cod_imovel: "CAR-PRIVADO", credito_p50: 500 }, geometry: { type: "Polygon", coordinates: [[[1, 1], [2, 1], [1, 1]]] } }] })

describe("projeção aberta do potencial H3", () => {
  it("reconstrói o hexágono e não repassa campos pagos nem textos da entrada", () => {
    const p = projetarPotencial(exemplo())
    expect(p.features[0].properties).toEqual({ h3: "8581b16bfffffff", potencial_ha: 10.5, fazendas: 5 })
    expect(p.features[0].geometry.coordinates[0].length).toBeGreaterThanOrEqual(6)
    expect(p.features[0].geometry.coordinates[0][0]).not.toEqual([1, 1])
    expect(JSON.stringify(p)).not.toMatch(/PRIVAD|cod_imovel|credito_p50/)
    expect(p.metadados.dominio_ha).toEqual([0, 100, 1000, 10000, 50000])
  })
  it("mantém desconhecido como null e recusa célula pequena, repetida ou outra resolução", () => {
    const p = exemplo()
    p.features[0].properties.potencial_ha = null as unknown as number
    expect(projetarPotencial(p).features[0].properties.potencial_ha).toBeNull()
    p.features[0].properties.fazendas = 4
    expect(() => projetarPotencial(p)).toThrow("contrato anônimo")
    p.features[0].properties.fazendas = 5
    p.features.push(p.features[0])
    expect(() => projetarPotencial(p)).toThrow("contrato anônimo")
    const q = exemplo()
    q.features[0].properties.h3 = "CAR-PRIVADO"
    expect(() => projetarPotencial(q)).toThrow("contrato anônimo")
  })
})

describe("agregado nacional com o Brasil inteiro", () => {
  it("34 mil células, o máximo geográfico, cabem nos limites sem cortar nenhuma", () => {
    const base = exemplo()
    const celulas = polygonToCells([[-5, -74], [-5, -34], [-34, -34], [-34, -74], [-5, -74]], 5).slice(0, 34_000)
    expect(celulas.length).toBe(34_000)
    const porUf = [celulas.slice(0, 17_000), celulas.slice(17_000)]
    const colecoes = porUf.map(lista => ({ ...base, features: lista.map((h3, i) => ({ type: "Feature",
      properties: { h3, potencial_ha: i % 7 === 0 ? null : 1234.5678 + i, fazendas: 5 + (i % 400) }, geometry: { type: "Point", coordinates: [0, 0] } })) }))
    const nacional = projetarAgregados(colecoes.map(projetarPotencial))!
    expect(nacional.features).toHaveLength(34_000)
    const normal = Buffer.from(JSON.stringify(nacional))
    expect(normal.length).toBeLessThan(LIMITE_AGREGADOS_NORMAL)
    expect(gzipSync(normal, { level: 6 }).length).toBeLessThan(LIMITE_AGREGADOS_GZIP)
    // o centro tem 3 casas e os hectares 1; o h3 segue inteiro
    const f = nacional.features.find(x => x.properties.potencial_ha !== null)!
    expect(String(f.geometry.coordinates[0]).split(".")[1]?.length ?? 0).toBeLessThanOrEqual(3)
    expect(Number.isInteger(f.properties.potencial_ha! * 10)).toBe(true)
  }, 120_000)
})
