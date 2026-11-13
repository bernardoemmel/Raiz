import { describe, expect, it } from "vitest"
import { Supercluster } from "@maplibre/geojson-vt"
import { createExpression } from "@maplibre/maplibre-gl-style-spec"
import type { Geo } from "../../../compartilhado/dados"
import { lerGrupo, prepararPontosAgregados } from "./grupos"
import { IndiceGrupos, OPCOES_INDICE_GRUPOS } from "./indice-grupos"
import type { CaixaGrupos } from "./protocolo-grupos"

const h3 = (n: number) => `85${n.toString(16).padStart(13, "0")}`
const ponto = (n: number, lon: number, lat: number, fazendas = 5, ha: number | null = 10): Geo["features"][number] => ({
  type: "Feature", geometry: { type: "Point", coordinates: [lon, lat] },
  properties: { h3: h3(n), fazendas, potencial_ha: ha, cod_imovel: "NAO-PUBLICAR", nome: "NAO-PUBLICAR" },
})
const geo = (features: Geo["features"]): Geo => ({ type: "FeatureCollection", features })

/** Reprodução independente das expressões e opções que GeoJSONSource entrega ao mesmo fork. */
function indiceDoMapLibre(dados: Geo) {
  const ha = ["coalesce", ["get", "potencial_ha"], 0]
  const com = ["case", [">", ha, 0], 1, 0]
  const expressoes = { fazendas: ["get", "fazendas"], ha_conhecidos: ha, com_medida: com, sem_medida: ["-", 1, com] }
  const campos = Object.entries(expressoes).map(([nome, valor]) => {
    const e = createExpression(valor, `sources.agregados.clusterProperties.${nome}`)
    if (e.result !== "success") throw new Error("Expressão de comparação inválida.")
    return { nome, e: e.value }
  })
  const indice = new Supercluster({ maxZoom: 11, minPoints: 2, extent: 8192, radius: 112 * (8192 / 512),
    map: p => Object.fromEntries(campos.map(({ nome, e }) => [nome, e.evaluate({ zoom: 0 }, { type: 1, properties: p ?? {} })])),
    reduce: (a, b) => { for (const { nome } of campos) a[nome] = Number(a[nome]) + Number(b[nome]) },
  })
  indice.load(prepararPontosAgregados(dados).features as never)
  return indice
}

describe("índice público mantido no worker", () => {
  it("preserva clusters, centros, IDs, somas e expansão do mesmo índice usado pelo MapLibre", () => {
    const dados = geo(Array.from({ length: 80 }, (_, n) => ponto(n, -55 + (n % 10) * 0.7, -12 + Math.floor(n / 10) * 0.5, 5 + n, n % 3 ? n / 10 : null)))
    dados.features.push(dados.features[0], ponto(90, -55, -12, 4))
    const novo = new IndiceGrupos(dados), anterior = indiceDoMapLibre(dados)
    const caixas: CaixaGrupos[] = [[-75, -35, -34, 6], [-53, -11, -49, -8], [-51.01, -10.01, -50.99, -9.99]]
    for (const bbox of caixas) for (const zoom of [0, 2.2, 3, 5, 8, 10, 11.9]) {
      const esperado = anterior.getClusters(bbox, Math.floor(zoom)).map(lerGrupo).filter(g => g !== null).sort((a, b) => b.fazendas - a.fazendas)
      const grupos = novo.consultar(bbox, zoom)
      expect(grupos).toEqual(esperado)
      for (const grupo of grupos) if (grupo.cluster !== undefined)
        expect(novo.aproximar(grupo.cluster)).toBe(anterior.getClusterExpansionZoom(grupo.cluster))
    }
    expect(OPCOES_INDICE_GRUPOS.radius / OPCOES_INDICE_GRUPOS.extent).toBe(112 / 512)
  })

  it("mantém nós individuais e grupos sem medida, sem propriedades privadas no retorno", () => {
    const indice = new IndiceGrupos(geo([ponto(1, -50, -6, 5, null), ponto(2, -50.0001, -6, 8, null), ponto(3, -40, -6, 7, 0.0005)]))
    const grupos = indice.consultar([-70, -30, -30, 10], 4)
    expect(grupos).toHaveLength(2)
    expect(grupos[0]).toMatchObject({ fazendas: 13, hectares: null, semMedida: 2 })
    expect(grupos[1]).toMatchObject({ chave: h3(3), fazendas: 7, hectares: 0.0005, semMedida: 0 })
    const texto = JSON.stringify(grupos)
    for (const proibido of ["NAO-PUBLICAR", "cod_imovel", "nome", "properties", "geometry", "features"]) expect(texto).not.toContain(proibido)
    expect(indice.consultar([-70, -30, -30, 10], 12)).toEqual([])
  })

  it("soma fazendas, não células, e conserva hectares parcialmente conhecidos", () => {
    const indice = new IndiceGrupos(geo([ponto(1, -50, -6, 5, 10), ponto(2, -50.01, -6, 8, null)]))
    expect(indice.consultar([-70, -30, -30, 10], 3)).toMatchObject([{ fazendas: 13, hectares: 10, semMedida: 1 }])
  })

  it("trata antimeridiano, cópias do mundo e caixas maiores que um mundo sem duplicar grupos", () => {
    const dados = geo([ponto(1, 179, 0), ponto(2, -179, 0), ponto(3, 0, 0)])
    const indice = new IndiceGrupos(dados)
    const lesteOeste = indice.consultar([170, -5, -170, 5], 11)
    expect(new Set(lesteOeste.map(g => g.chave))).toEqual(new Set([h3(1), h3(2)]))
    expect(indice.consultar([170, -5, 190, 5], 11)).toEqual(lesteOeste)
    expect(indice.consultar([530, -5, 550, 5], 11)).toEqual(lesteOeste)
    const todos = indice.consultar([-540, -90, 540, 90], 11)
    expect(todos).toHaveLength(3)
    expect(new Set(todos.map(g => g.chave)).size).toBe(3)
    // Um centro no limite pertence à consulta; a margem visual é fornecida pelo mapa.
    const centro = todos.find(g => g.chave === h3(3))!.centro
    expect(indice.consultar([centro[0], centro[1], centro[0], centro[1]], 11).map(g => g.chave)).toContain(h3(3))
  })

  it("aceita índice vazio e rejeita geometria ou chave que não pertence ao agregado público", () => {
    expect(new IndiceGrupos(null).consultar([-180, -90, 180, 90], 3)).toEqual([])
    expect(() => new IndiceGrupos(geo([{ ...ponto(1, 0, 0), properties: { h3: "nome de pessoa", fazendas: 5 } }]))).toThrow("inválidos")
    expect(() => new IndiceGrupos(geo([ponto(1, Infinity, 0)]))).toThrow("inválidos")
    expect(() => new IndiceGrupos(geo([])).consultar([0, 10, 1, -10], 3)).toThrow("inválido")
  })
})
