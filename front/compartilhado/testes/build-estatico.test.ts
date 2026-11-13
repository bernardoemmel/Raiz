import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { gunzipSync, gzipSync } from "node:zlib"
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
    fs.writeFileSync(path.join(geo, "indice.json"), JSON.stringify({ municipios, gerado_em: "2026-11-12T10:41:00Z", dados_publicados_em: "2026-11-11T18:00:00Z" }))
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
    expect(indice.cobertura).toEqual({
      gerado_em: "2026-11-12T10:41:00Z", dados_publicados_em: "2026-11-11T18:00:00Z",
      com_desenho: MUNICIPIOS, sem_desenho: [], acesso: "restrito",
    })
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

  it("pacote público novo publica só situação básica e geometria sanitizada, nunca ficha ou medidas", async () => {
    fs.writeFileSync(path.join(repo, "dados", "estados.json"), JSON.stringify({
      escopo: "publico_basico", versao_publicacao: 1,
      estados: { PA: { escopo: "publico_basico", versao_publicacao: 1, municipios: 2, total_ibge: 144, completo: false } },
    }))
    for (const cod of MUNICIPIOS) {
      const cars = CARS.filter((car) => car.includes(cod))
      fs.writeFileSync(path.join(repo, "dados", "PA", `imoveis_basicos_${cod}.csv`),
        "cod_imovel,cod_ibge,municipio,uf,situacao_basica\n" + cars.map((car, k) => `${car},${cod},Município,PA,${k ? "nao_apto" : "com_pendencia"}\n`).join(""))
      const formas = { type: "FeatureCollection", features: cars.map((car, k) => ({ ...poligono(car, -50 + k), properties: { cod_imovel: car, credito_p50: 99999, risco: "privado" } })) }
      fs.writeFileSync(path.join(geo, `imoveis_${cod}.geojson.gz`), gzipSync(JSON.stringify(formas)))
    }
    const lidos = vi.spyOn(fs, "readFileSync")
    const saida = await construir(3)
    expect(json(saida, "amostra/estados.json").acesso).toBe("publico_basico")
    expect(json(saida, "geo/indice.json").cobertura).toMatchObject({ acesso: "aberto", com_desenho: MUNICIPIOS, sem_desenho: [] })
    expect(json(saida, "amostra/estados.json").estados.find((e: { uf: string }) => e.uf === "PA").com_lista).toEqual(MUNICIPIOS)
    expect(lidos.mock.calls.some(([arq]) => /imoveis_\d{7}\.csv$/.test(String(arq)))).toBe(false)
    for (const cod of MUNICIPIOS) {
      const csv = gunzipSync(fs.readFileSync(path.join(saida, "amostra", `imoveis_basicos_${cod}.csv.gz`))).toString()
      expect(csv.split("\n")[0]).toBe("cod_imovel,cod_ibge,municipio,uf,situacao_basica")
      const forma = JSON.parse(gunzipSync(fs.readFileSync(path.join(saida, "geo", `imoveis_${cod}.geojson.gz`))).toString())
      expect(forma.features.length).toBeGreaterThan(0)
      expect(forma.features.every((f: { properties: object }) => Object.keys(f.properties).join() === "cod_imovel")).toBe(true)
      expect(JSON.stringify(forma)).not.toContain("credito_p50")
      expect(fs.existsSync(path.join(saida, "amostra", `imoveis_${cod}.csv.gz`))).toBe(false)
    }
    expect(fs.existsSync(path.join(saida, "amostra", "fichas"))).toBe(false)
    expect(json(saida, "amostra/car_PA.json")).toEqual({})
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

  it("ignora completamente snapshots financeiros de lotes presentes na pasta local", async () => {
    const lotes = path.join(repo, "dados/lotes")
    fs.mkdirSync(lotes, { recursive: true })
    const resumo = { titulares: 10, reservas: 2, ha_lote: 100, creditos_lote_faixa: { p10: 10, p50: 20, p90: 30 },
      dados_individuais: [{ cod_imovel: CARS[0], nome_dono: "Dado privado de teste" }] }
    fs.writeFileSync(path.join(lotes, "lote_PA_central_r11.json"), JSON.stringify({
      uf: "PA", cenario: "central_r11", resumos: { barata: resumo, segura: resumo, compacta: resumo },
      arquivos: { privado: { url: "https://exemplo.invalid/individual.tar.gz" } },
    }))
    const lidos = vi.spyOn(fs, "readFileSync")
    const saida = await construir(0)
    expect(lidos.mock.calls.some(([arquivo]) => String(arquivo) === path.join(lotes, "lote_PA_central_r11.json"))).toBe(false)
    const lote = json(saida, "amostra/lote_PA_central_r11.json")
    expect(lote.estado).toBe("ausente")
    expect(lote.opcoes).toEqual([])
    expect(lote.base.creditos).toEqual({ p10: null, p50: null, p90: null })
    expect(JSON.stringify(lote)).not.toMatch(/Dado privado|cod_imovel|individual.tar.gz|nome_dono/)
  })

  it("publica apenas o contrato de resumo aprovado, sem campos pagos extras", async () => {
    const lotes = path.join(repo, "dados/lotes-publicos")
    fs.mkdirSync(lotes, { recursive: true })
    fs.writeFileSync(path.join(lotes, "lote_PA_central_r11.json"), JSON.stringify({
      contrato: "publico_lotes", versao: 1, estado: "publicado", uf: "PA", cenario: "central_r11",
      modelo_versao: "modelo-teste", atualizado_em: "2026-11-12T18:00:00Z", volume_creditos: 1000000,
      preco_contrato_usd: 55, opcoes: ["barata", "segura", "compacta"].map(id => ({ id, fazendas: 10,
        creditos: { p10: 10, p50: 20, p90: 30 }, hectares: 100, custo_usd_credito: 17,
        terra_pronta: { creditos_p50: 0, fracao_meta: 0 }, itens: [{ cod_imovel: CARS[0] }],
        geometria: { type: "Polygon" }, destrava: [{ texto: "Diligência privada" }], tir_p50: 91,
      })),
      arquivo_privado: "https://exemplo.invalid/individual.tar.gz",
    }))
    const saida = await construir(0), lote = json(saida, "amostra/lote_PA_central_r11.json")
    expect(lote.estado).toBe("publicado")
    expect(lote.opcoes).toHaveLength(3)
    expect(JSON.stringify(lote)).not.toMatch(/cod_imovel|Polygon|Diligência|tir_p50|tar\.gz/)
  })
})
