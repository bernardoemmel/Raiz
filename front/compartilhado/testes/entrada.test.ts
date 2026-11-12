import fs from "node:fs"
import path from "node:path"
import { describe, expect, it } from "vitest"
import { lerCsv } from "../dados/csv"
import { buscar } from "../dados/busca"
import { complementosDe, juntarComplementos } from "../dados/complementos"
import { lerFunil, lerImovel } from "../dados/funil"
import { etapasDoFunil, etapasDoResumo, noFoco } from "../funil-etapas"
import { destinoDaBusca, lerRota, linkFazenda, linkMunicipio, municipiosSemDados, type MunicipioDoMapa } from "../../globo/src/rota"

const FRONT = path.resolve(__dirname, "../..")
const AMOSTRA = path.resolve(FRONT, "../dados/amostra")
const ler = (arq: string) => lerCsv(fs.readFileSync(path.join(AMOSTRA, arq), "utf8")).linhas
const carregar = (cod: string) => {
  const nomes = complementosDe(fs.readdirSync(AMOSTRA), cod)
  const { porImovel } = juntarComplementos(nomes.map((arquivo) => ({ arquivo, linhas: ler(arquivo) })))
  return ler(`imoveis_${cod}.csv`).map((l) => lerImovel(l, porImovel.get(l.cod_imovel)))
}

/** todos os arquivos de código de um diretório, sem node_modules nem build */
function arquivos(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) return ["node_modules", "dist", "geo", "prints", "referencia"].includes(e.name) ? [] : arquivos(p)
    return /\.(tsx?|jsx?|mjs|css|html|json)$/.test(e.name) ? [p] : []
  })
}

describe("tela de entrada sem globo", () => {
  it("nenhum app depende do cobe", () => {
    for (const app of ["globo", "produtor"]) {
      const pkg = JSON.parse(fs.readFileSync(path.join(FRONT, app, "package.json"), "utf8"))
      expect({ ...pkg.dependencies, ...pkg.devDependencies }, app).not.toHaveProperty("cobe")
      const trava = path.join(FRONT, app, "package-lock.json")
      if (fs.existsSync(trava)) expect(fs.readFileSync(trava, "utf8"), `${app}/package-lock.json`).not.toMatch(/node_modules\/cobe"/)
    }
  })

  it("nenhum código do front importa o cobe nem monta o globo", () => {
    const achados = [path.join(FRONT, "globo"), path.join(FRONT, "produtor"), path.join(FRONT, "compartilhado")]
      .flatMap(arquivos)
      .filter((a) => !a.endsWith("entrada.test.ts") && !a.endsWith("package-lock.json"))
      .filter((a) => /from ["']cobe["']|import\(["']cobe["']\)|createGlobe|Pular abertura/.test(fs.readFileSync(a, "utf8")))
    expect(achados).toEqual([])
    expect(fs.existsSync(path.join(FRONT, "globo/src/components/cobe-globe.tsx"))).toBe(false)
  })
})

describe("rotas", () => {
  it("sem nada no endereço abre o Brasil; município e fazenda pelo código", () => {
    expect(lerRota("")).toEqual({ tela: "entrada" })
    expect(lerRota("#/")).toEqual({ tela: "entrada" })
    expect(lerRota("#/abertura")).toEqual({ tela: "entrada" })
    expect(lerRota(linkMunicipio("1507300"))).toEqual({ tela: "municipio", municipio: "1507300" })
    expect(lerRota("#/municipio/150730")).toEqual({ tela: "entrada" })
    const car = "PA-1507300-F293CD17B5FE4D4682CB436FF5B136D0"
    expect(lerRota(linkFazenda(car))).toEqual({ tela: "fazenda", car })
  })
})

describe("busca leva ao lugar certo", () => {
  const imoveis = [...carregar("1504950"), ...carregar("1507300")]
  const municipios = ler("resumo_PA.csv").map((l) => lerFunil(l, "PA"))
  const base = { municipios, imoveis, comImoveis: new Set(["1504950", "1507300"]) }
  const mapa: MunicipioDoMapa[] = [
    { cod_ibge: "1507300", nome: "São Félix do Xingu", uf: "PA" },
    { cod_ibge: "5107909", nome: "Sinop", uf: "MT" },
    { cod_ibge: "5107958", nome: "Tangará da Serra", uf: "MT" },
    { cod_ibge: "4205407", nome: "Florianópolis", uf: "SC" },
  ]
  const conhecidos = (q: string) => new Set(buscar(q, base).municipios.map((m) => m.cod_ibge))

  it("código do CAR vai direto para a ficha, de qualquer município", () => {
    for (const car of [
      "PA-1504950-508C67099D164E0581650983A8CC2059",
      "PA-1507300-F293CD17B5FE4D4682CB436FF5B136D0",
      "PA-1504208-B000CE16276348319BBA474ACFB35A67",
    ])
      expect(destinoDaBusca(buscar(car, base))).toBe(linkFazenda(car))
  })

  it("município vai para o mapa dele", () => {
    expect(destinoDaBusca(buscar("são félix do xingu", base))).toBe("#/municipio/1507300")
    expect(destinoDaBusca(buscar("Nova Esperança do Piriá", base))).toBe("#/municipio/1504950")
    // só com o resumo (sem lista por fazenda): também vai, e o painel avisa
    expect(destinoDaBusca(buscar("altamira", base))).toBe("#/municipio/1500602")
  })

  it("município de estado ainda não processado também vai para o mapa (igual a tocar nele)", () => {
    const r = buscar("sinop", base)
    expect(r.situacao).toBe("nao_encontrado")
    const semDados = municipiosSemDados("sinop", mapa, conhecidos("sinop"))
    expect(semDados.map((m) => m.cod_ibge)).toEqual(["5107909"])
    expect(destinoDaBusca(r, semDados)).toBe("#/municipio/5107909")
    // o que a busca do back-end já conhece não se repete
    expect(municipiosSemDados("são félix", mapa, conhecidos("são félix"))).toEqual([])
    // código do CAR e texto curto não procuram no mapa
    expect(municipiosSemDados("MT-5107909", mapa, new Set())).toEqual([])
    expect(municipiosSemDados("si", mapa, new Set())).toEqual([])
  })

  it("com mais de um resultado, a pessoa escolhe na lista", () => {
    expect(destinoDaBusca(buscar("xingu", base))).toBeNull()
    expect(destinoDaBusca(buscar("PA-1507300", base))).toBeNull()
  })
})

describe("funil em barras", () => {
  const imoveis = carregar("1507300")
  const resumo = lerFunil(ler("resumo_PA.csv").find((l) => l.cod_ibge === "1507300")!, "PA")
  const etapas = etapasDoFunil(imoveis)

  it("as barras batem com o resumo do motor, e quem sai em cada etapa soma a diferença", () => {
    // a terra não corta: o caminho da terra tem as mesmas aptas, divididas em pronta agora, em espera e só mostrar
    expect(etapas.map((e) => e.total.n)).toEqual([resumo.imoveis, resumo.sem_problema, resumo.aptas_carbono, resumo.aptas_carbono])
    const terra = etapas[3].terra!
    expect((terra.pronta_agora?.n ?? 0) + (terra.em_espera?.n ?? 0) + (terra.so_mostrar?.n ?? 0)).toBe(resumo.aptas_carbono)
    for (let k = 1; k < etapas.length; k++) {
      const saiu = etapas[k].perdas.reduce((s, p) => s + p.n, 0)
      expect(saiu, etapas[k].id).toBe(etapas[k - 1].total.n - etapas[k].total.n)
    }
    expect(etapasDoResumo(resumo).map((e) => e.total.n)).toEqual(etapas.map((e) => e.total.n))
  })

  it("tocar na barra deixa no mapa só quem chegou ali; no contorno, só quem saiu", () => {
    for (const e of etapas) {
      const dentro = imoveis.filter((i) => noFoco(i, { etapa: e.id, lado: "dentro" })).length
      expect(dentro, e.id).toBe(e.total.n)
    }
    const fora = imoveis.filter((i) => noFoco(i, { etapa: etapas[1].id, lado: "fora" })).length
    expect(fora).toBe(etapas[0].total.n - etapas[1].total.n)
    expect(imoveis.filter((i) => noFoco(i, null)).length).toBe(imoveis.length)
  })
})
