import { describe, expect, it } from "vitest"
import { projetarPotencial } from "../potencial-publico"

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
