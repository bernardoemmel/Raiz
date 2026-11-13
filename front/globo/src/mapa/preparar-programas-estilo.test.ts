import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { LayerSpecification, Painter, StyleLayer } from "maplibre-gl"
import { estiloBase } from "./estilo"
import { camadasHexagonos } from "./camadas-hexagonos"

type Variante = Parameters<Painter["programCache"]["getProgram"]>[0]
type Configuracao = NonNullable<Variante["programConfiguration"]>
type Avaliacao = Parameters<StyleLayer["recalculate"]>[0]
const { fileURLToPath } = await vi.importActual<{ fileURLToPath(url: URL): string }>("node:url")
const { extrairProgramasNacionais } = await vi.importActual<{ extrairProgramasNacionais(): { nome: string; vertice: string; fragmento: string }[] }>(fileURLToPath(new URL("../../../compartilhado/vite-maplibre-programas.ts", import.meta.url)))
const pacote = new URL("../../node_modules/maplibre-gl/", import.meta.url)
const fonte = (caminho: string) => fileURLToPath(new URL(`src/${caminho}.ts`, pacote))
// Importações dinâmicas usam o código original e não incluem seus TS no tsc da aplicação.
const { ProgramConfiguration } = await vi.importActual<{ ProgramConfiguration: new (camada: StyleLayer, zoom: number, filtro: (nome: string) => boolean) => Configuracao }>(fonte("data/program_configuration"))
const { createStyleLayer } = await vi.importActual<{ createStyleLayer(spec: LayerSpecification, estado: object): StyleLayer }>(fonte("style/create_style_layer"))
const { EvaluationParameters } = await vi.importActual<{ EvaluationParameters: new (zoom: number) => Avaliacao }>(fonte("style/evaluation_parameters"))
beforeEach(() => { vi.stubGlobal("location", { origin: "https://raiz.example" }) })
afterEach(() => { vi.unstubAllGlobals() })

describe("variantes GPU do estilo nacional efetivo", () => {
  for (const zoom of [3.1, 3.85, 5.5]) it(`cobre cada ordem de macros do fundo, H3 e rótulos em zoom ${zoom}`, () => {
    const preparados = extrairProgramasNacionais()
    const specs = [...estiloBase("/geo/base_brasil.pmtiles", { nacional: true }).layers, ...camadasHexagonos()]
    for (const spec of specs) {
      if (!["fill", "line", "symbol"].includes(spec.type)) continue
      const camada = createStyleLayer(spec, {})
      camada.recalculate(new EvaluationParameters(zoom), [])
      if (camada.isHidden(zoom)) continue
      const configuracao = new ProgramConfiguration(camada, zoom, nome => spec.type !== "symbol" || nome.startsWith("text"))
      expect(configuracao.getBinderAttributes(), spec.id).toEqual([])
      const nome = spec.type === "symbol" ? "symbolSDF" : spec.type
      const cabecalho = ["#version 300 es", ...configuracao.defines(), "#define PROJECTION_MERCATOR", ""].join("\n")
      expect(preparados.some(p => p.nome === nome && p.vertice.startsWith(cabecalho) && p.fragmento.startsWith(cabecalho)), `${spec.id}: ${configuracao.defines().join(", ")}`).toBe(true)
      configuracao.destroy()
    }
  })
})
