import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { LayerSpecification, Painter, StyleLayer } from "maplibre-gl"
import { estiloBase } from "./estilo"
import { instalarPreparoProgramasNacionais, VERSAO_PREPARO_NACIONAL } from "./preparar-programas-nacionais"
import { COR } from "../../../compartilhado/cores"
import { SHADER_SIMBOLO } from "./shader-simbolo.generated"

type Variante = Parameters<Painter["programCache"]["getProgram"]>[0]
type Configuracao = NonNullable<Variante["programConfiguration"]>
type Contexto = Parameters<Configuracao["getUniforms"]>[0]
type Argumentos = Parameters<Painter["render"]>
type Avaliacao = Parameters<StyleLayer["recalculate"]>[0]
type Bucket = { programConfigurations?: { get(id: string): Configuracao }; text?: { programConfigurations: { get(id: string): Configuracao } }; createArrays?(): void; iconsInText?: boolean }

// As implementações são as do pacote instalado, inclusive o gerador de buffers e a
// transferência worker. Caminhos dinâmicos evitam incluir os TS internos no tsc da aplicação.
const { readFileSync } = await vi.importActual<{ readFileSync(arquivo: URL, codificacao: "utf8"): string }>("node:fs")
const { fileURLToPath } = await vi.importActual<{ fileURLToPath(url: URL): string }>("node:url")
const { gerarShaderSimbolo } = await vi.importActual<{ gerarShaderSimbolo(codigo: string, versao: string): typeof SHADER_SIMBOLO }>(fileURLToPath(new URL("../../../compartilhado/gerar-shader-simbolo.ts", import.meta.url)))
const pacote = new URL("../../node_modules/maplibre-gl/", import.meta.url)
const fonte = (caminho: string) => fileURLToPath(new URL(`src/${caminho}.ts`, pacote))
const { ProgramConfiguration } = await vi.importActual<{ ProgramConfiguration: new (camada: StyleLayer, zoom: number, filtro: (nome: string) => boolean) => Configuracao }>(fonte("data/program_configuration"))
const { createStyleLayer } = await vi.importActual<{ createStyleLayer(spec: LayerSpecification, estado: object): StyleLayer }>(fonte("style/create_style_layer"))
const { EvaluationParameters } = await vi.importActual<{ EvaluationParameters: new (zoom: number) => Avaliacao }>(fonte("style/evaluation_parameters"))
const { CollisionBoxArray } = await vi.importActual<{ CollisionBoxArray: new () => unknown }>(fonte("data/array_types.g"))
const { serialize, deserialize } = await vi.importActual<{ serialize(valor: unknown): unknown; deserialize(valor: unknown): unknown }>(fonte("util/web_worker_transfer"))
const { ProgramCache } = await vi.importActual<{ ProgramCache: new (contexto: Contexto) => Painter["programCache"] }>(fonte("webgl/program_cache"))
const { NullWebGL2RenderingContext } = await vi.importActual<{ NullWebGL2RenderingContext: new (canvas: HTMLCanvasElement) => WebGL2RenderingContext }>(fonte("util/test/null_gl"))
const { shaders } = await vi.importActual<{ shaders: { projectionMercator: Variante["projectionShaderVariant"]["prelude"] } }>(fonte("shaders/shaders"))

beforeEach(() => {
  vi.stubGlobal("location", { origin: "https://raiz.example" })
  // serialize testa instanceof ImageData; estes testes só transferem configurações de pintura.
  vi.stubGlobal("ImageData", class ImageData {})
})
afterEach(() => vi.unstubAllGlobals())

function camadaReal(spec: LayerSpecification, zoom: number): StyleLayer {
  const camada = createStyleLayer(spec, {})
  camada.recalculate(new EvaluationParameters(zoom), [])
  return camada
}

function bucketReal(camada: StyleLayer, zoom: number): Bucket {
  const parametros = { index: 0, layers: [camada], zoom, pixelRatio: 1, overscaling: 1,
    collisionBoxArray: new CollisionBoxArray(), sourceLayerIndex: 0, sourceID: camada.source }
  const bucket = camada.createBucket!(parametros as Parameters<NonNullable<StyleLayer["createBucket"]>>[0]) as Bucket
  if (camada.type === "symbol") bucket.createArrays!()
  return bucket
}

function configuracaoDoWorker(camada: StyleLayer, zoom: number): Configuracao {
  const bucket = bucketReal(camada, zoom)
  const configuracao = (camada.type === "symbol" ? bucket.text! : bucket).programConfigurations!.get(camada.id)
  return deserialize(serialize(configuracao)) as Configuracao
}

function contextoReal() {
  // Só as chamadas WebGL são dublês. ProgramCache, Program, GLSL e binders são reais.
  const gl = new NullWebGL2RenderingContext({ width: 360, height: 640 } as HTMLCanvasElement)
  vi.mocked(gl.getUniformLocation).mockImplementation((_programa, nome) => ({ nome }) as WebGLUniformLocation)
  const contexto = { gl } as Contexto
  return { gl, contexto, cache: new ProgramCache(contexto) }
}

const projecao = { name: "mercator", define: "#define PROJECTION_MERCATOR", prelude: shaders.projectionMercator }
const variante = (name: string, programConfiguration?: Configuracao): Variante => ({
  name, programConfiguration, projectionShaderVariant: projecao,
  showOverdrawInspector: false, useTerrain: false, defines: [],
})

function fontesCompiladas(gl: WebGL2RenderingContext) {
  const fontes = vi.mocked(gl.shaderSource).mock.calls.map(([, codigo]) => codigo)
  return { fragmento: fontes.at(-2)!, vertice: fontes.at(-1)! }
}

// A única normalização aceita permutar os defines HAS_UNIFORM. Todo o GLSL restante,
// inclusive projeção, qualifiers, atributos e código executável, precisa ser idêntico.
function canonico(codigo: string) {
  const prefixo = codigo.match(/^#version 300 es\n((?:#define HAS_UNIFORM_u_[A-Za-z0-9_]+\n)*)/)
  if (!prefixo) return codigo
  const defines = prefixo[1].split("\n").filter(Boolean)
  if (new Set(defines).size !== defines.length) return codigo
  return "#version 300 es\n" + defines.sort().map(define => `${define}\n`).join("") + codigo.slice(prefixo[0].length)
}

function cenario(zoom = 2, base: string | null = "https://raiz.example/geo/base_brasil.pmtiles") {
  const specs = estiloBase(base, { nacional: true }).layers
  const camadas = Object.fromEntries(specs.map(spec => [spec.id, camadaReal(spec, zoom)]))
  const buckets = Object.fromEntries(Object.values(camadas).filter(camada => camada.type !== "background")
    .map(camada => [camada.id, bucketReal(camada, zoom)]))
  let disponivel = true
  const fontes = Object.fromEntries([...new Set(Object.values(camadas).map(camada => camada.source).filter(Boolean))].map(id => [id, {
    getVisibleCoordinates: () => disponivel ? [{}] : [], getTile: () => ({ getBucket: (camada: StyleLayer) => buckets[camada.id] }),
  }]))
  const estilo = { _order: specs.map(spec => spec.id), _layers: camadas, tileManagers: fontes, map: {}, projection: { name: "mercator" } }
  const dados = { projectionShaderVariant: projecao, showOverdrawInspector: false, useSubdivision: false, isRenderingGlobe: false }
  const { gl, contexto, cache } = contextoReal()
  const nativo = vi.fn(function (this: Painter, ..._argumentos: Argumentos) { return this })
  const getProgram = vi.spyOn(cache, "getProgram")
  const pintor = { context: contexto, programCache: cache, render: nativo, renderToTexture: false } as unknown as Painter
  const mapa = { painter: pintor, version: VERSAO_PREPARO_NACIONAL }
  const argumentos = [estilo, { zoom }, dados] as unknown as Argumentos
  return { mapa, pintor, gl, contexto, cache, getProgram, nativo, camadas, buckets, estilo, dados, argumentos,
    disponibilizar(valor: boolean) { disponivel = valor }, render: () => pintor.render(...argumentos) }
}

describe("preparo nacional com configurações e shaders reais do MapLibre", () => {
  it("normaliza só flags sem valor e sem duplicatas no prefixo inicial", () => {
    const inicio = "#version 300 es\n", a = "#define HAS_UNIFORM_u_a\n", b = "#define HAS_UNIFORM_u_b\n"
    const sufixo = "#define PROJECTION_MERCATOR\nvoid main() {}\n"
    expect(canonico(inicio + b + a + sufixo)).toBe(canonico(inicio + a + b + sufixo))
    const comValor = "#define HAS_UNIFORM_u_a 1\n"
    expect(canonico(inicio + comValor + b + sufixo)).not.toBe(canonico(inicio + b + comValor + sufixo))
    expect(canonico(inicio + b + a + a + sufixo)).not.toBe(canonico(inicio + a + a + b + sufixo))
    expect(canonico(inicio + sufixo + b + a)).not.toBe(canonico(inicio + sufixo + a + b))
  })

  it("trava a versão do adaptador no mesmo fornecedor conferido pelo gerador", () => {
    const { version } = JSON.parse(readFileSync(new URL("package.json", pacote), "utf8"))
    expect(VERSAO_PREPARO_NACIONAL).toBe(version)
    expect(SHADER_SIMBOLO).toEqual(gerarShaderSimbolo(readFileSync(new URL("dist/maplibre-gl.mjs", pacote), "utf8"), version))
  })

  for (const zoom of [2, 4, 6]) it(`compila SDF idêntico ao worker e ao aquecedor no zoom ${zoom}`, () => {
    const cena = cenario(zoom)
    const referencia = cena.camadas["estados-rotulo-sem-dados"]
    const antecipada = new ProgramConfiguration(referencia, zoom, nome => nome.startsWith("text"))
    for (const id of ["estados-rotulo-sem-dados", "estados-rotulo"]) {
      const recebida = configuracaoDoWorker(cena.camadas[id], zoom)
      expect(recebida).toBeInstanceOf(ProgramConfiguration)
      expect(recebida.cacheKey).toBe(antecipada.cacheKey)
      expect(recebida.defines()).toEqual(antecipada.defines())
      expect(recebida.getBinderUniforms()).toEqual(antecipada.getBinderUniforms())
      expect(recebida.getBinderAttributes()).toEqual([])
      const { gl, cache } = contextoReal()
      cache.getProgram(variante("symbolSDF", recebida))
      expect(fontesCompiladas(gl)).toEqual(SHADER_SIMBOLO)
    }
  })

  for (const base of [null, "https://raiz.example/geo/base_brasil.pmtiles"]) it(`prepara variantes antes do render nativo, base=${Boolean(base)}`, () => {
    const cena = cenario(2, base)
    instalarPreparoProgramasNacionais(cena.mapa)
    cena.render()
    expect(cena.getProgram.mock.calls.map(([v]) => v.name)).toEqual(["clippingMask", "fill", "line", "symbolSDF"])
    expect(cena.getProgram.mock.invocationCallOrder.at(-1)).toBeLessThan(cena.nativo.mock.invocationCallOrder[0])
    expect(cena.nativo).toHaveBeenCalledExactlyOnceWith(...cena.argumentos)
    expect(cena.nativo.mock.contexts[0]).toBe(cena.pintor)
    expect(cena.pintor.render).toBe(cena.nativo)
    expect(cena.gl.drawElements).not.toHaveBeenCalled()
    expect(cena.gl.clear).not.toHaveBeenCalled()
    const antecipadas = new Map(cena.getProgram.mock.calls.map(([v]) => [v.name, v]))
    for (const camada of Object.values(cena.camadas).filter(camada => ["fill", "line", "symbol"].includes(camada.type))) {
      const nome = camada.type === "symbol" ? "symbolSDF" : camada.type
      const recebida = configuracaoDoWorker(camada, 2)
      const { gl, cache } = contextoReal()
      cache.getProgram(antecipadas.get(nome)!)
      const fontesAntecipadas = fontesCompiladas(gl)
      const outro = contextoReal()
      outro.cache.getProgram(variante(nome, recebida))
      const fontesDoBucket = fontesCompiladas(outro.gl)
      expect(canonico(fontesAntecipadas.fragmento)).toEqual(canonico(fontesDoBucket.fragmento))
      expect(canonico(fontesAntecipadas.vertice)).toEqual(canonico(fontesDoBucket.vertice))
      const compilações = vi.mocked(cena.gl.createProgram).mock.calls.length
      const preparado = cena.cache.getProgram(antecipadas.get(nome)!)
      expect(cena.cache.getProgram(variante(nome, recebida))).toBe(preparado)
      expect(cena.gl.createProgram).toHaveBeenCalledTimes(compilações)
    }
  })

  it("o bucket real aplica cor e opacidade atuais por nome no programa preparado", () => {
    const cena = cenario()
    instalarPreparoProgramasNacionais(cena.mapa)
    cena.render()
    const camada = cena.camadas["estados-rotulo"]
    const recebida = configuracaoDoWorker(camada, 2)
    const programa = cena.cache.getProgram(variante("symbolSDF", recebida))
    // A ordem dos binders do programa não precisa coincidir com a do bucket atual.
    const uniforms = [...programa.binderUniforms].reverse()
    const pintar = () => recebida.setUniforms(cena.contexto, uniforms, camada.paint, { zoom: 2 })
    pintar()
    camada.setPaintProperty("text-color", COR.urucum)
    camada.setPaintProperty("text-opacity", 0.37)
    camada.updateTransitions({ now: 0, transition: { duration: 0, delay: 0 } })
    camada.recalculate(new EvaluationParameters(2), [])
    vi.mocked(cena.gl.uniform4f).mockClear()
    vi.mocked(cena.gl.uniform1f).mockClear()
    pintar()
    expect(cena.gl.uniform4f).toHaveBeenCalledWith({ nome: "u_fill_color" }, 194 / 255, 82 / 255, 26 / 255, 1)
    expect(cena.gl.uniform1f).toHaveBeenCalledWith({ nome: "u_opacity" }, 0.37)
    expect(cena.gl.createProgram).toHaveBeenCalledTimes(4)
  })
})

describe("ciclo de vida e recusa do adaptador privado", () => {
  it("espera um bucket em renders naturais e restaura depois do preparo", () => {
    const cena = cenario()
    cena.disponibilizar(false)
    instalarPreparoProgramasNacionais(cena.mapa)
    const adaptado = cena.pintor.render
    cena.render()
    expect(cena.getProgram).not.toHaveBeenCalled()
    expect(cena.nativo).toHaveBeenCalledTimes(1)
    expect(cena.pintor.render).toBe(adaptado)
    cena.disponibilizar(true)
    cena.render()
    cena.render()
    expect(cena.getProgram).toHaveBeenCalledTimes(4)
    expect(cena.nativo).toHaveBeenCalledTimes(3)
    expect(cena.pintor.render).toBe(cena.nativo)
  })

  it("a limpeza pendente não compila nem sobrescreve outro adaptador", () => {
    const cena = cenario()
    const limpar = instalarPreparoProgramasNacionais(cena.mapa)
    limpar()
    limpar()
    cena.render()
    expect(cena.getProgram).not.toHaveBeenCalled()
    const outraLimpeza = instalarPreparoProgramasNacionais(cena.mapa)
    const posterior = vi.fn()
    cena.pintor.render = posterior
    outraLimpeza()
    expect(cena.pintor.render).toBe(posterior)
  })

  it("uma versão desconhecida conserva o método original", () => {
    const cena = cenario()
    instalarPreparoProgramasNacionais({ ...cena.mapa, version: "6.16.0" })()
    expect(cena.pintor.render).toBe(cena.nativo)
    cena.render()
    expect(cena.getProgram).not.toHaveBeenCalled()
  })

  const recusas: [string, (cena: ReturnType<typeof cenario>) => void][] = [
    ["contexto perdido", cena => { vi.mocked(cena.gl.isContextLost).mockReturnValue(true) }],
    ["terreno", cena => { Object.assign(cena.estilo.map, { terrain: {} }) }],
    ["renderização em textura", cena => { Object.assign(cena.pintor, { renderToTexture: {} }) }],
    ["colisões visíveis", cena => { Object.assign(cena.estilo.map, { showCollisionBoxes: true }) }],
    ["vértices visíveis", cena => { Object.assign(cena.estilo.map, { vertices: true }) }],
    ["limites de tiles", cena => { Object.assign(cena.dados, { showTileBoundaries: true }) }],
    ["inspetor de sobreposição", cena => { cena.dados.showOverdrawInspector = true }],
    ["projeção diferente", cena => { cena.estilo.projection.name = "globe" }],
    ["subdivisão", cena => { cena.dados.useSubdivision = true }],
    ["céu visível", cena => { Object.assign(cena.dados, { sky: { "sky-color": { a: 1 }, "horizon-color": { a: 0 } } }) }],
    ["camada desconhecida", cena => { cena.estilo._order.push("detalhe-nao-conferido") }],
    ["ícone no texto", cena => { cena.buckets["estados-rotulo"].iconsInText = true }],
    ["ícone estático antes do bucket", cena => {
      cena.disponibilizar(false)
      cena.camadas["estados-rotulo"].setLayoutProperty("icon-image", "marcador")
    }],
    ["imagem formatada antes do bucket", cena => {
      cena.disponibilizar(false)
      cena.camadas["estados-rotulo"].setLayoutProperty("text-field", ["format", ["image", "marcador"], {}])
    }],
    ["cor por seção formatada antes do bucket", cena => {
      cena.disponibilizar(false)
      cena.camadas["estados-rotulo"].setLayoutProperty("text-field", ["format", "Pará", { "text-color": COR.urucum }])
    }],
    ["pintura por feição", cena => {
      const camada = cena.camadas["estados-preenchimento"]
      camada.setPaintProperty("fill-color", ["get", "cor"])
      camada.updateTransitions({ now: 0, transition: { duration: 0 } })
      camada.recalculate(new EvaluationParameters(2), [])
    }],
  ]
  for (const [nome, alterar] of recusas) it(`recusa ${nome} sem preparar parcialmente`, () => {
    const cena = cenario()
    alterar(cena)
    instalarPreparoProgramasNacionais(cena.mapa)
    cena.render()
    expect(cena.getProgram).not.toHaveBeenCalled()
    expect(cena.nativo).toHaveBeenCalledExactlyOnceWith(...cena.argumentos)
    expect(cena.pintor.render).toBe(cena.nativo)
  })

  it("devolve erros de preparo ao caminho nativo e preserva seu diagnóstico", () => {
    const cena = cenario()
    cena.getProgram.mockImplementation(() => { throw new Error("falha de link") })
    const erroNativo = new Error("diagnóstico nativo de GL")
    cena.nativo.mockImplementation(() => { throw erroNativo })
    instalarPreparoProgramasNacionais(cena.mapa)
    expect(cena.render).toThrow(erroNativo)
    expect(cena.pintor.render).toBe(cena.nativo)
    expect(cena.nativo).toHaveBeenCalledTimes(1)
  })
})
