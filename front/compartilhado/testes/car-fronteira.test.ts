import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { abrirPasta } from "../pasta-dados"
import { dadosRaiz } from "../vite-dados"
import { fonteAmostra } from "../dados/fonte-amostra"

const CAR_PB = "PB-2500106-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
const CAR_RN_VIZINHO = "RN-2400703-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
const DESTINOS = ["2400109", "2413409"]
const FRONTEIRAS = { "2500106": DESTINOS }

function conectar(plugin: ReturnType<typeof dadosRaiz>) {
  let chamada: (req: unknown, res: unknown, next: () => void) => void
  plugin.configureServer({ middlewares: { use: (fn: typeof chamada) => { chamada = fn } } } as never)
  return (url: string) => new Promise<{ status: number; corpo: string }>(resolve => {
    const res = { statusCode: 200, setHeader() {}, end(dado: string | Buffer = "") { resolve({ status: this.statusCode, corpo: dado.toString() }) } }
    chamada({ url, headers: {} }, res, () => resolve({ status: 404, corpo: "" }))
  })
}

describe("CAR público cadastrado em outra UF", () => {
  let repo: string
  beforeEach(() => {
    repo = fs.mkdtempSync(path.join(os.tmpdir(), "raiz-car-fronteira-"))
    fs.mkdirSync(path.join(repo, "dados", "RN"), { recursive: true })
    fs.mkdirSync(path.join(repo, "geo"))
    fs.mkdirSync(path.join(repo, "site"))
    fs.writeFileSync(path.join(repo, "dados", "estados.json"), JSON.stringify({
      versao_publicacao: 1, escopo: "publico_basico", estados: { RN: { versao_publicacao: 1, escopo: "publico_basico" } },
    }))
    fs.writeFileSync(path.join(repo, "dados", "RN", "resumo_RN.csv"), "cod_ibge,municipio,imoveis\n2400109,Acari,6\n2413409,Serra Negra do Norte,6\n")
    for (const cod of DESTINOS) {
      fs.writeFileSync(path.join(repo, "dados", "RN", `imoveis_basicos_${cod}.csv`),
        `cod_imovel,cod_ibge,municipio,uf,situacao_basica\n${CAR_PB},${cod},Município,RN,apto\n` +
        (cod === "2413409" ? `${CAR_RN_VIZINHO},${cod},Município,RN,com_pendencia\n` : ""))
      fs.writeFileSync(path.join(repo, "dados", "RN", `imoveis_${cod}.csv`), "cod_imovel,credito_p50\nPB-2500205-CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC,canario_PRIVADO\n")
    }
    vi.stubEnv("RAIZ_GEO", "geo")
    vi.stubEnv("RAIZ_BUILD_DADOS", "1")
    vi.spyOn(console, "log").mockImplementation(() => {})
  })
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); fs.rmSync(repo, { recursive: true, force: true }) })

  async function construir() {
    const plugin = dadosRaiz({ repo, raizDados: "dados" })
    plugin.configResolved({ root: repo, command: "build", build: { outDir: "site" } })
    await plugin.closeBundle()
    return path.join(repo, "site")
  }

  it("gera relações únicas por município sem perder recortes do mesmo CAR nem ler o arquivo privado", () => {
    const lidos = vi.spyOn(fs, "readFileSync")
    const pasta = abrirPasta({ repo, raizDados: "dados" })
    expect(pasta.fronteirasBasicas()).toEqual(FRONTEIRAS)
    expect(pasta.fronteirasBasicas()).toEqual(FRONTEIRAS)
    expect(lidos.mock.calls.filter(([arq]) => /imoveis_basicos_/.test(String(arq)))).toHaveLength(2)
    expect(lidos.mock.calls.some(([arq]) => /imoveis_\d{7}\.csv$/.test(String(arq)))).toBe(false)
    expect(JSON.stringify(pasta.fronteirasBasicas())).not.toContain("PB-")
    expect(JSON.stringify(pasta.fronteirasBasicas())).not.toContain("2400703")
  })

  it("invalida o índice na mesma pasta e preserva código cadastral histórico fora da DTB atual", () => {
    const pasta = abrirPasta({ repo, raizDados: "dados" })
    expect(pasta.fronteirasBasicas()).toEqual(FRONTEIRAS)
    const arquivo = path.join(repo, "dados", "RN", "imoveis_basicos_2413409.csv")
    fs.writeFileSync(arquivo, "cod_imovel,cod_ibge,municipio,uf,situacao_basica\nPB-2599999-DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD,2413409,Município,RN,apto\n")
    const instante = new Date(Date.now() + 1000)
    fs.utimesSync(arquivo, instante, instante)
    expect(pasta.fronteirasBasicas()).toEqual({ "2500106": ["2400109"], "2599999": ["2413409"] })
    fs.rmSync(path.join(repo, "dados", "RN", "imoveis_basicos_2400109.csv"))
    expect(pasta.fronteirasBasicas()).toEqual({ "2599999": ["2413409"] })
  })

  it("servidor de desenvolvimento confirma CAR na lista básica territorial e preserva a busca da mesma UF", async () => {
    const servir = conectar(dadosRaiz({ repo, raizDados: "dados" }))
    const estados = JSON.parse((await servir("/amostra/estados.json")).corpo)
    expect(estados.car_fronteira).toBe("car_fronteira.json")
    expect(estados.estados.find((e: { uf: string }) => e.uf === "PB").situacao).toBe("sem_dados")
    const indice = await servir("/amostra/car_fronteira.json")
    expect(indice.status).toBe(200)
    expect(JSON.parse(indice.corpo)).toEqual(FRONTEIRAS)
    for (const car of [CAR_PB, CAR_PB.slice(0, 15), CAR_RN_VIZINHO]) {
      const resultado = JSON.parse((await servir(`/busca?q=${car}`)).corpo)
      expect(resultado.situacao).toBe("ok")
      expect(resultado.imoveis).toHaveLength(1)
      expect(resultado.imoveis.every((i: { uf: string; cod_imovel: string }) => i.uf === "RN" && i.cod_imovel.startsWith(car))).toBe(true)
      expect(Object.keys(resultado.imoveis[0]).sort()).toEqual(["cod_ibge", "cod_imovel", "municipio", "situacao_basica", "uf"])
    }
    expect(JSON.parse((await servir(`/busca?q=${CAR_PB.replace(/A/g, "D")}`)).corpo).situacao).toBe("estado_nao_processado")
  })

  it("build anuncia somente o arquivo existente e o navegador abre só as listas candidatas", async () => {
    const saida = await construir()
    const estados = JSON.parse(fs.readFileSync(path.join(saida, "amostra", "estados.json"), "utf8"))
    expect(estados.car_fronteira).toBe("car_fronteira.json")
    expect(JSON.parse(fs.readFileSync(path.join(saida, "amostra", estados.car_fronteira), "utf8"))).toEqual(FRONTEIRAS)
    const pedidos: string[] = []
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      pedidos.push(url)
      const arquivo = path.join(saida, url.replace(/^\/Raiz\//, ""))
      if (!fs.existsSync(arquivo)) throw new Error(`Arquivo inexistente: ${url}`)
      return new Response(fs.readFileSync(arquivo), { headers: { "content-type": url.endsWith(".gz") ? "application/gzip" : "application/json" } })
    }))
    const fonte = fonteAmostra("/Raiz/")
    await fonte.buscar("Serra Negra")
    expect(pedidos.some(url => /car_|imoveis_/.test(url))).toBe(false)
    expect((await fonte.buscar(CAR_PB)).imoveis).toMatchObject([{ cod_imovel: CAR_PB, cod_ibge: DESTINOS[0] }])
    expect(pedidos.filter(url => /imoveis_|car_/.test(url))).toEqual(["/Raiz/amostra/car_fronteira.json", ...DESTINOS.map(cod => `/Raiz/amostra/imoveis_basicos_${cod}.csv.gz`)])
    expect(pedidos.some(url => /indice_PB|car_PB/.test(url))).toBe(false)
    expect((await fonte.buscar(CAR_RN_VIZINHO)).imoveis).toHaveLength(1)
    expect(await fonte.ficha(CAR_PB)).toBeNull()
    expect(await fonte.certidoes(CAR_PB)).toEqual([])
  })

  it("remove índice e anúncio ao voltar ao contrato agregado, mesmo havendo sobras do build anterior", async () => {
    await construir()
    fs.rmSync(path.join(repo, "dados", "estados.json"))
    const saida = await construir()
    expect(fs.existsSync(path.join(saida, "amostra", "car_fronteira.json"))).toBe(false)
    const estados = JSON.parse(fs.readFileSync(path.join(saida, "amostra", "estados.json"), "utf8"))
    expect(estados.acesso).toBe("agregado")
    expect(estados.car_fronteira).toBeUndefined()
    expect((await conectar(dadosRaiz({ repo, raizDados: "dados" }))("/amostra/car_fronteira.json")).status).toBe(404)
  })
})
