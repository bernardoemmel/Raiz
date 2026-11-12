import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { gzipSync } from "node:zlib"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { fonteAmostra } from "../dados/fonte-amostra"
import { dadosRaiz } from "../vite-dados"
import { abrirPasta } from "../pasta-dados"

const MUNICIPIOS = ["1504208", "1505536"]
const CARS = [
  "PA-1504208-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
  "PA-1504208-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
  "PA-1505536-CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC",
]
const poligono = (car: string, lon: number) => ({
  type: "Feature",
  properties: { cod_imovel: car },
  geometry: { type: "Polygon", coordinates: [[[lon, -6], [lon + 0.01, -6], [lon + 0.01, -5.99], [lon, -6]]] },
})

describe("build estático com geometrias comprimidas", () => {
  let repo: string
  let geo: string
  beforeEach(() => {
    repo = fs.mkdtempSync(path.join(os.tmpdir(), "raiz-build-estatico-"))
    geo = path.join(repo, "geo-publicado")
    fs.mkdirSync(geo)
    const dados = path.join(repo, "dados", "PA")
    fs.mkdirSync(dados, { recursive: true })
    fs.writeFileSync(path.join(dados, "resumo_PA.csv"), "cod_ibge,municipio,imoveis\n1504208,Marabá,2\n1505536,Parauapebas,1\n")
    const municipios: Record<string, unknown> = {}
    MUNICIPIOS.forEach((cod, n) => {
      const cars = CARS.filter((car) => car.includes(cod))
      fs.writeFileSync(path.join(dados, `imoveis_${cod}.csv`),
        "cod_imovel,cod_municipio_ibge,municipio,uf,ha,carbono_ha,f_matricula\n" +
        cars.map((car) => `${car},${cod},${n ? "Parauapebas" : "Marabá"},PA,10,4,1\n`).join(""))
      const arquivo = `imoveis_${cod}.geojson.gz`
      const formas = { type: "FeatureCollection", features: cars.map((car, k) => poligono(car, -50 + n + k * 0.02)) }
      fs.writeFileSync(path.join(geo, arquivo), gzipSync(JSON.stringify(formas)))
      // O arquivo antigo e o cache existem, mas não podem substituir o gzip ou aumentar o site.
      fs.writeFileSync(path.join(geo, `imoveis_${cod}.geojson`), '{"type":"FeatureCollection","features":[]}')
      municipios[cod] = { imoveis: { arquivo, bytes: fs.statSync(path.join(geo, arquivo)).size }, base: { arquivo: "base_PA.pmtiles", bytes: 10 } }
    })
    fs.writeFileSync(path.join(geo, "base_PA.pmtiles"), "base-teste")
    fs.writeFileSync(path.join(geo, "base_antiga.pmtiles"), "cache antigo")
    fs.writeFileSync(path.join(geo, "exportacao.tmp"), "temporário")
    fs.mkdirSync(path.join(geo, "cache"))
    fs.writeFileSync(path.join(geo, "cache", "fonte.parquet"), "cache de download")
    fs.writeFileSync(path.join(geo, "indice.json"), JSON.stringify({ municipios }))
    vi.stubEnv("RAIZ_GEO", "geo-publicado")
    vi.stubEnv("RAIZ_BUILD_DADOS", "1")
    vi.spyOn(console, "log").mockImplementation(() => {})
  })
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
    fs.rmSync(repo, { recursive: true, force: true })
  })

  async function construir(limite: number) {
    vi.stubEnv("RAIZ_FICHAS_LIMITE", String(limite))
    const plugin = dadosRaiz({ repo, raizDados: "dados" })
    const saida = path.join(repo, "dist")
    fs.mkdirSync(saida)
    plugin.configResolved({ root: repo, command: "build", build: { outDir: saida } })
    await plugin.closeBundle()
    return saida
  }
  const json = (saida: string, arquivo: string) => JSON.parse(fs.readFileSync(path.join(saida, arquivo), "utf8"))

  it("lê geometrias gzip na origem privada e publica só uma cópia da base compartilhada", async () => {
    const pasta = abrirPasta({ repo, raizDados: "dados", geo })
    expect(pasta.municipio("1504208")?.geo.size).toBe(2)
    expect((await pasta.pontos("PA"))?.pontos).toHaveLength(3)
    const copiar = vi.spyOn(fs, "copyFileSync")
    const saida = await construir(3)
    const pontos = json(saida, "amostra/pontos_PA.json")
    expect(pontos.fazendas).toBeNull()
    expect(pontos.sem_lugar).toBeNull()
    expect(pontos.pontos).toHaveLength(0)
    expect(fs.existsSync(path.join(saida, "amostra/fichas"))).toBe(false)
    expect(fs.readdirSync(path.join(saida, "geo")).sort()).toEqual([
      "base_PA.pmtiles", "indice.json",
    ])
    const indice = json(saida, "geo/indice.json")
    for (const cod of MUNICIPIOS) expect(indice.municipios[cod]).toEqual({ base: { arquivo: "base_PA.pmtiles", bytes: 10 } })
    expect(copiar.mock.calls.filter(([origem]) => String(origem).endsWith("base_PA.pmtiles"))).toHaveLength(1)
  })

  it("não reconstrói fichas no navegador nem pede arquivos individuais ausentes", async () => {
    const saida = await construir(1)
    const pedidos: string[] = []
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      pedidos.push(url)
      const arquivo = path.join(saida, url.replace(/^\/Raiz\//, ""))
      if (!fs.existsSync(arquivo)) throw new Error(`Pedido de arquivo ausente: ${url}`)
      return new Response(fs.readFileSync(arquivo), { headers: { "content-type": url.endsWith(".gz") ? "application/gzip" : "application/json" } })
    }))
    const fonte = fonteAmostra("/Raiz/")
    const pronta = await fonte.ficha(CARS[2])
    expect(pronta).toBeNull()
    expect(pedidos).toEqual(["/Raiz/amostra/estados.json"])
    const calculada = await fonte.ficha(CARS[0])
    expect(calculada).toBeNull()
    expect(pedidos).not.toContain("/Raiz/geo/imoveis_1504208.geojson.gz")
    expect(pedidos).not.toContain(`/Raiz/amostra/fichas/${CARS[0]}.json`)
  })

  it("variável antiga de limite de fichas não reabre a publicação por fazenda", async () => {
    const saida = await construir(0)
    expect(fs.existsSync(path.join(saida, "amostra", "fichas"))).toBe(false)
    expect(json(saida, "amostra/pontos_PA.json").fazendas).toBeNull()
    expect(json(saida, "amostra/estados.json").acesso).toBe("agregado")
  })

  it("publica o aviso de lote ausente como JSON, sem provocar 404 no navegador", async () => {
    const saida = await construir(0)
    const lote = json(saida, "amostra/lote_PA_central_r11.json")
    expect(lote.estado).toBe("ausente")
    expect(lote.base.creditos.p50).toBeNull()
    expect(lote.opcoes).toEqual([])
  })

  it("copia só o resumo dos lotes publicados, sem CAR nem pacotes por fazenda", async () => {
    const lotes = path.join(repo, "dados/lotes")
    fs.mkdirSync(lotes, { recursive: true })
    const resumo = { titulares: 10, reservas: 2, ha_lote: 100, creditos_lote_faixa: { p10: 10, p50: 20, p90: 30 },
      dados_individuais: [{ cod_imovel: CARS[0], nome_dono: "Dado privado de teste" }] }
    fs.writeFileSync(path.join(lotes, "lote_PA_central_r11.json"), JSON.stringify({
      uf: "PA", cenario: "central_r11", resumos: { barata: resumo, segura: resumo, compacta: resumo },
      arquivos: { privado: { url: "https://exemplo.invalid/individual.tar.gz" } },
    }))
    const saida = await construir(0)
    const lote = json(saida, "amostra/lote_PA_central_r11.json")
    expect(lote.estado).toBe("publicado")
    expect(lote.opcoes).toHaveLength(3)
    expect(lote.opcoes[0].creditos).toEqual({ p10: 10, p50: 20, p90: 30 })
    expect(JSON.stringify(lote)).not.toMatch(/Dado privado|cod_imovel|individual.tar.gz|nome_dono/)
  })
})
