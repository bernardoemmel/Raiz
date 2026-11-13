/** Gera a variante nacional a partir dos shaders BSD-3-Clause do MapLibre conferido.
 * Usa o preparador do próprio fornecedor: nenhuma segunda implementação de GLSL.
 * Os bytes são conferidos antes de executar o bloco puro de constantes/preparação.
 */
import { createHash } from "node:crypto"

const VERSAO = "6.15.0"
const SHA256 = "41198b23679a7d8892183408bbef2eabdc74745beb90261f6be0f660b7aeb2fd"
const DEFINES = [
  "#version 300 es", "#define HAS_UNIFORM_u_fill_color", "#define HAS_UNIFORM_u_halo_color",
  "#define HAS_UNIFORM_u_halo_width", "#define HAS_UNIFORM_u_opacity", "#define HAS_UNIFORM_u_halo_blur",
  "#define PROJECTION_MERCATOR",
]

export function gerarShaderSimbolo(codigo: string, versao: string): { fragmento: string; vertice: string } {
  if (versao !== VERSAO || createHash("sha256").update(codigo).digest("hex") !== SHA256)
    throw new Error("MapLibre diferente de 6.15.0 conferido: revise o aquecimento do símbolo antes de atualizar.")
  const inicio = codigo.indexOf("dO=`#ifdef GL_ES"), fim = codigo.indexOf("const SO=", inicio)
  if (inicio < 0 || fim < inicio) throw new Error("Bloco de shaders do MapLibre não encontrado.")
  const shaders = new Function(`const ${codigo.slice(inicio, fim)};return {prelude:bO.prelude,projecao:bO.projectionMercator,simbolo:bO.symbolSDF};`)() as
    Record<"prelude" | "projecao" | "simbolo", { fragmentSource: string; vertexSource: string }>
  const fonte = (campo: "fragmentSource" | "vertexSource") => [...DEFINES, shaders.prelude[campo], shaders.projecao[campo], shaders.simbolo[campo]].join("\n")
  return { fragmento: fonte("fragmentSource"), vertice: fonte("vertexSource") }
}

export function arquivoShaderSimbolo(codigo: string, versao: string): string {
  return `/** Gerado por front/scripts/gerar-shader-simbolo.mjs; não editar à mão.
 * MapLibre GL JS ${VERSAO}, BSD-3-Clause. Licença completa: licencas/maplibre-gl.txt.
 * symbolSDF, Mercator, cores uniformes; mesmos bytes usados pelo mapa nacional.
 */
export const SHADER_SIMBOLO = ${JSON.stringify(gerarShaderSimbolo(codigo, versao), null, 2)} as const\n`
}
