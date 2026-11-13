import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { afterEach, describe, expect, it, vi } from "vitest"
import { compararCobertura, registrarNovosMunicipios } from "../../scripts/comparar-cobertura.mjs"
import { fonteAmostra } from "../dados/fonte-amostra"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { PainelCobertura } from "../../globo/src/partes/PainelCobertura"

const indice = (com: string[], sem: string[] = [], gerado_em = "2026-11-13T10:41:00Z") => ({ cobertura: { gerado_em, dados_publicados_em: gerado_em, com_desenho: com, sem_desenho: sem, acesso: "aberto" as const } })
afterEach(() => vi.unstubAllGlobals())

describe("municípios novos desde a publicação anterior", () => {
  it("conta códigos adicionados; obter o desenho de um município conhecido não o torna novo", () => {
    const antes = indice(["1505536", "5200050"], ["1502772"], "2026-11-12T10:41:00Z")
    const atual = indice(["1505536", "1502772", "4300034"], ["1502772"])
    const c = compararCobertura(atual, antes)
    expect(c).toEqual({ anterior_em: antes.cobertura.gerado_em, atual_em: atual.cobertura.gerado_em, municipios: ["4300034"] })
    const html = renderToStaticMarkup(createElement(PainelCobertura, { cobertura: { ...atual.cobertura, novos_desde: c } }))
    expect(html).toContain("1 município novo")
    expect(html).toContain('dateTime="2026-11-12T10:41:00Z"')
    expect(renderToStaticMarkup(createElement(PainelCobertura, { cobertura: { ...atual.cobertura, novos_desde: c }, uf: "PA" }))).toContain("0 municípios novos")
  })
  it("mantém desconhecido sem snapshot anterior válido, sem usar o total como novos", () => {
    const atual = indice(["1505536", "1502772"])
    for (const anterior of [null, {}, indice([], [], "data inválida"), indice([], [], "2027-01-01T00:00:00Z"), { cobertura: { ...atual.cobertura, com_desenho: [1505536] } }]) expect(compararCobertura(atual, anterior)).toBeNull()
    const html = renderToStaticMarkup(createElement(PainelCobertura, { cobertura: atual.cobertura }))
    expect(html).toContain("comparação com a publicação anterior ainda não está disponível")
    expect(html).not.toContain("2 municípios novos")
  })
  it("consulta o último site publicado e grava somente a diferença e suas datas", async () => {
    const site = fs.mkdtempSync(path.join(os.tmpdir(), "raiz-cobertura-"))
    try {
      fs.mkdirSync(path.join(site, "geo"))
      const arquivo = path.join(site, "geo/indice.json")
      const atual = indice(["1505536", "1502772"])
      fs.writeFileSync(arquivo, JSON.stringify(atual))
      const buscar = vi.fn(async () => new Response(JSON.stringify(indice(["1505536"], [], "2026-11-12T10:41:00Z")), { headers: { "content-type": "application/json" } }))
      await registrarNovosMunicipios({ site, siteUrl: "https://raiz.example/", buscar })
      expect(String(buscar.mock.calls[0][0])).toBe("https://raiz.example/geo/indice.json")
      expect(JSON.parse(fs.readFileSync(arquivo, "utf8")).cobertura.novos_desde.municipios).toEqual(["1502772"])
      await registrarNovosMunicipios({ site, siteUrl: "https://raiz.example/", buscar: async () => new Response("", { status: 404 }) })
      expect(JSON.parse(fs.readFileSync(arquivo, "utf8")).cobertura.novos_desde).toBeNull()
    } finally { fs.rmSync(site, { recursive: true, force: true }) }
  })
})

describe("fundo e estados antes dos limites municipais", () => {
  it("não consulta arquivos inexistentes ao escolher um estado ou município ainda sem dados", async () => {
    const pedidos: string[] = []
    vi.stubGlobal("fetch", async (url: string) => {
      pedidos.push(url)
      expect(url).toBe("/amostra/estados.json")
      return new Response(JSON.stringify({ acesso: "publico_basico", estados: [
        { uf: "AM", situacao: "sem_dados", com_lista: [] },
        { uf: "PA", situacao: "incompleto", com_lista: ["1505536"] },
      ] }), { headers: { "content-type": "application/json" } })
    })
    const fonte = fonteAmostra("/")
    expect(await fonte.pontos("AM")).toEqual([])
    expect(await fonte.basicos?.("1302603")).toBeNull()
    expect(await fonte.basicos?.("1501402")).toBeNull()
    expect(pedidos).toEqual(["/amostra/estados.json"])
  })
  it("não baixa o GeoJSON nacional de municípios na entrada e reutiliza os estados ao aproximar", async () => {
    const pedidos: string[] = []
    const geo = { type: "FeatureCollection", features: [] }
    vi.stubGlobal("location", { href: "https://raiz.example/" })
    vi.stubGlobal("fetch", async (url: string) => {
      pedidos.push(url)
      const json = url.endsWith("indice.json") ? { municipios: {}, brasil: { base: { arquivo: "base_brasil.pmtiles" }, estados: { arquivo: "brasil_estados.geojson" }, municipios: { arquivo: "brasil_municipios.geojson" } } } : geo
      return new Response(JSON.stringify(json), { headers: { "content-type": "application/json" } })
    })
    const fonte = fonteAmostra("/")
    const inicial = await fonte.geo.brasil({ municipios: false })
    expect(inicial.base).toBe("https://raiz.example/geo/base_brasil.pmtiles")
    expect(inicial.municipios).toBeNull()
    expect(pedidos).toEqual(["/geo/indice.json", "/geo/brasil_estados.geojson"])
    await fonte.geo.brasil()
    expect(pedidos).toEqual(["/geo/indice.json", "/geo/brasil_estados.geojson", "/geo/brasil_municipios.geojson"])
  })
})
