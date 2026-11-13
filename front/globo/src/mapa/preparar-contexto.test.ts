import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

class WorkerTeste {
  static criados: WorkerTeste[] = []
  onmessage?: (evento: { data: unknown }) => void
  onerror?: () => void
  onmessageerror?: () => void
  terminate = vi.fn()
  constructor() { WorkerTeste.criados.push(this) }
}
beforeEach(() => { vi.resetModules(); vi.useFakeTimers(); WorkerTeste.criados = []; vi.stubGlobal("Worker", WorkerTeste); vi.stubGlobal("OffscreenCanvas", class {}) })
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

describe("preparação não bloqueante do contexto gráfico", () => {
  it("compartilha o trabalho entre download e montagem e retém o worker até a liberação explícita", async () => {
    const { prepararContextoMapa } = await import("./preparar-contexto")
    const primeiro = prepararContextoMapa(), segundo = prepararContextoMapa()
    expect(primeiro).toBe(segundo)
    expect(WorkerTeste.criados).toHaveLength(1)
    const worker = WorkerTeste.criados[0]
    worker.onmessage?.({ data: { pronto: true } })
    const liberar = await primeiro
    expect(worker.terminate).not.toHaveBeenCalled()
    liberar(); liberar()
    expect(worker.terminate).toHaveBeenCalledTimes(1)
    const proximo = prepararContextoMapa()
    expect(WorkerTeste.criados).toHaveLength(2)
    WorkerTeste.criados[1].onmessage?.({ data: { pronto: true } })
    ;(await proximo)()
  })
  it("não impede o caminho nativo quando OffscreenCanvas não existe", async () => {
    vi.stubGlobal("OffscreenCanvas", undefined)
    const { prepararContextoMapa } = await import("./preparar-contexto")
    ;(await prepararContextoMapa())()
    expect(WorkerTeste.criados).toHaveLength(0)
  })
  it("falha ou prazo de driver travado encerram o worker sem rejeitar a abertura", async () => {
    const { prepararContextoMapa } = await import("./preparar-contexto")
    const erro = prepararContextoMapa()
    WorkerTeste.criados[0].onerror?.()
    ;(await erro)()
    expect(WorkerTeste.criados[0].terminate).toHaveBeenCalledTimes(1)
    const travado = prepararContextoMapa()
    await vi.advanceTimersByTimeAsync(5000)
    ;(await travado)()
    expect(WorkerTeste.criados[1].terminate).toHaveBeenCalledTimes(1)
  })
  it("inicia somente o contexto no worker, sem copiar nem compilar GLSL", async () => {
    const gl = { clearColor: vi.fn(), clear: vi.fn(), finish: vi.fn(), COLOR_BUFFER_BIT: 16384 }
    const getContext = vi.fn(() => gl), postMessage = vi.fn()
    vi.stubGlobal("OffscreenCanvas", class { getContext = getContext })
    vi.stubGlobal("postMessage", postMessage)
    await import("./preparar-contexto.worker")
    expect(getContext).toHaveBeenCalledWith("webgl2", { antialias: false, powerPreference: "high-performance" })
    expect(gl.clear).toHaveBeenCalledWith(gl.COLOR_BUFFER_BIT)
    expect(gl.finish).toHaveBeenCalledOnce()
    expect(postMessage).toHaveBeenCalledWith({ pronto: true })
    Reflect.deleteProperty(globalThis, "contextoMapaInicial")
  })
})
