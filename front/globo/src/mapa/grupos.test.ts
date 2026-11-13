import { describe, expect, it } from "vitest"
import { Supercluster } from "@maplibre/geojson-vt"
import type { Geo } from "../../../compartilhado/dados"
import { descreverGrupo, fonteGrupos, lerGrupo, prepararPontosAgregados } from "./grupos"

const ponto = (h3: string, fazendas: number, ha: number | null, lon = -50): Geo["features"][number] => ({
  type: "Feature", geometry: { type: "Point", coordinates: [lon, -6] }, properties: { h3, fazendas, potencial_ha: ha, cod_imovel: "NAO-PUBLICAR" },
})

describe("grupos públicos do mapa", () => {
  it("conta fazendas do agregado, não pontos, e preserva medida ausente no Supercluster", () => {
    const geo = prepararPontosAgregados({ type: "FeatureCollection", features: [ponto("a", 5, 10), ponto("b", 8, null, -50.01), ponto("a", 5, 10)] })
    expect(geo.features).toHaveLength(2)
    expect(geo.features.some(f => "cod_imovel" in f.properties)).toBe(false)
    const campos = Object.keys(fonteGrupos().clusterProperties ?? {})
    const indice = new Supercluster({ maxZoom: 11, radius: 112,
      map: p => Object.fromEntries(campos.map(c => [c, p[c]])),
      reduce: (a, b) => { for (const c of campos) a[c] = Number(a[c]) + Number(b[c]) },
    })
    indice.load(geo.features as never)
    const grupos = indice.getClusters([-74, -34, -34, 6], 3)
    expect(grupos).toHaveLength(1)
    const grupo = lerGrupo(grupos[0])!
    expect(grupo).toMatchObject({ fazendas: 13, hectares: 10, semMedida: 1 })
    expect(descreverGrupo(grupo)).toBe("13 fazendas no agregado, 10 ha conhecidos. Cobertura parcial.")
    expect(indice.getLeaves(grupo.cluster!, 10)).toHaveLength(2)
  })

  it("não apresenta a identidade zero da soma como hectares conhecidos", () => {
    const geo = prepararPontosAgregados({ type: "FeatureCollection", features: [ponto("a", 5, null), ponto("b", 4, 10)] })
    expect(geo.features).toHaveLength(1)
    const grupo = lerGrupo(geo.features[0])!
    expect(grupo.hectares).toBeNull()
    expect(descreverGrupo(grupo)).toContain("hectares não informados")
  })

  it("não arredonda uma área positiva pequena para zero", () => {
    const geo = prepararPontosAgregados({ type: "FeatureCollection", features: [ponto("a", 5, 0.0005)] })
    expect(descreverGrupo(lerGrupo(geo.features[0])!)).toContain("menos de 0,1 ha")
  })
})
