/**
 * Dados por estado: a pasta de RAIZ_DADOS (ou dados/estados, que o predev baixa), o estados.json, os pontos de cada
 * estado com cache em disco, a queda para a amostra sem internet e a máscara de CPF e CNPJ no que vai para a tela.
 * Os estados de teste são montados numa pasta temporária a partir da amostra do Pará (nada disto vai para o git).
 */

import { execFileSync, spawnSync } from "node:child_process"
import { gunzipSync, gzipSync } from "node:zlib"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { afterAll, beforeAll, describe, expect, it } from "vitest"
import { escreverCsv, lerCsv } from "../dados/csv"
import { buscarTextoGz } from "../dados/fonte"
import { complementosDe, juntarComplementos } from "../dados/complementos"
import { lerFunil, lerImovel } from "../dados/funil"
import { ufDoCodigo } from "../formato"
import { municipiosDoEstado } from "../ibge-municipios"
import { abrirPasta, lerRaizDados, pastaPadrao, ufDoArquivo } from "../pasta-dados"
import { dadosRaiz } from "../vite-dados"

const FRONT = path.resolve(__dirname, "../..")
const REPO = path.resolve(FRONT, "..")
const AMOSTRA = path.join(REPO, "dados", "amostra")
const BAIXAR = path.join(FRONT, "scripts", "baixar-dados.mjs")

const temp = fs.mkdtempSync(path.join(os.tmpdir(), "raiz-estados-"))
afterAll(() => fs.rmSync(temp, { recursive: true, force: true }))

const ler = (arq: string) => lerCsv(fs.readFileSync(path.join(AMOSTRA, arq), "utf8"))
const calado = () => {}

/** CPF de teste com os dígitos certos (só para ver a máscara agir; não é de ninguém) */
function cpfDeTeste(base: string): string {
  const d = base.split("").map(Number)
  for (const n of [9, 10]) {
    let s = 0
    for (let i = 0; i < n; i++) s += d[i] * (n + 1 - i)
    d.push(((s * 10) % 11) % 10)
  }
  return d.join("")
}
const CPF = cpfDeTeste("123456789")

/** um quadrado em volta de (lon, lat), para o contorno de município de teste */
const quadrado = (lon: number, lat: number) => ({
  type: "Polygon",
  coordinates: [
    [
      [lon - 0.1, lat - 0.1],
      [lon + 0.1, lat - 0.1],
      [lon + 0.1, lat + 0.1],
      [lon - 0.1, lat + 0.1],
      [lon - 0.1, lat - 0.1],
    ],
  ],
})

// Amapá completo (os 16 municípios do IBGE, um com lista por fazenda) e Goiás incompleto (5 de 246 e um código que
// não existe no IBGE). O resumo copia as linhas do Pará trocando o código; a lista por fazenda é a de Cumaru do Norte.
const AP = municipiosDoEstado("AP")
const GO = municipiosDoEstado("GO").slice(0, 5)
const COM_LISTA = AP[0]
const SEM_CONTORNO = AP[15]

function montarDados(raiz: string) {
  const escrever = (uf: string, nome: string, colunas: string[], linhas: Record<string, unknown>[]) => {
    fs.mkdirSync(path.join(raiz, uf), { recursive: true })
    fs.writeFileSync(path.join(raiz, uf, nome), escreverCsv(colunas, linhas))
  }
  const resumo = ler("resumo_PA.csv")
  escrever(
    "AP",
    "resumo_AP.csv",
    resumo.colunas,
    AP.map((cod, k) => ({ ...resumo.linhas[k], cod_ibge: cod, municipio: `Município ${k + 1}` })),
  )
  for (const tipo of ["imoveis", "filtros"]) {
    const t = ler(`${tipo}_1504950.csv`)
    escrever(
      "AP",
      `${tipo}_${COM_LISTA}.csv`,
      t.colunas,
      t.linhas.map((l) => ({
        ...l,
        cod_imovel: l.cod_imovel.replace("PA-1504950-", `AP-${COM_LISTA}-`),
        ...(tipo === "imoveis" ? { uf: "AP", cod_municipio_ibge: COM_LISTA } : {}),
      })),
    )
  }
  // um complemento com coluna pessoal e CPF: não pode chegar à tela
  const primeiros = ler("imoveis_1504950.csv").linhas.slice(0, 3)
  escrever(
    "AP",
    `extras_${COM_LISTA}.csv`,
    ["cod_imovel", "nome_proprietario", "obs"],
    primeiros.map((l) => ({
      cod_imovel: l.cod_imovel.replace("PA-1504950-", `AP-${COM_LISTA}-`),
      nome_proprietario: "Nome de teste",
      obs: `contato ${CPF} e ${CPF.slice(0, 3)}.${CPF.slice(3, 6)}.${CPF.slice(6, 9)}-${CPF.slice(9)}`,
    })),
  )
  escrever(
    "GO",
    "resumo_GO.csv",
    resumo.colunas,
    [...GO, "5299999"].map((cod, k) => ({ ...resumo.linhas[k], cod_ibge: cod, municipio: `Município ${k + 1}` })),
  )
  // pasta que não é de estado fica de fora
  fs.mkdirSync(path.join(raiz, "rascunho"), { recursive: true })
  fs.writeFileSync(path.join(raiz, "rascunho", "imoveis_1507300.csv"), "cod_imovel\n")
}

function montarGeo(dir: string) {
  fs.mkdirSync(dir, { recursive: true })
  const cods = [...AP.filter((c) => c !== SEM_CONTORNO), ...GO]
  const features = cods.map((cod, k) => ({
    type: "Feature",
    properties: { cod_ibge: cod, nome: `Município ${k + 1}`, uf: ufDoCodigo(cod) },
    geometry: quadrado(-52 + k * 0.5, -1 - (k % 3)),
  }))
  fs.writeFileSync(path.join(dir, "brasil_municipios.geojson"), JSON.stringify({ type: "FeatureCollection", features }))
}

const DADOS = path.join(temp, "dados")
const GEO = path.join(temp, "geo")
const CACHE = path.join(temp, "cache")
const abrir = (opcoes: Partial<Parameters<typeof abrirPasta>[0]> = {}) =>
  abrirPasta({ repo: REPO, raizDados: DADOS, geo: GEO, cache: CACHE, avisar: calado, ...opcoes })

beforeAll(() => {
  montarDados(DADOS)
  montarGeo(GEO)
})

describe("estado completo e incompleto pela lista do IBGE", () => {
  it("a lista do IBGE tem os 5.571 municípios, 16 no Amapá e 246 em Goiás", () => {
    const todos = Object.keys({ AC: 1, AL: 1, AM: 1, AP: 1, BA: 1, CE: 1, DF: 1, ES: 1, GO: 1, MA: 1, MG: 1, MS: 1, MT: 1, PA: 1, PB: 1, PE: 1, PI: 1, PR: 1, RJ: 1, RN: 1, RO: 1, RR: 1, RS: 1, SC: 1, SE: 1, SP: 1, TO: 1 })
    expect(todos.reduce((s, uf) => s + municipiosDoEstado(uf).length, 0)).toBe(5571)
    expect(AP).toHaveLength(16)
    expect(municipiosDoEstado("GO")).toHaveLength(246)
    expect(municipiosDoEstado("MT")).toContain("5101837") // Boa Esperança do Norte, criado depois do censo de 2022
    for (const uf of todos) for (const cod of municipiosDoEstado(uf)) expect(ufDoCodigo(cod), cod).toBe(uf)
  })

  it("o nome do arquivo diz de que estado ele é", () => {
    expect(ufDoArquivo("resumo_GO.csv")).toBe("GO")
    expect(ufDoArquivo("imoveis_1507300.csv")).toBe("PA")
    expect(ufDoArquivo("extras_direto_1600303.csv")).toBe("AP")
    expect(ufDoArquivo("resumo_XX.csv")).toBeNull()
    expect(ufDoArquivo("notas.csv")).toBeNull()
  })

  it("Amapá: todos os 16 municípios processados, completo, com a lista por fazenda de um", () => {
    const p = abrir()
    expect(p.modo).toBe("estados")
    expect(p.ufs()).toEqual(["AP", "GO"])
    const e = p.estados()
    expect(e.pasta).toBe("RAIZ_DADOS")
    expect(e.estados).toHaveLength(27)
    const ap = e.estados.find((x) => x.uf === "AP")!
    expect(ap).toMatchObject({ situacao: "completo", completo: true, municipios: 16, municipios_ibge: 16, com_lista: [COM_LISTA], fora_da_lista: [] })
  })

  it("Goiás: 5 de 246, incompleto, e o código que não está no IBGE não conta", () => {
    const go = abrir().estados().estados.find((x) => x.uf === "GO")!
    expect(go).toMatchObject({ situacao: "incompleto", completo: false, municipios: 5, municipios_ibge: 246, fora_da_lista: ["5299999"] })
  })

  it("estado sem pasta fica sem dados, com o total do IBGE para o aviso", () => {
    const e = abrir().estados().estados
    const to = e.find((x) => x.uf === "TO")!
    expect(to).toMatchObject({ situacao: "sem_dados", municipios: 0, municipios_ibge: 139, com_lista: [] })
    expect(e.filter((x) => x.situacao === "sem_dados")).toHaveLength(25)
  })

  it("lê pelo nome das colunas e junta os complementos do estado", () => {
    const m = abrir().municipio(COM_LISTA)!
    const amostra = ler("imoveis_1504950.csv").linhas
    expect(m.imoveis).toHaveLength(amostra.length)
    // filtros_ entrou: a mesma fazenda tem o filtro territorial que tinha no Pará
    const nomes = complementosDe(fs.readdirSync(AMOSTRA), "1504950").filter((n) => n.startsWith("filtros_"))
    const { porImovel } = juntarComplementos(nomes.map((arquivo) => ({ arquivo, linhas: ler(arquivo).linhas })))
    const original = lerImovel(amostra[0], porImovel.get(amostra[0].cod_imovel))
    const copia = m.imoveis.find((i) => i.cod_imovel === amostra[0].cod_imovel.replace("PA-1504950-", `AP-${COM_LISTA}-`))!
    expect(copia.filtro_territorial).toBe(original.filtro_territorial)
    expect(copia.apta).toBe(original.apta)
  })
})

describe("pontos por estado, com cache em disco", () => {
  it("as fazendas aptas do estado somam o funil, e o município sem contorno fica fora do mapa, contado à parte", async () => {
    const p = abrir({ cache: path.join(temp, "cache-soma") })
    const r = (await p.pontos("AP"))!
    const resumo = lerCsv(fs.readFileSync(path.join(DADOS, "AP", "resumo_AP.csv"), "utf8")).linhas.map((l) => lerFunil(l, "AP"))
    const daLista = p.municipio(COM_LISTA)!.imoveis.filter((i) => i.apta).length
    const doResumo = resumo.filter((m) => m.cod_ibge !== COM_LISTA).reduce((s, m) => s + m.aptas_carbono, 0)
    expect(r.fazendas).toBe(daLista + doResumo)
    expect(r.sem_lugar).toBe(resumo.find((m) => m.cod_ibge === SEM_CONTORNO)!.aptas_carbono)
    expect(r.pontos.reduce((s, x) => s + x[5], 0)).toBe(r.fazendas - r.sem_lugar)
    // sem contorno das fazendas, cada município vira dois pontos no meio dele (com matrícula e falta o título)
    expect(r.pontos.every((x) => x[4].startsWith("16") && x[5] >= 1)).toBe(true)
    expect(new Set(r.pontos.map((x) => x[4])).size).toBe(15)
    // o Goiás não pediu nada: ninguém leu os imóveis de lá
    expect(await p.pontos("PA")).toBeNull()
  })

  it("monta uma vez, guarda em disco e só refaz quando o CSV muda", async () => {
    const cache = path.join(temp, "cache-vezes")
    const p = abrir({ cache })
    const primeira = await p.pontosTexto("AP")
    expect(p.montagens()).toBe(1)
    expect(await p.pontosTexto("AP")).toBe(primeira)
    expect(p.montagens()).toBe(1)
    const arquivos = () => fs.readdirSync(p.cache).filter((f) => f.startsWith("pontos_AP."))
    expect(arquivos()).toHaveLength(1)

    // servidor reiniciado: lê do disco, sem montar
    const depois = abrir({ cache })
    expect(await depois.pontosTexto("AP")).toBe(primeira)
    expect(depois.montagens()).toBe(0)

    // o CSV mudou: refaz, e a versão velha sai do disco
    const csv = path.join(DADOS, "AP", `imoveis_${COM_LISTA}.csv`)
    const antes = arquivos()[0]
    const futuro = new Date(Date.now() + 60_000)
    fs.utimesSync(csv, futuro, futuro)
    await depois.pontosTexto("AP")
    expect(depois.montagens()).toBe(1)
    expect(arquivos()).toHaveLength(1)
    expect(arquivos()[0]).not.toBe(antes)
  })

  it("dois pedidos do mesmo estado ao mesmo tempo esperam a mesma montagem", async () => {
    const p = abrir({ cache: path.join(temp, "cache-junto") })
    const [a, b] = await Promise.all([p.pontosTexto("GO"), p.pontosTexto("GO")])
    expect(a).toBe(b)
    expect(p.montagens()).toBe(1)
  })
})

describe("estados.json baixado do Release dados", () => {
  it("usa os números do estados.json em vez de recontar; estado fora dele é contado", () => {
    const raiz = path.join(temp, "publicada")
    montarDados(raiz)
    fs.writeFileSync(
      path.join(raiz, "estados.json"),
      JSON.stringify({
        gerado_em: "2026-11-12T11:01:27+00:00",
        estados: {
          // o publicado diz 14 de 15 municípios; na pasta só há arquivo de 16 do Amapá: vale o publicado
          AP: { municipios: 14, total_ibge: 15, completo: false, tabelas: { imoveis: 14 }, versao: "abc", atualizado_em: "2026-11-12T10:52:28+00:00" },
        },
      }),
    )
    const e = abrir({ raizDados: raiz }).estados()
    expect(e.pasta).toBe("publicada")
    expect(e.gerado_em).toBe("2026-11-12T11:01:27+00:00")
    expect(e.estados.find((x) => x.uf === "AP")).toMatchObject({
      situacao: "incompleto",
      municipios: 14,
      municipios_ibge: 15,
      tabelas: { imoveis: 14 },
      versao: "abc",
      atualizado_em: "2026-11-12T10:52:28+00:00",
      com_lista: [COM_LISTA],
    })
    expect(e.estados.find((x) => x.uf === "GO")).toMatchObject({ situacao: "incompleto", municipios: 5, municipios_ibge: 246 })
  })
})

describe("sem RAIZ_DADOS e sem internet: a amostra", () => {
  const repoFalso = path.join(temp, "repo")
  beforeAll(() => fs.mkdirSync(repoFalso, { recursive: true }))

  it("RAIZ_DADOS vem do ambiente ou do .env; sem ela, dados/estados se já tiver estado; senão, nada", () => {
    expect(lerRaizDados(repoFalso, {})).toBeNull()
    expect(pastaPadrao(repoFalso, {})).toBeNull()
    fs.mkdirSync(path.join(repoFalso, "dados", "publicos"), { recursive: true })
    expect(pastaPadrao(repoFalso, {}), "pasta pública vazia não volta à amostra").toBe("dados/publicos")
    fs.mkdirSync(path.join(repoFalso, "dados", "publicos", "AP"))
    fs.writeFileSync(path.join(repoFalso, "dados", "publicos", "AP", "resumo_AP.csv"), "cod_ibge\n")
    expect(pastaPadrao(repoFalso, {})).toBe("dados/publicos")
    fs.writeFileSync(path.join(repoFalso, ".env"), 'MAPBIOMAS_ALERTA_EMAIL=x\nRAIZ_DADOS="motor/saida"\n')
    expect(pastaPadrao(repoFalso, {})).toBe("motor/saida")
    expect(pastaPadrao(repoFalso, { RAIZ_DADOS: "/outra" })).toBe("/outra")
    fs.writeFileSync(path.join(repoFalso, ".env"), "RAIZ_DADOS=\n")
    expect(lerRaizDados(repoFalso, {})).toBeNull()
  })

  it("sem a variável, com pasta que não existe ou pedindo dados/amostra, lê a amostra como sempre", () => {
    const avisos: string[] = []
    for (const raizDados of [null, "dados/amostra"]) {
      const p = abrirPasta({ repo: REPO, raizDados, geo: GEO, cache: CACHE, avisar: (m) => avisos.push(m) })
      expect(p.modo).toBe("amostra")
      const e = p.estados()
      expect(e.pasta).toBe("amostra")
      expect(e.estados.find((x) => x.uf === "PA")).toMatchObject({
        situacao: "completo",
        municipios: 144,
        municipios_ibge: 144,
        com_lista: ["1504950", "1507300"],
      })
      expect(e.estados.filter((x) => x.situacao === "sem_dados")).toHaveLength(26)
    }
    const vazia = abrirPasta({ repo: REPO, raizDados: "/pasta/que/nao/existe", avisar: (m) => avisos.push(m) })
    expect(vazia.ufs()).toEqual([])
    expect(avisos.join(" ")).toMatch(/nenhum dado será servido/)
  })

  it("o predev sem internet avisa e segue (sai sem erro), e o front abre com a amostra", async () => {
    const destino = path.join(temp, "baixados")
    const r = spawnSync(process.execPath, [BAIXAR], {
      env: { ...process.env, RAIZ_DADOS: destino, RAIZ_DADOS_URL: "http://127.0.0.1:9/dados", RAIZ_SEM_DOWNLOAD: "" },
      encoding: "utf8",
      timeout: 30_000,
    })
    expect(r.status).toBe(0)
    expect(r.stderr).toMatch(/\[dados\] não consegui ler o estados\.json público/)
    expect(fs.existsSync(destino)).toBe(false)
    // o plugin com a mesma RAIZ_DADOS: a pasta não existe, então serve a amostra
    const servir = conectar(dadosRaiz({ repo: REPO, raizDados: destino, cache: path.join(temp, "cache-predev") }))
    const e = JSON.parse((await servir("/amostra/estados.json")).corpo)
    expect(e.pasta).toBe("RAIZ_DADOS")
    expect(e.estados.find((x: { uf: string }) => x.uf === "PA").situacao).toBe("sem_dados")
    expect((await servir("/amostra/pontos_PA.json")).status).toBe(404)
  }, 60_000)

  it("RAIZ_SEM_DOWNLOAD=1 pula o download sem tentar a rede", () => {
    const saida = execFileSync(process.execPath, [BAIXAR], {
      env: { ...process.env, RAIZ_SEM_DOWNLOAD: "1", RAIZ_DADOS_URL: "http://127.0.0.1:9/dados" },
      encoding: "utf8",
    })
    expect(saida).toBe("")
  })
})

describe("o que o plugin serve", () => {
  let servir: ReturnType<typeof conectar>
  beforeAll(() => {
    servir = conectar(dadosRaiz({ repo: REPO, raizDados: DADOS, cache: path.join(temp, "cache-plugin") }))
  })

  it("estados, índice e pontos de um estado pelas rotas de sempre", async () => {
    const e = JSON.parse((await servir("/amostra/estados.json")).corpo)
    expect(e.estados.find((x: { uf: string }) => x.uf === "GO").municipios).toBe(5)
    const i = JSON.parse((await servir("/amostra/indice_AP.json")).corpo)
    expect(i.arquivos).not.toContain(`imoveis_${COM_LISTA}.csv`)
    expect(e.acesso).toBe("agregado")
    expect(e.estados.every((x: { com_lista: string[] }) => x.com_lista.length === 0)).toBe(true)
    expect(i.arquivos).toContain("resumo_AP.csv")
    expect(JSON.parse((await servir("/amostra/indice_GO.json")).corpo).arquivos).toEqual(["resumo_GO.csv"])
    expect(JSON.parse((await servir("/amostra/pontos_GO.json")).corpo).uf).toBe("GO")
    expect((await servir("/amostra/pontos_TO.json")).status).toBe(404)
  })

  it("não serve ficha, CSV por imóvel, índice CAR ou busca individual no site aberto", async () => {
    const car = ler("imoveis_1504950.csv").linhas[0].cod_imovel
    for (const url of [
      `/amostra/extras_${COM_LISTA}.csv`, `/amostra/imoveis_${COM_LISTA}.csv.gz`,
      `/amostra/fichas/${car}.json`, "/amostra/car_PA.json", `/geo/imoveis_${COM_LISTA}.geojson`,
      `/@fs/${DADOS}/AP/imoveis_${COM_LISTA}.csv`,
    ]) expect((await servir(url)).status, url).toBe(404)
    const busca = JSON.parse((await servir(`/busca?q=${car.slice(0, 16)}`)).corpo)
    expect(busca.imoveis).toEqual([])
    expect(JSON.parse((await servir("/busca?q=Município")).corpo).municipios.length).toBeGreaterThan(0)
  })

  it("a leitura interna ainda acha CAR que o motor pôs no município vizinho", async () => {
    const doVizinho = ler("imoveis_1504950.csv").linhas.find((l) => !l.cod_imovel.startsWith("PA-1504950-"))!.cod_imovel
    const pasta = abrirPasta({ repo: REPO, raizDados: null, cache: path.join(temp, "cache-vizinho") })
    expect((await pasta.foraDoMunicipio("PA"))[doVizinho]).toBe("1504950")
    expect((await pasta.ficha(doVizinho))?.imovel.cod_imovel).toBe(doVizinho)
  })

  it("o CSV também sai comprimido (.csv.gz, como o site estático guarda), limpo do mesmo jeito", async () => {
    const r = await servir("/amostra/resumo_AP.csv.gz")
    expect(r.status).toBe(200)
    expect([r.bruto[0], r.bruto[1]]).toEqual([0x1f, 0x8b])
    const texto = gunzipSync(r.bruto).toString("utf8")
    expect(texto).toBe((await servir("/amostra/resumo_AP.csv")).corpo)
    expect(texto).not.toContain(CPF)
    expect((await servir("/amostra/resumo_XX.csv.gz")).status).toBe(404)
  })

  it("o navegador lê o CSV comprimido ou já descomprimido pelo servidor", async () => {
    const original = globalThis.fetch
    const csv = "cod_imovel,ha\nAP-1600055-A,10\n"
    try {
      for (const corpo of [gzipSync(csv), Buffer.from(csv)]) {
        globalThis.fetch = (async () => new Response(corpo, { headers: { "content-type": "application/gzip" } })) as typeof fetch
        expect(await buscarTextoGz("/amostra/x.csv.gz")).toBe(csv)
      }
      globalThis.fetch = (async () => new Response("", { status: 404 })) as typeof fetch
      expect(await buscarTextoGz("/amostra/y.csv.gz")).toBeNull()
    } finally {
      globalThis.fetch = original
    }
  })

  it("nome de arquivo com caminho não sai da pasta", async () => {
    expect((await servir("/amostra/..%2F..%2F.env")).status).toBe(404)
    expect((await servir("/amostra/resumo_XX.csv")).status).toBe(404)
  })
})

describe("leitor de CSV rápido", () => {
  it("o caminho rápido e o de aspas dão o mesmo resultado", () => {
    const texto = '﻿a,b,c\r\n1,"x, y",3\n\n4,"diz ""oi""",6\r\n7,"duas\nlinhas",9\n10,11,12'
    expect(lerCsv(texto).linhas).toEqual([
      { a: "1", b: "x, y", c: "3" },
      { a: "4", b: 'diz "oi"', c: "6" },
      { a: "7", b: "duas\nlinhas", c: "9" },
      { a: "10", b: "11", c: "12" },
    ])
    expect(lerCsv("a,b\r1,2\r").linhas).toEqual([{ a: "1", b: "2" }])
    expect(lerCsv("a,b,c\n1,2,3\n", { colunas: ["c", "a", "z"] }).linhas).toEqual([{ a: "1", c: "3" }])
  })
})

/** o middleware do plugin, chamado como o Vite chama, devolvendo status e corpo */
function conectar(plugin: ReturnType<typeof dadosRaiz>) {
  type Middleware = (req: unknown, res: unknown, next: () => void) => void
  let middleware: Middleware | null = null
  const log = console.log
  console.log = () => {}
  plugin.configureServer({ middlewares: { use: (fn: Middleware) => (middleware = fn) } } as never)
  console.log = log
  return (url: string) =>
    new Promise<{ status: number; corpo: string; bruto: Buffer }>((ok) => {
      const res = {
        statusCode: 200,
        setHeader() {},
        end(dado?: string | Buffer) {
          const bruto = Buffer.isBuffer(dado) ? dado : Buffer.from(dado ?? "")
          ok({ status: this.statusCode, corpo: bruto.toString("utf8"), bruto })
        },
      }
      middleware!({ url, headers: {} }, res, () => ok({ status: 404, corpo: "", bruto: Buffer.alloc(0) }))
    })
}
