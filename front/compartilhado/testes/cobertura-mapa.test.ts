import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { afterEach, describe, expect, it, vi } from "vitest"
import { coberturaDoIndice, contarCobertura } from "../dados/cobertura-mapa"
import { fonteAmostra } from "../dados/fonte-amostra"
import { PainelCobertura } from "../../globo/src/partes/PainelCobertura"

describe("cobertura do mapa publicado", () => {
  const indice = {
    gerado_em: "2026-11-12T10:41:00Z",
    dados_publicados_em: "2026-11-11T18:00:00Z",
    municipios: {
      "1505536": { imoveis: { arquivo: "imoveis_1505536.geojson.gz" } },
      "1502772": { imoveis: { arquivo: "imoveis_1502772.geojson.gz" } },
      "5200050": { imoveis: { arquivo: "imoveis_5200050.geojson.gz" } },
      "3100104": {},
    },
    sem_contorno: { "3100104": "ausente" },
  }

  it("distingue municípios processados de desenhos existentes e soma as UFs", () => {
    const cobertura = coberturaDoIndice(indice, (arquivo) => !arquivo.includes("1502772"))
    expect(contarCobertura(cobertura)).toEqual({ municipios: 2, estados: 2, semDesenho: 2 })
    expect(contarCobertura(cobertura, "PA")).toEqual({ municipios: 1, estados: 1, semDesenho: 1 })
    expect(cobertura.com_desenho).toEqual(["1505536", "5200050"])
    expect(cobertura.gerado_em).toBe(indice.gerado_em)
    expect(cobertura.dados_publicados_em).toBe(indice.dados_publicados_em)
  })

  it("não inventa datas nem aceita arquivo de outro município ou caminho privado", () => {
    const cobertura = coberturaDoIndice({ municipios: {
      "1505536": { imoveis: { arquivo: "../dados/imoveis_1505536.geojson.gz" } },
      "1502772": { imoveis: { arquivo: "imoveis_1505536.geojson.gz" } },
    }, gerado_em: "hoje" }, () => true)
    expect(cobertura.com_desenho).toEqual([])
    expect(cobertura.gerado_em).toBeNull()
    expect(cobertura.dados_publicados_em).toBeNull()
  })

  it("explica a cobertura e a diferença entre a data do mapa e a do Release", () => {
    const cobertura = coberturaDoIndice(indice, (arquivo) => !arquivo.includes("1502772"))
    const html = renderToStaticMarkup(createElement(PainelCobertura, { cobertura }))
    expect(html).toContain("2 municípios em 2 estados")
    expect(html).toContain("2 ainda aguardam o desenho")
    expect(html).toContain("Última atualização do mapa")
    expect(html).toContain('dateTime="2026-11-12T10:41:00Z"')
    expect(html).toContain('dateTime="2026-11-11T18:00:00Z"')
    expect(html).toContain("desenhos individuais exigem acesso pago")
  })
})


describe("cobertura leve antes de abrir o mapa detalhado", () => {
  afterEach(() => vi.unstubAllGlobals())
  it("lê a contagem e as datas sem baixar nenhum contorno", async () => {
    const caminhos: string[] = []
    const cobertura = { gerado_em: "2026-11-12T10:41:00Z", dados_publicados_em: "2026-11-11T18:00:00Z", com_desenho: ["1505536"], sem_desenho: [], acesso: "restrito" }
    vi.stubGlobal("fetch", async (url: string) => {
      caminhos.push(url)
      if (url !== "/teste/geo/indice.json") throw new Error("O painel não deve baixar geometria.")
      return new Response(JSON.stringify({ cobertura, municipios: {}, brasil: { municipios: { arquivo: "brasil_municipios.geojson" } } }), { headers: { "Content-Type": "application/json" } })
    })
    const fonte = fonteAmostra("/teste/")
    expect(await fonte.geo.cobertura()).toEqual(cobertura)
    expect(await fonte.geo.cobertura()).toEqual(cobertura)
    expect(caminhos).toEqual(["/teste/geo/indice.json"])
  })
})
