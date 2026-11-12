import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { gunzipSync } from "node:zlib"
import { afterAll, describe, expect, it } from "vitest"
import { abrirPasta } from "../pasta-dados"
import { dadosRaiz } from "../vite-dados"
import { lerCsv } from "../dados/csv"
import { fonteAmostra } from "../dados/fonte-amostra"

const repo = fs.mkdtempSync(path.join(os.tmpdir(), "raiz-publicacao-"))
const dados = path.join(repo, "dados", "amostra")
const geo = path.join(repo, "front", "geo")
const saida = path.join(repo, "site")
fs.mkdirSync(dados, { recursive: true })
fs.mkdirSync(geo, { recursive: true })
fs.mkdirSync(saida, { recursive: true })
afterAll(() => fs.rmSync(repo, { recursive: true, force: true }))

const car = "PA-1504950-ABCDEF"
fs.writeFileSync(path.join(dados, "resumo_PA.csv"), `cod_ibge,municipio,imoveis,aptas_carbono,ha_carbono,cod_imovel,observacao\n1504950,Cumaru do Norte,6,6,60,${car},informacao_individual\n1507300,São Félix do Xingu,3,3,30,${car},informacao_individual\n`)
fs.writeFileSync(path.join(dados, "imoveis_1504950.csv"), "cod_imovel,ha,carbono_ha,problema,desm_pos2016_ha\n" + Array.from({ length: 6 }, (_, k) => `${car}${k},10,10,false,0\n`).join(""))
const contorno = (x: number, y: number) => ({ type: "Polygon", coordinates: [[[x, y], [x + 1, y], [x + 1, y + 1], [x, y + 1], [x, y]]] })
const colecao = (features: unknown[]) => JSON.stringify({ type: "FeatureCollection", features })
fs.writeFileSync(path.join(geo, "brasil_municipios.geojson"), colecao([{ type: "Feature", properties: { cod_ibge: "1504950", nome: "Cumaru do Norte", uf: "PA" }, geometry: contorno(-52, -8) }]))
fs.writeFileSync(path.join(geo, "municipio_1504950.geojson"), fs.readFileSync(path.join(geo, "brasil_municipios.geojson")))
fs.writeFileSync(path.join(geo, "imoveis_1504950.geojson"), colecao(Array.from({ length: 6 }, (_, k) => (
  { type: "Feature", properties: { cod_imovel: car + k }, geometry: contorno(-51.95 + k * 0.005, -7.95 + k * 0.005) }
))))
fs.writeFileSync(path.join(geo, "camadas_1504950.pmtiles"), car)
fs.writeFileSync(path.join(geo, "base_brasil.pmtiles"), "mapa_base")

function conectar(plugin: ReturnType<typeof dadosRaiz>) {
  let chamada: (req: unknown, res: unknown, next: () => void) => void
  plugin.configureServer({ middlewares: { use: (fn: typeof chamada) => { chamada = fn } } } as never)
  return (url: string) => new Promise<{ status: number; corpo: string }>((resolve) => {
    const res = { statusCode: 200, setHeader() {}, end(dado: string | Buffer = "") { resolve({ status: this.statusCode, corpo: dado.toString() }) } }
    chamada({ url, headers: {} }, res, () => resolve({ status: 404, corpo: "" }))
  })
}

describe("site aberto somente agregado", () => {
  it("o navegador não tenta reconstruir ficha a partir de CSV na publicação aberta", async () => {
    const original = globalThis.fetch
    const urls: string[] = []
    globalThis.fetch = (async (url: string | URL | Request) => {
      urls.push(String(url))
      return new Response(JSON.stringify({ acesso: "agregado", estados: [] }), { headers: { "content-type": "application/json" } })
    }) as typeof fetch
    try {
      const fonte = fonteAmostra("/publico/")
      expect(await fonte.ficha(car)).toBeNull()
      expect(await fonte.imoveis("1504950")).toBeNull()
      expect(await fonte.imovel(car)).toBeNull()
      expect(await fonte.certidoes(car)).toEqual([])
      expect(urls).toEqual(["/publico/amostra/estados.json"])
    } finally {
      globalThis.fetch = original
    }
  })
  it("recusa embutir o token operacional num build, inclusive quando vem do .env Vite", () => {
    const plugin = dadosRaiz({ repo, raizDados: null })
    for (const chave of ["VITE_RAIZ_TOKEN", "VITE_RAIZ_API_TOKEN"])
      expect(() => plugin.configResolved({ root: repo, command: "build", build: { outDir: "site" }, env: { [chave]: "credencial_de_teste" } })).toThrow("não podem entrar no site")
  })

  it("agrupa no centro do município mesmo quando conhece o contorno de cada fazenda", async () => {
    const pasta = abrirPasta({ repo, raizDados: null })
    const privado = (await pasta.pontos("PA"))!
    expect(privado.pontos).toHaveLength(6)
    const publico = (await pasta.pontosPublicos("PA"))!
    expect(publico.pontos).toHaveLength(1)
    expect(publico.pontos[0].slice(2)).toEqual(["pendencia", 60, "1504950", 6])
    expect(privado.pontos.some((p) => p[0] === publico.pontos[0][0] && p[1] === publico.pontos[0][1])).toBe(false)
    expect(publico.suprimidos).toBe(true)
    expect(publico.fazendas).toBeNull()
    expect(publico.sem_lugar).toBeNull()
  })

  it("bloqueia acesso direto a dados de origem e mantém a busca por município", async () => {
    const servir = conectar(dadosRaiz({ repo, raizDados: null }))
    for (const url of [
      `/@fs/${dados}/imoveis_1504950.csv`, "/dados/amostra/imoveis_1504950.csv", "/front/geo/imoveis_1504950.geojson",
      "/geo/camadas_1504950.pmtiles", "/amostra/imoveis_1504950.csv", "/amostra/imoveis_1504950.csv.gz",
      `/amostra/fichas/${car}.json`, "/amostra/car_PA.json",
    ]) expect((await servir(url)).status, url).toBe(404)
    const resumo = await servir("/amostra/resumo_PA.csv")
    expect(resumo.status).toBe(200)
    expect(resumo.corpo).not.toContain(car)
    expect(resumo.corpo).not.toContain("informacao_individual")
    const pequena = lerCsv(resumo.corpo).linhas.find((l) => l.cod_ibge === "1507300")!
    expect(pequena.dados_suprimidos).toBe("true")
    expect(pequena.imoveis).toBe("")
    expect(pequena.ha_carbono).toBe("")
    expect(JSON.parse((await servir("/busca?q=Cumaru")).corpo).municipios).toHaveLength(1)
    expect(JSON.parse((await servir("/busca?q=São Félix")).corpo).municipios[0].imoveis).toBeNull()
    expect(JSON.parse((await servir(`/busca?q=${car}`)).corpo).imoveis).toEqual([])
  })

  it("build remove sobras individuais e não publica CAR, ficha ou camada por fazenda", async () => {
    const anterior = process.env.RAIZ_BUILD_DADOS
    process.env.RAIZ_BUILD_DADOS = "1"
    try {
      fs.mkdirSync(path.join(saida, "amostra", "fichas"), { recursive: true })
      fs.writeFileSync(path.join(saida, "amostra", "fichas", "antiga.json"), car)
      const plugin = dadosRaiz({ repo, raizDados: null })
      plugin.configResolved({ root: repo, command: "build", build: { outDir: "site" } })
      await plugin.closeBundle()
      const publicados = fs.readdirSync(path.join(saida, "amostra"))
      expect(publicados).toEqual(expect.arrayContaining(["estados.json", "indice_PA.json", "pontos_PA.json", "resumo_PA.csv.gz"]))
      expect(publicados.some((p) => /^(fichas|car_|imoveis_|extras_|filtros_)/.test(p))).toBe(false)
      const texto = gunzipSync(fs.readFileSync(path.join(saida, "amostra", "resumo_PA.csv.gz"))).toString()
      expect(texto).not.toContain(car)
      expect(texto).not.toContain("informacao_individual")
      expect(fs.readdirSync(path.join(saida, "geo"))).toEqual(expect.arrayContaining(["base_brasil.pmtiles", "brasil_municipios.geojson", "municipio_1504950.geojson", "indice.json"]))
      expect(fs.existsSync(path.join(saida, "geo", "imoveis_1504950.geojson"))).toBe(false)
      expect(fs.existsSync(path.join(saida, "geo", "camadas_1504950.pmtiles"))).toBe(false)
      const indice = JSON.parse(fs.readFileSync(path.join(saida, "geo", "indice.json"), "utf8"))
      expect(indice.municipios["1504950"].imoveis).toBeUndefined()
      const estados = JSON.parse(fs.readFileSync(path.join(saida, "amostra", "estados.json"), "utf8"))
      expect(estados.acesso).toBe("agregado")
      expect(estados.estados.every((e: { com_lista: string[] }) => !e.com_lista.length)).toBe(true)
      const markdown = fs.readFileSync(path.join(saida, "dados/municipios/1507300.md"), "utf8")
      expect(markdown).toContain("| Imóveis analisados | Suprimido |")
      expect(markdown).not.toContain(car)
      expect(fs.readFileSync(path.join(saida, "dados/estados/PA.md"), "utf8")).not.toContain("imoveis_1504950.csv")
    } finally {
      if (anterior === undefined) delete process.env.RAIZ_BUILD_DADOS
      else process.env.RAIZ_BUILD_DADOS = anterior
    }
  })
})
