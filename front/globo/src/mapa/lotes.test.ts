import { describe, expect, it } from "vitest"
import type { Geo } from "../../../compartilhado/dados"
import { coordenadaValida, geometriasDosLotes, limitesDoLote, type FazendaNoMapa } from "./lotes"

const fazenda: FazendaNoMapa = { cod_imovel: "CAR-1", cod_ibge: "1505536", lon: -49.9, lat: -6.1, papel: "lote", interesse: "sem_contato" }
const geo: Geo = { type: "FeatureCollection", features: [{ type: "Feature", properties: { cod_imovel: "CAR-1", nome: "não deve passar para o mapa" }, geometry: { type: "Polygon", coordinates: [[[-50, -6], [-49, -6], [-49, -7], [-50, -6]]] } }] }

describe("desenho das alternativas de lote", () => {
  it("preserva a mesma fazenda em alternativas diferentes com identificadores próprios", () => {
    const desenho = geometriasDosLotes([geo, geo], [{ ...fazenda, opcao: "barata" }, { ...fazenda, opcao: "compacta" }])
    expect(desenho.features).toHaveLength(2)
    expect(desenho.features.map((f) => f.properties.id)).toEqual(["barata:CAR-1", "compacta:CAR-1"])
    expect(desenho.features.map((f) => f.properties.opcao)).toEqual(["barata", "compacta"])
    expect(desenho.features[0].geometry).toEqual(geo.features[0].geometry)
    expect(desenho.features[0].properties).not.toHaveProperty("nome")
  })

  it("não cria polígonos para fazenda ausente no desenho publicado", () => {
    expect(geometriasDosLotes([null, geo], [{ ...fazenda, cod_imovel: "CAR-2" }]).features).toEqual([])
  })

  it("rejeita coordenadas desconhecidas ou fora da terra sem deslocar a fazenda", () => {
    expect(coordenadaValida(fazenda)).toBe(true)
    expect(coordenadaValida({ ...fazenda, lon: NaN })).toBe(false)
    expect(coordenadaValida({ ...fazenda, lat: 100 })).toBe(false)
  })

  it("enquadra o contorno inteiro, além do centro da fazenda", () => {
    expect(limitesDoLote(geo, [fazenda])).toEqual([-50, -7, -49, -6])
    expect(limitesDoLote({ type: "FeatureCollection", features: [] }, [])).toBeNull()
  })
})
