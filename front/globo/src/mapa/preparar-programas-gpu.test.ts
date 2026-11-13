import { describe, expect, it, vi } from "vitest"
import { prepararProgramasGpu } from "./preparar-programas-gpu"

const fontes = [{ nome: "fill", vertice: "vertice real", fragmento: "fragmento real" }]
function contexto() {
  return {
    VERTEX_SHADER: 35633, FRAGMENT_SHADER: 35632, LINK_STATUS: 35714,
    isContextLost: vi.fn(() => false), createProgram: vi.fn(() => ({})), createShader: vi.fn(() => ({})),
    shaderSource: vi.fn(), compileShader: vi.fn(), attachShader: vi.fn(), linkProgram: vi.fn(),
    getProgramParameter: vi.fn(() => true), deleteProgram: vi.fn(), deleteShader: vi.fn(), finish: vi.fn(),
  }
}
describe("preparação GPU fora da interface", () => {
  it("consulta o resultado real e retém apenas programas válidos até o worker encerrar", () => {
    const gl = contexto(), resultado = prepararProgramasGpu(gl as unknown as WebGL2RenderingContext, fontes)
    expect(resultado).toHaveLength(1)
    expect(gl.shaderSource.mock.calls.map(c => c[1])).toEqual(["vertice real", "fragmento real"])
    expect(gl.linkProgram).toHaveBeenCalledOnce()
    expect(gl.getProgramParameter).toHaveBeenCalledWith(resultado[0], gl.LINK_STATUS)
    expect(gl.deleteShader).toHaveBeenCalledTimes(2)
    expect(gl.deleteProgram).not.toHaveBeenCalled()
    expect(gl.finish).toHaveBeenCalledOnce()
  })
  it("libera programas recusados e continua sem substituir a compilação nativa", () => {
    const gl = contexto(); gl.getProgramParameter.mockReturnValue(false)
    expect(prepararProgramasGpu(gl as unknown as WebGL2RenderingContext, fontes)).toEqual([])
    expect(gl.deleteProgram).toHaveBeenCalledOnce()
    expect(gl.deleteShader).toHaveBeenCalledTimes(2)
  })
  it("libera recursos em exceção do driver", () => {
    const gl = contexto(); gl.compileShader.mockImplementation(() => { throw new Error("contexto perdido") })
    expect(prepararProgramasGpu(gl as unknown as WebGL2RenderingContext, fontes)).toEqual([])
    expect(gl.deleteProgram).toHaveBeenCalledOnce()
    expect(gl.deleteShader).toHaveBeenCalledTimes(2)
  })
  it("não inicia compilações num contexto perdido", () => {
    const gl = contexto(); gl.isContextLost.mockReturnValue(true)
    expect(prepararProgramasGpu(gl as unknown as WebGL2RenderingContext, fontes)).toEqual([])
    expect(gl.createProgram).not.toHaveBeenCalled()
    expect(gl.finish).not.toHaveBeenCalled()
  })
  it("libera programas se a conclusão do trabalho gráfico falhar", () => {
    const gl = contexto(); gl.finish.mockImplementation(() => { throw new Error("driver indisponível") })
    expect(prepararProgramasGpu(gl as unknown as WebGL2RenderingContext, fontes)).toEqual([])
    expect(gl.deleteProgram).toHaveBeenCalledOnce()
  })
})
