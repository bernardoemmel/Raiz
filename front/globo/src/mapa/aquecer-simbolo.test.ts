import { afterEach, describe, expect, it, vi } from "vitest"
import { aquecerSimbolo } from "./aquecer-simbolo"
import { SHADER_SIMBOLO } from "./shader-simbolo.generated"

function contexto(link = true) {
  const programa = {}, shaders = [{}, {}], chamadas: string[] = []
  const gl = {
    FRAGMENT_SHADER: 35632, VERTEX_SHADER: 35633, LINK_STATUS: 35714,
    createProgram: vi.fn(() => programa), createShader: vi.fn().mockReturnValueOnce(shaders[0]).mockReturnValueOnce(shaders[1]),
    shaderSource: vi.fn(), compileShader: vi.fn(() => chamadas.push("compilar")), attachShader: vi.fn(),
    linkProgram: vi.fn(() => chamadas.push("linkar")), getProgramParameter: vi.fn(() => { chamadas.push("conferir"); return link }),
    finish: vi.fn(() => chamadas.push("concluir")), deleteProgram: vi.fn(), deleteShader: vi.fn(),
  }
  return { gl, programa, shaders, chamadas }
}

afterEach(() => vi.unstubAllGlobals())
describe("aquecimento real de símbolo fora da interface", () => {
  it("compila ambos shaders antes do link e conserva só o programa até o mapa assumir", () => {
    const { gl, programa, shaders, chamadas } = contexto()
    expect(aquecerSimbolo(gl as unknown as WebGL2RenderingContext)).toBe(programa)
    expect(gl.shaderSource.mock.calls).toEqual([[shaders[0], SHADER_SIMBOLO.fragmento], [shaders[1], SHADER_SIMBOLO.vertice]])
    expect(chamadas).toEqual(["compilar", "compilar", "linkar", "conferir", "concluir"])
    expect(gl.deleteProgram).not.toHaveBeenCalled()
    expect(gl.deleteShader.mock.calls).toEqual(shaders.map(s => [s]))
  })
  it.each(["link", "shader", "excecao"])("libera recursos e mantém o caminho normal quando falha %s", falha => {
    const { gl, programa, shaders } = contexto(false)
    if (falha === "shader") gl.createShader.mockReset().mockReturnValueOnce(shaders[0]).mockReturnValueOnce(null)
    if (falha === "excecao") gl.compileShader.mockImplementation(() => { throw new Error("Contexto perdido") })
    expect(aquecerSimbolo(gl as unknown as WebGL2RenderingContext)).toBeNull()
    expect(gl.deleteProgram).toHaveBeenCalledWith(programa)
    expect(gl.deleteShader).toHaveBeenCalledWith(shaders[0])
    expect(gl.finish).not.toHaveBeenCalled()
  })
  it.each([null, "erro"])("avisa pronto mesmo sem contexto (%s), sem bloquear o MapLibre", async falha => {
    vi.resetModules()
    vi.stubGlobal("OffscreenCanvas", class { getContext() { if (falha) throw new Error("WebGL indisponível"); return null } })
    const postMessage = vi.fn()
    vi.stubGlobal("postMessage", postMessage)
    await import("./preparar-gpu.worker")
    expect(postMessage).toHaveBeenCalledWith({ pronto: true })
  })
})
