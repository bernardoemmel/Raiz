import fs from "node:fs"
import path from "node:path"
import { describe, expect, it } from "vitest"
import { lerCsv } from "../dados/csv"
import { buscar } from "../dados/busca"
import { complementosDe, juntarComplementos } from "../dados/complementos"
import { lerFunil, lerImovel } from "../dados/funil"
import { fmtInt } from "../formato"
import { etapasDoFunil, etapasDoResumo, fraseDoBrasil, noFoco, numerosDoBrasil } from "../funil-etapas"
import { nomeProprio, pontoDentro, rotulosDeAreas } from "../rotulos-mapa"
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
    expect(etapas.map((e) => e.total.n)).toEqual([resumo.imoveis, resumo.sem_problema, resumo.aptas_carbono, resumo.aptas_com_matricula])
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

describe("frase da tela de entrada", () => {
  const resumo = ler("resumo_PA.csv").map((l) => lerFunil(l, "PA"))
  const n = numerosDoBrasil(resumo)
  const frase = fraseDoBrasil(n, ["Pará"], fmtInt)
  const numero = (re: RegExp) => Number(frase.match(re)?.[1].replace(/\./g, ""))

  it("prontas para conversar e as que só falta o título somam o número de Fazendas aptas", () => {
    const prontas = numero(/([\d.]+) fazendas? estão prontas para conversar/)
    const faltaTitulo = numero(/outras? ([\d.]+) passam? em tudo, mas ainda falta o título/)
    expect(prontas).toBe(n.prontas)
    expect(faltaTitulo).toBe(n.faltaTitulo)
    expect(prontas + faltaTitulo).toBe(n.aptas)
    // e bate com o resumo do motor: aptas = aptas_carbono; prontas = aptas_com_matricula
    expect(n.aptas).toBe(resumo.reduce((s, m) => s + m.aptas_carbono, 0))
    expect(n.prontas).toBe(resumo.reduce((s, m) => s + m.aptas_com_matricula, 0))
    expect(frase).toContain(`${fmtInt(n.municipios)} municípios (Pará)`)
    expect(frase).not.toMatch(/título em dia/)
  })

  it("singular, plural e nenhuma pendência", () => {
    const base = { municipios: 1, imoveis: 10, aptas: 3, prontas: 1, faltaTitulo: 2, ha: 5 }
    expect(fraseDoBrasil(base, ["Pará"], fmtInt)).toBe(
      "A Raíz já leu 1 município (Pará): 10 imóveis do Cadastro Ambiental Rural (CAR). 1 fazenda está pronta para conversar e outras 2 passam em tudo, mas ainda falta o título.",
    )
    expect(fraseDoBrasil({ ...base, aptas: 2, faltaTitulo: 1 }, ["Pará"], fmtInt)).toContain("e outra 1 passa em tudo")
    expect(fraseDoBrasil({ ...base, aptas: 1, faltaTitulo: 0 }, ["Pará"], fmtInt)).toMatch(/1 fazenda está pronta para conversar\.$/)
  })
})

describe("áreas sem imóvel do CAR no mapa", () => {
  it("escreve o nome da unidade de conservação como gente escreve", () => {
    expect(nomeProprio("ÁREA DE PROTEÇÃO AMBIENTAL TRIUNFO DO XINGU")).toBe("Área de Proteção Ambiental Triunfo do Xingu")
    expect(nomeProprio("FLORESTA NACIONAL DE TAPIRAPÉ-AQUIRI")).toBe("Floresta Nacional de Tapirapé-Aquiri")
    expect(nomeProprio("Capoto/Jarina")).toBe("Capoto/Jarina")
  })

  it("o nome fica dentro da área, mesmo em forma de U", () => {
    // um U: o centro da caixa (5, 5) cai fora
    const u = { type: "Polygon", coordinates: [[[0, 0], [10, 0], [10, 10], [7, 10], [7, 3], [3, 3], [3, 10], [0, 10], [0, 0]]] }
    const [x, y] = pontoDentro(u)!
    expect(dentro([x, y], u.coordinates[0] as [number, number][])).toBe(true)
    const r = rotulosDeAreas(
      { type: "FeatureCollection", features: [{ type: "Feature", properties: { nome: "Kayapó" }, geometry: u }] },
      { type: "FeatureCollection", features: [{ type: "Feature", properties: { nome: "PARQUE ESTADUAL DO XINGU" }, geometry: u }] },
    )
    expect(r.features.map((f) => f.properties.rotulo)).toEqual(["Terra indígena Kayapó", "Parque Estadual do Xingu"])
  })

  // as geometrias geradas por front/scripts/geo.py (fora do git): só confere quando existem
  const GEO = path.resolve(FRONT, "geo")
  for (const cod of ["1507300", "1504950"])
    it.skipIf(!fs.existsSync(path.join(GEO, `municipio_${cod}.geojson`)))(`terra indígena e unidade de conservação não passam da divisa (${cod})`, () => {
      const lerGeo = (n: string) => JSON.parse(fs.readFileSync(path.join(GEO, `${n}_${cod}.geojson`), "utf8"))
      const divisa = aneisDe(lerGeo("municipio").features[0].geometry)
      for (const camada of ["ti", "uc"]) {
        if (!fs.existsSync(path.join(GEO, `${camada}_${cod}.geojson`))) continue
        let fora = 0
        for (const f of lerGeo(camada).features)
          for (const anel of aneisDe(f.geometry)) for (const p of anel) if (!divisa.some((d) => dentro(p, d)) && distancia(p, divisa) > 2e-4) fora++
        expect(fora, camada).toBe(0)
      }
    })
})

/** os anéis externos de um Polygon ou MultiPolygon */
function aneisDe(g: { type: string; coordinates: unknown }): [number, number][][] {
  if (g.type === "Polygon") return [(g.coordinates as [number, number][][])[0]]
  if (g.type === "MultiPolygon") return (g.coordinates as [number, number][][][]).map((p) => p[0])
  return []
}
function dentro([x, y]: [number, number], anel: [number, number][]): boolean {
  let sim = false
  for (let i = 0, j = anel.length - 1; i < anel.length; j = i++) {
    const [xi, yi] = anel[i]
    const [xj, yj] = anel[j]
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) sim = !sim
  }
  return sim
}
function distancia([x, y]: [number, number], aneis: [number, number][][]): number {
  let d = Infinity
  for (const a of aneis)
    for (let i = 0; i + 1 < a.length; i++) {
      const [ax, ay] = a[i]
      const [bx, by] = a[i + 1]
      const l = (bx - ax) ** 2 + (by - ay) ** 2
      const t = l ? Math.max(0, Math.min(1, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / l)) : 0
      d = Math.min(d, Math.hypot(x - (ax + t * (bx - ax)), y - (ay + t * (by - ay))))
    }
  return d
}
