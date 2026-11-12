import { gzipSync } from "node:zlib"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { fonteAmostra } from "../dados/fonte-amostra"

const CAR = "PA-1505536-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
const CAR_VIZINHO = "PA-1504208-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
const respostas: Record<string, unknown> = {
  "estados.json": { estados: [{ uf: "PA", situacao: "incompleto", com_lista: ["1505536"] }] },
  "indice_PA.json": { arquivos: ["resumo_PA.csv", "imoveis_1505536.csv"] },
  "resumo_PA.csv.gz": "cod_ibge,municipio,imoveis\n1505536,Parauapebas,2\n1504208,Marabá,1\n",
  "car_PA.json": { [CAR_VIZINHO]: "1505536" },
  "fichas/indice.json": { municipios: [], codigos: [] },
  "geo/indice.json": { municipios: { "1505536": { imoveis: { arquivo: "imoveis_1505536.geojson.gz", bytes: 200 } } } },
  "geo/imoveis_1505536.geojson.gz": JSON.stringify({
    type: "FeatureCollection",
    features: [{ type: "Feature", properties: { cod_imovel: CAR }, geometry: { type: "Polygon", coordinates: [[[-50, -6], [-50, -5.9], [-49.9, -5.9], [-50, -6]]] } }],
  }),
  "imoveis_1505536.csv.gz": `cod_imovel,cod_municipio_ibge,municipio,uf,ha,carbono_ha\n${CAR},1505536,Parauapebas,PA,10,4\n${CAR_VIZINHO},1505536,Parauapebas,PA,5,2\n`,
}

describe("busca do site estático em subdiretório", () => {
  let pedidos: string[]
  let arquivos: Record<string, unknown>
  beforeEach(() => {
    pedidos = []
    arquivos = { ...respostas }
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      pedidos.push(url)
      expect(url).toMatch(/^\/Raiz\/(?:amostra|geo)\//)
      const arquivo = url.replace("/Raiz/", "").replace(/^amostra\//, "")
      const dado = arquivos[arquivo]
      // Nenhuma rota /busca nem tentativa de arquivo inexistente é permitida neste servidor estático.
      if (dado === undefined) throw new Error(`Arquivo inesperado: ${url}`)
      return typeof dado === "string"
        ? new Response(gzipSync(dado), { headers: { "content-type": "application/gzip" } })
        : Response.json(dado)
    }))
  })
  afterEach(() => vi.unstubAllGlobals())

  it("busca nome e código do município sem baixar listas de fazendas", async () => {
    const fonte = fonteAmostra("/Raiz/")
    for (const consulta of ["Parauapebas", "1505536"]) {
      expect((await fonte.buscar(consulta)).municipios[0]).toMatchObject({ cod_ibge: "1505536", municipio: "Parauapebas" })
    }
    expect((await fonte.buscar("maraba")).municipios[0].municipio).toBe("Marabá")
    expect(pedidos).toHaveLength(3)
    expect(pedidos.some((url) => url.includes("imoveis_"))).toBe(false)
  })

  it("busca CAR inteiro, com pontos e pelo começo usando só o município e as exceções do estado", async () => {
    const fonte = fonteAmostra("/Raiz/")
    for (const consulta of [CAR, "pa 1505536 aaaa.aaaa", CAR_VIZINHO, CAR_VIZINHO.slice(0, 15)]) {
      const esperado = consulta.includes("1504208") ? CAR_VIZINHO : CAR
      expect((await fonte.buscar(consulta)).imoveis[0].cod_imovel).toBe(esperado)
    }
    expect(pedidos.filter((url) => url.includes("imoveis_"))).toEqual(["/Raiz/amostra/imoveis_1505536.csv.gz"])
  })

  it.each(["ausente", "sem_dados", "incompleto"])("CAR de UF %s não pede índice de fazendas ausente", async (situacao) => {
    const estadoPA = { uf: "PA", situacao: "incompleto", com_lista: ["1505536"] }
    arquivos["estados.json"] = { estados: situacao === "ausente" ? [estadoPA] : [estadoPA, { uf: "SP", situacao, com_lista: [] }] }
    if (situacao === "incompleto") {
      arquivos["indice_SP.json"] = { arquivos: ["resumo_SP.csv"] }
      arquivos["resumo_SP.csv.gz"] = "cod_ibge,municipio,imoveis\n3550308,São Paulo,1\n"
    }
    const fonte = fonteAmostra("/Raiz/")
    const car = "SP-3550308-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    expect((await fonte.buscar(car)).situacao).toBe(situacao === "incompleto" ? "municipio_sem_imoveis" : "estado_nao_processado")
    expect(await fonte.imovel(car)).toBeNull()
    expect(pedidos.some((url) => url.includes("car_SP.json") || url.includes("imoveis_3550308"))).toBe(false)
  })

  it("descarta consulta cancelada sem envenenar as leituras em cache", async () => {
    const fonte = fonteAmostra("/Raiz/")
    const controle = new AbortController()
    const pendente = fonte.buscar("Parauapebas", controle.signal)
    controle.abort()
    await expect(pendente).rejects.toMatchObject({ name: "AbortError" })
    expect((await fonte.buscar("1505536")).situacao).toBe("ok")
    expect(pedidos).toHaveLength(3)
  })

  it("monta ficha ausente do manifesto com geometria gzip e sem pedir JSON inexistente", async () => {
    const fonte = fonteAmostra("/Raiz/")
    const ficha = await fonte.ficha(CAR)
    expect(ficha?.imovel.cod_imovel).toBe(CAR)
    expect(pedidos).toContain("/Raiz/geo/imoveis_1505536.geojson.gz")
    expect(pedidos.filter((url) => url.includes("/fichas/"))).toEqual(["/Raiz/amostra/fichas/indice.json"])
    expect(await fonte.geo.camada("1504208", "imoveis")).toBeNull()
    expect(pedidos.some((url) => url.includes("imoveis_1504208"))).toBe(false)
  })

  it("busca CAR público mínimo sem reconstruir métricas nem abrir ficha completa", async () => {
    arquivos["estados.json"] = { acesso: "publico_basico", estados: [{ uf: "PA", situacao: "incompleto", com_lista: ["1505536"] }] }
    arquivos["indice_PA.json"] = { arquivos: ["resumo_PA.csv", "imoveis_basicos_1505536.csv", "imoveis_1505536.csv", "certidoes_1505536.csv"] }
    arquivos["imoveis_basicos_1505536.csv.gz"] = `cod_imovel,cod_ibge,municipio,uf,situacao_basica,ha,credito_p50\n${CAR},1505536,Parauapebas,PA,apto,98765,88888\n${CAR_VIZINHO},1505536,Parauapebas,PA,nao_apto,98765,88888\n`
    const fonte = fonteAmostra("/Raiz/")
    for (const car of [CAR, CAR_VIZINHO]) {
      const resultado = await fonte.buscar(car)
      expect(resultado.imoveis).toEqual([{ cod_imovel: car, cod_ibge: "1505536", municipio: "Parauapebas", uf: "PA", situacao_basica: car === CAR ? "apto" : "nao_apto" }])
      expect(await fonte.imovel(car)).toBeNull()
      expect(await fonte.ficha(car)).toBeNull()
      expect(await fonte.certidoes(car)).toEqual([])
    }
    expect(await fonte.imoveis("1505536")).toBeNull()
    expect(pedidos.filter((url) => /imoveis_|fichas\/|certidoes_/.test(url))).toEqual(["/Raiz/amostra/imoveis_basicos_1505536.csv.gz"])
    expect(await fonte.geo.camada("1505536", "imoveis")).toMatchObject({ features: [{ properties: { cod_imovel: CAR } }] })
  })
})
