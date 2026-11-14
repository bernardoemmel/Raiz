/** O contexto já pertence ao worker. O renderizador mantém sua compilação normal como fallback. */
export interface FonteProgramaGpu { nome: string; vertice: string; fragmento: string }

export function prepararProgramasGpu(gl: WebGL2RenderingContext, fontes: readonly FonteProgramaGpu[]): WebGLProgram[] {
  const programas: WebGLProgram[] = []
  for (const fonte of fontes) {
    if (gl.isContextLost()) break
    const programa = gl.createProgram()
    const vertice = gl.createShader(gl.VERTEX_SHADER), fragmento = gl.createShader(gl.FRAGMENT_SHADER)
    if (!programa || !vertice || !fragmento) {
      if (programa) gl.deleteProgram(programa)
      if (vertice) gl.deleteShader(vertice)
      if (fragmento) gl.deleteShader(fragmento)
      continue
    }
    try {
      gl.shaderSource(vertice, fonte.vertice)
      gl.shaderSource(fragmento, fonte.fragmento)
      gl.compileShader(vertice)
      gl.compileShader(fragmento)
      gl.attachShader(programa, fragmento)
      gl.attachShader(programa, vertice)
      gl.linkProgram(programa)
      // A espera fica no worker; nunca falsifica LINK_STATUS ou intercepta o renderizador.
      if (gl.getProgramParameter(programa, gl.LINK_STATUS)) programas.push(programa)
      else gl.deleteProgram(programa)
    } catch { gl.deleteProgram(programa) }
    finally { gl.deleteShader(vertice); gl.deleteShader(fragmento) }
  }
  try { if (programas.length) gl.finish() }
  catch { for (const programa of programas) gl.deleteProgram(programa); return [] }
  return programas
}
