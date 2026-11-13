import { describe, expect, it } from "vitest"
import { createExpression } from "@maplibre/maplibre-gl-style-spec"
import { Supercluster } from "@maplibre/geojson-vt"
import type { Geo } from "../../../compartilhado/dados"
import { camadasGrupos, descreverGrupo, fonteGrupos, lerGrupo, prepararPontosAgregados, raioGrupo, rotulosGrupo, urlAgregadosPublica } from "./grupos"

const ponto = (h3: string, fazendas: number, ha: number | null, lon = -50): Geo["features"][number] => ({
  type: "Feature", geometry: { type: "Point", coordinates: [lon, -6] }, properties: { h3, fazendas, potencial_ha: ha, cod_imovel: "NAO-PUBLICAR" },
})

describe("grupos públicos do mapa", () => {
  it("conta fazendas do agregado, não pontos, e preserva medida ausente no Supercluster", () => {
    const geo = prepararPontosAgregados({ type: "FeatureCollection", features: [ponto("a", 5, 10), ponto("b", 8, null, -50.01), ponto("a", 5, 10)] })
    expect(geo.features).toHaveLength(2)
    expect(geo.features.some(f => "cod_imovel" in f.properties)).toBe(false)
    const propriedades = fonteGrupos().clusterProperties ?? {}
    const campos = Object.keys(propriedades)
    const mapeamento = Object.entries(propriedades).map(([nome, [, expr]]) => {
      const compilada = createExpression(expr, `sources.agregados.clusterProperties.${nome}`)
      if (compilada.result !== "success") throw new Error(`Expressão inválida: ${nome}`)
      return { nome, expr: compilada.value }
    })
    const indice = new Supercluster({ maxZoom: 11, radius: 112,
      map: p => Object.fromEntries(mapeamento.map(c => [c.nome, c.expr.evaluate({ zoom: 0 }, { type: 1, properties: p ?? {} })])),
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
    expect(lerGrupo({ geometry: { type: "Point", coordinates: [-50, -6] }, properties: null })).toBeNull()
    const geo = prepararPontosAgregados({ type: "FeatureCollection", features: [ponto("a", 5, null), ponto("b", 4, 10)] })
    expect(geo.features).toHaveLength(1)
    const grupo = lerGrupo(geo.features[0])!
    expect(grupo.hectares).toBeNull()
    expect(descreverGrupo(grupo)).toContain("hectares não informados")
  })

  it("formata os rótulos realmente mostrados nos botões, inclusive medidas pequenas e ausentes", () => {
    const grupo = lerGrupo(ponto("a", 415575, 596074.0744))!
    expect(rotulosGrupo(grupo)).toEqual(["415.575", "596.074 ha"])
    expect(rotulosGrupo(lerGrupo(ponto("b", 5, 0.0005))!)).toEqual(["5", "<0,1 ha"])
    expect(rotulosGrupo(lerGrupo(ponto("c", 5, null))!)).toEqual(["5", "Sem medida"])
    expect(raioGrupo(grupo)).toBe(56)
    expect(raioGrupo({ ...grupo, fazendas: 10000 })).toBe(50)
    expect(raioGrupo({ ...grupo, fazendas: 5 })).toBe(44)
  })

  it("mantém a consulta espacial sem compilar o programa gráfico dos círculos", () => {
    const [camada] = camadasGrupos()
    expect(camada.type).toBe("circle")
    if (camada.type !== "circle") throw new Error("A consulta precisa de uma camada circle")
    expect(camada.paint?.["circle-opacity"]).toBe(0)
    expect(camada.paint?.["circle-stroke-opacity"]).toBe(0)
    expect(camada.layout?.visibility).not.toBe("none")
    expect(camada.maxzoom).toBe(12)
  })

  it("não arredonda uma área positiva pequena para zero", () => {
    const geo = prepararPontosAgregados({ type: "FeatureCollection", features: [ponto("a", 5, 0.0005)] })
    expect(descreverGrupo(lerGrupo(geo.features[0])!)).toContain("menos de 0,1 ha")
  })

  it("entrega ao worker somente o arquivo público da publicação atual", () => {
    const esperado = "https://raiz.example/Raiz/geo/agregados_brasil.geojson"
    expect(urlAgregadosPublica(esperado, esperado)).toBe(esperado)
    expect(urlAgregadosPublica("agregados_brasil.geojson", esperado)).toBe(esperado)
    for (const url of ["https://outro.example/geo/agregados_brasil.geojson", "/api/privado", `${esperado}?token=exemplo`, "javascript:alert(1)", "https://usuario:senha@raiz.example/Raiz/geo/agregados_brasil.geojson"])
      expect(urlAgregadosPublica(url, esperado)).toBeNull()
  })
})
