import { describe, expect, it } from "vitest"
import { ordenarImoveis } from "../../globo/src/mapa/cartografia"
import { lerPotencialMapa } from "../dados/potencial"
import type { Geo } from "../dados"

const quadrado = (lado: number): Geo["features"][number] => ({ type: "Feature", properties: { cod_imovel: `FICTICIO-${lado}` }, geometry: { type: "Polygon", coordinates: [[[0,0],[lado,0],[lado,lado],[0,lado],[0,0]]] } })

describe("cartografia sem preenchimento por imóvel", () => {
  it("desenha grandes antes das pequenas, preserva geometrias e não publica hectare inferido", () => {
    const pequenas = quadrado(1), grande = quadrado(4), media = quadrado(2)
    const g: Geo = { type: "FeatureCollection", features: [pequenas, grande, media] }
    const antes = structuredClone(g), ordenado = ordenarImoveis(g)
    expect(ordenado.features.map(f => f.properties.cod_imovel)).toEqual(["FICTICIO-4", "FICTICIO-2", "FICTICIO-1"])
    expect(g).toEqual(antes)
    expect(ordenado.features[0].geometry).toEqual(grande.geometry)
    expect(ordenado.features[0].properties).not.toHaveProperty("hectares")
  })
  it("aceita apenas agregados com cinco contribuintes e deduplica célula de fronteira sem somar", () => {
    const hex = quadrado(2)
    const f = { ...hex, properties: { h3: "85814e6bfffffff", fazendas: 5, potencial_ha: 10, cod_imovel: "PRIVADO", tir: 99 } }
    const p = lerPotencialMapa({ type: "FeatureCollection", metadados: { contrato: "potencial_h3", versao: 1, resolucao: 5, minimo_contribuintes: 5, cobertura: "parcial", metodo: "ponto_interior_estatistico" }, features: [f, f, { ...f, properties: { ...f.properties, h3: "85814e6cfffffff", fazendas: 4 } }] })!
    expect(p.geo.features).toHaveLength(1)
    expect(p.geo.features[0].properties).toEqual({ h3: "85814e6bfffffff", fazendas: 5, potencial_ha: 10 })
    expect(JSON.stringify(p)).not.toContain("PRIVADO")
    expect(p.metadados.aviso).toContain("cobertura parcial")
  })
  it("medida ausente permanece desconhecida, sem reconstruir potencial do limite do CAR", () => {
    const f = { ...quadrado(2), properties: { h3: "85814e6bfffffff", fazendas: 7 } }
    expect(lerPotencialMapa({ type: "FeatureCollection", features: [f] })).toBeNull()
    const p = lerPotencialMapa({ type: "FeatureCollection", metadados: { contrato: "potencial_h3", versao: 1, resolucao: 5, minimo_contribuintes: 5, cobertura: "parcial", metodo: "ponto_interior_estatistico" }, features: [f] })!
    expect(p.geo.features[0].properties.potencial_ha).toBeNull()
  })
})
