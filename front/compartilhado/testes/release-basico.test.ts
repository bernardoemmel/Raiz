import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { gunzipSync } from "node:zlib"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { abrirPasta } from "../pasta-dados"
import { dadosRaiz } from "../vite-dados"
import { fonteAmostra } from "../dados/fonte-amostra"
import { fontePedidosRelease } from "../pedidos/fonte-pedidos"
import { CAMPOS_PADRAO } from "../pedidos/exemplo"

let repo: string, dados: string, geo: string
const cod = "1505536"
const car = `PA-${cod}-EXEMPLO`
const basico = `imoveis_basicos_${cod}.csv`
const completo = `imoveis_${cod}.csv`
const contorno = { type: "Polygon", coordinates: [[[-50, -6], [-49, -6], [-49, -5], [-50, -5], [-50, -6]]] }
const abrir = () => abrirPasta({ repo, raizDados: dados, geo })

beforeEach(() => {
  repo = fs.mkdtempSync(path.join(os.tmpdir(), "raiz-release-basico-"))
  dados = path.join(repo, "dados", "estados")
  geo = path.join(repo, "front", "geo")
  fs.mkdirSync(path.join(dados, "PA"), { recursive: true })
  fs.mkdirSync(geo, { recursive: true })
  fs.writeFileSync(path.join(dados, "PA", basico), "cod_imovel,cod_ibge,municipio,uf,situacao_basica\n" + Array.from({ length: 12 }, (_, n) => `${car}${n},${cod},Parauapebas,PA,apto\n`).join(""))
  fs.writeFileSync(path.join(dados, "PA", "resumo_PA.csv"), "cod_ibge,municipio,imoveis,aptas_carbono,aptas_com_matricula,ha_carbono,ha_carbono_matricula\n1505536,Parauapebas,12,12,6,120,60\n")
  fs.writeFileSync(path.join(geo, "brasil_municipios.geojson"), JSON.stringify({ type: "FeatureCollection", features: [{ type: "Feature", properties: { cod_ibge: cod, nome: "Parauapebas", uf: "PA" }, geometry: contorno }] }))
})
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); fs.rmSync(repo, { recursive: true, force: true }) })

function manifesto(escopo = "publico_basico") {
  fs.writeFileSync(path.join(dados, "estados.json"), JSON.stringify({ gerado_em: "2026-11-12T19:25:46Z", estados: { PA: { municipios: 1, completo: false, escopo } } }))
}
function deixarArquivoAntigo() {
  fs.writeFileSync(path.join(dados, "PA", completo), `cod_imovel,ha,carbono_ha\n${car}ANTIGO,999,999\n`)
}

describe("Release público básico", () => {
  it("descobre os municípios e usa as somas publicadas sem inventar métricas individuais", async () => {
    manifesto()
    const pasta = abrir()
    expect(pasta.comImoveis("PA")).toEqual([cod])
    expect(pasta.quantidadeImoveis(cod)).toBe(12)
    expect(pasta.estados().estados.find((e) => e.uf === "PA")).toMatchObject({ municipios: 1, com_lista: [cod] })
    expect(pasta.municipio(cod)).toBeNull()
    expect(await pasta.ficha(car + "0")).toBeNull()
    const pontos = await pasta.pontosPublicos("PA")
    expect(pontos).toMatchObject({ fazendas: 12, sem_lugar: 0, suprimidos: false })
    expect(pontos!.pontos.map((p) => p.slice(2))).toEqual([["apta", 60, cod, 6], ["pendencia", 60, cod, 6]])
  })

  it("prefere o básico ao arquivo antigo, inclusive sem manifesto", async () => {
    deixarArquivoAntigo()
    const pasta = abrir()
    expect(pasta.comImoveis("PA")).toEqual([cod])
    expect(pasta.quantidadeImoveis(cod)).toBe(12)
    expect(pasta.municipio(cod)).toBeNull()
    expect((await pasta.pontosPublicos("PA"))!.fazendas).toBe(12)
  })

  it("o escopo público básico impede o uso de arquivo e cache detalhados remanescentes", async () => {
    fs.unlinkSync(path.join(dados, "PA", basico))
    deixarArquivoAntigo()
    const pasta = abrir()
    expect((await pasta.pontos("PA"))!.fazendas).toBe(1)
    expect(pasta.municipio(cod)).not.toBeNull()
    manifesto()
    expect(pasta.comImoveis("PA")).toEqual([])
    expect(pasta.quantidadeImoveis(cod)).toBe(0)
    expect(pasta.municipio(cod)).toBeNull()
    expect(pasta.csvLimpo(completo)).toBeNull()
    expect(pasta.arquivos("PA")).not.toContain(completo)
    expect((await pasta.pontosPublicos("PA"))!.fazendas).toBe(12)
  })

  it("publica somente agregados e alimenta o pedido com os totais reais do novo pacote", async () => {
    manifesto()
    deixarArquivoAntigo()
    vi.stubEnv("RAIZ_BUILD_DADOS", "1")
    fs.mkdirSync(path.join(repo, "site"))
    const plugin = dadosRaiz({ repo, raizDados: dados })
    plugin.configResolved({ root: repo, command: "build", build: { outDir: "site" } })
    await plugin.closeBundle()
    const saida = path.join(repo, "site")
    const publicados = fs.readdirSync(path.join(saida, "amostra"))
    expect(publicados).not.toContain(basico)
    expect(publicados).not.toContain(completo)
    const texto = gunzipSync(fs.readFileSync(path.join(saida, "amostra", "resumo_PA.csv.gz"))).toString()
    expect(texto).toContain("Parauapebas,12,12,6,120,60")
    expect(texto).not.toContain(car)
    const pedidos: string[] = []
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      pedidos.push(url)
      const arquivo = path.join(saida, url.replace(/^\/Raiz\//, ""))
      if (!fs.existsSync(arquivo)) throw new Error(`Arquivo não publicado: ${url}`)
      return new Response(fs.readFileSync(arquivo))
    }))
    const fonte = fonteAmostra("/Raiz/")
    const f = fontePedidosRelease("/Raiz/", fonte)
    const pedido = await f.criar({ ...CAMPOS_PADRAO, onde: { ...CAMPOS_PADRAO.onde, biomas: [], ufs: ["PA"] } })
    expect(pedido.publicacao?.cobertura).toEqual({ municipios: 1, estados: 1, fazendas: 12, hectares: 120 })
    expect(pedido.publicacao?.base.creditos.p50).toBeNull()
    expect(pedido.opcoes).toEqual([])
    expect(await fonte.ficha(car + "0")).toBeNull()
    expect(pedidos.some((url) => /imoveis|fichas|car_PA/.test(url))).toBe(false)
  })
})
