import { SHADER_SIMBOLO } from "./shader-simbolo.generated"

/** Trabalho real fora da interface; a falta de recursos gráficos mantém o caminho normal do mapa. */
export function aquecerSimbolo(gl: WebGL2RenderingContext): WebGLProgram | null {
  const programa = gl.createProgram()
  if (!programa) return null
  const shaders: WebGLShader[] = []
  try {
    for (const [tipo, fonte] of [[gl.FRAGMENT_SHADER, SHADER_SIMBOLO.fragmento], [gl.VERTEX_SHADER, SHADER_SIMBOLO.vertice]] as const) {
      const shader = gl.createShader(tipo)
      if (!shader) throw new Error("Shader indisponível")
      shaders.push(shader)
      gl.shaderSource(shader, fonte)
      gl.compileShader(shader)
      gl.attachShader(programa, shader)
    }
    gl.linkProgram(programa)
    if (!gl.getProgramParameter(programa, gl.LINK_STATUS)) throw new Error("Programa indisponível")
    gl.finish()
    return programa
  } catch {
    gl.deleteProgram(programa)
    return null
  } finally {
    // O programa conserva os shaders anexados até o contexto do worker ser liberado.
    for (const shader of shaders) gl.deleteShader(shader)
  }
}
