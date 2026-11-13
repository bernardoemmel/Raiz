/** Adaptador restrito do MapLibre 6.15.0; origem BSD-3-Clause em NOTICE.md.
 * Usa o preparador e os GLSL instalados, sem manter outra cópia de shaders no produto.
 * As variantes dos quatro tipos são as efetivamente usadas na vista nacional V2.
 */
import { createHash } from "node:crypto"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { resolve } from "node:path"
import { runInNewContext } from "node:vm"

const PUBLICO = "virtual:raiz-programas-nacionais"
const INTERNO = "\0raiz-programas-nacionais"
const VERSAO = "6.15.0"
const SHA256 = "918d150440a60e14166b1e8907837d61d35aa83f491e5f5b79c52b14c92795a7"
const PADRAO = fileURLToPath(new URL("../globo/node_modules/maplibre-gl", import.meta.url))
const NOMES = ["_prelude", "_projection_mercator", "clipping_mask", "fill", "line", "symbol_sdf"]
const ARQUIVOS = ["src/shaders/shaders.ts", "src/webgl/program.ts", ...NOMES.flatMap(nome => ["fragment", "vertex"].map(tipo => `src/shaders/glsl/${nome}.${tipo}.glsl.g.ts`))]

// A ordem também pertence ao contrato do cache do driver. Estes defines foram
// conferidos contra shaderSource e contra ProgramConfiguration das camadas reais do estilo V2.
const VARIANTES = [
  { nome: "clippingMask", arquivo: "clipping_mask", uniformes: [] },
  { nome: "fill", arquivo: "fill", uniformes: ["color", "outline_color", "opacity", "pattern_to", "pattern_from", "pixel_ratio_to", "pixel_ratio_from"] },
  { nome: "line", arquivo: "line", uniformes: ["color", "width", "opacity", "floorwidth", "gapwidth", "offset", "blur", "dasharray_to", "dasharray_from", "pattern_to", "pattern_from", "pixel_ratio_to", "pixel_ratio_from"] },
  { nome: "symbolSDF", arquivo: "symbol_sdf", uniformes: ["fill_color", "halo_width", "halo_color", "opacity", "halo_blur"] },
  // H3 explicita opacity antes de FillStyleLayer acrescentar outline_color.
  { nome: "fill", arquivo: "fill", uniformes: ["color", "opacity", "outline_color", "pattern_to", "pattern_from", "pixel_ratio_to", "pixel_ratio_from"] },
  // Países/estados põem a cor do halo antes da largura; oceanos usam a ordem inversa.
  { nome: "symbolSDF", arquivo: "symbol_sdf", uniformes: ["fill_color", "halo_color", "halo_width", "opacity", "halo_blur"] },
  // A fronteira e os H3 usam opacity padrão; floorwidth é acrescentado antes dos padrões.
  { nome: "line", arquivo: "line", uniformes: ["color", "width", "floorwidth", "opacity", "gapwidth", "offset", "blur", "dasharray_to", "dasharray_from", "pattern_to", "pattern_from", "pixel_ratio_to", "pixel_ratio_from"] },
]

export interface ProgramaNacional { nome: string; vertice: string; fragmento: string }
interface Preparado { vertexSource: string; fragmentSource: string }

/** Falha fechada no build quando a dependência muda; o app não recebe GLSL antigo. */
export function extrairProgramasNacionais(pacote = PADRAO): ProgramaNacional[] {
  const versao = JSON.parse(readFileSync(resolve(pacote, "package.json"), "utf8")).version
  const fontes = new Map(ARQUIVOS.map(arquivo => [arquivo, readFileSync(resolve(pacote, arquivo), "utf8")]))
  const hash = createHash("sha256")
  for (const [arquivo, fonte] of fontes) hash.update(`${arquivo}\0`).update(fonte)
  if (versao !== VERSAO || hash.digest("hex") !== SHA256)
    throw new Error("MapLibre diferente de 6.15.0 conferido: revise os programas nacionais e sua equivalência antes de atualizar.")
  const fonte = fontes.get("src/shaders/shaders.ts")!
  const assinatura = "function prepare(fragmentSource: string, vertexSource: string): PreparedShader"
  const inicio = fonte.indexOf(assinatura)
  if (inicio < 0 || fonte.indexOf(assinatura, inicio + 1) >= 0) throw new Error("Preparador GLSL não reconhecido.")
  // Executa somente a função conferida por hash durante o build, nunca código recebido do banco.
  const preparar = runInNewContext(`(${fonte.slice(inicio).replace(assinatura, "function prepare(fragmentSource, vertexSource)")})`, {}, { timeout: 1000 }) as (fragmento: string, vertice: string) => Preparado
  const ler = (nome: string, tipo: string): string => {
    const modulo = fontes.get(`src/shaders/glsl/${nome}.${tipo}.glsl.g.ts`)!
    return runInNewContext(modulo.slice(modulo.indexOf("export default ") + 15), {}, { timeout: 1000 }) as string
  }
  const montar = (nome: string) => preparar(ler(nome, "fragment"), ler(nome, "vertex"))
  const prelude = montar("_prelude"), projecao = montar("_projection_mercator")
  return VARIANTES.map(({ nome, arquivo, uniformes }) => {
    const programa = montar(arquivo)
    const defines = ["#version 300 es", ...uniformes.map(u => `#define HAS_UNIFORM_u_${u}`), "#define PROJECTION_MERCATOR"]
    return {
      nome,
      vertice: [...defines, prelude.vertexSource, projecao.vertexSource, programa.vertexSource].join("\n"),
      fragmento: [...defines, prelude.fragmentSource, projecao.fragmentSource, programa.fragmentSource].join("\n"),
    }
  })
}

export function maplibreProgramasNacionais() {
  return {
    name: "raiz-maplibre-programas-nacionais",
    resolveId(id: string) { return id === PUBLICO ? INTERNO : null },
    load(id: string) {
      if (id !== INTERNO) return null
      return `/* MapLibre GL JS 6.15.0, BSD-3-Clause; licença em licencas/maplibre-gl.txt. */\nexport const programasNacionais = ${JSON.stringify(extrairProgramasNacionais())};`
    },
  }
}
