import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
vi.mock("./preparar-programas-gpu", () => ({ prepararProgramasGpu: vi.fn(() => []) }))

class WorkerTeste {
  static criados: WorkerTeste[] = []
  onmessage?: (evento: { data: unknown }) => void
  onerror?: () => void
  onmessageerror?: () => void
  terminate = vi.fn()
  constructor() { WorkerTeste.criados.push(this) }
}
beforeEach(() => { vi.resetModules(); vi.clearAllMocks(); vi.useFakeTimers(); WorkerTeste.criados = []; vi.stubGlobal("Worker", WorkerTeste); vi.stubGlobal("OffscreenCanvas", class {}) })
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

describe("preparação não bloqueante do contexto gráfico", () => {
  it("compartilha o trabalho entre download e montagem e retém o worker até a liberação explícita", async () => {
    const { prepararContextoMapa } = await import("./preparar-contexto")
    const primeiro = prepararContextoMapa(), segundo = prepararContextoMapa()
    expect(primeiro).toBe(segundo)
    expect(WorkerTeste.criados).toHaveLength(1)
    const worker = WorkerTeste.criados[0]
    worker.onmessage?.({ data: { pronto: true } })
    await primeiro.pronto
    expect(worker.terminate).not.toHaveBeenCalled()
    primeiro.cancelar(); primeiro.cancelar()
    expect(worker.terminate).toHaveBeenCalledTimes(1)
    const proximo = prepararContextoMapa()
    expect(WorkerTeste.criados).toHaveLength(2)
    WorkerTeste.criados[1].onmessage?.({ data: { pronto: true } })
    await proximo.pronto
    proximo.cancelar()
  })
  it("não impede o caminho nativo quando OffscreenCanvas não existe", async () => {
    vi.stubGlobal("OffscreenCanvas", undefined)
    const { prepararContextoMapa } = await import("./preparar-contexto")
    const preparo = prepararContextoMapa()
    await preparo.pronto
    preparo.cancelar()
    expect(WorkerTeste.criados).toHaveLength(0)
  })
  it("falha ou prazo de driver travado encerram o worker sem rejeitar a abertura", async () => {
    const { prepararContextoMapa } = await import("./preparar-contexto")
    const erro = prepararContextoMapa()
    WorkerTeste.criados[0].onerror?.()
    await erro.pronto
    expect(WorkerTeste.criados[0].terminate).toHaveBeenCalledTimes(1)
    const travado = prepararContextoMapa()
    await vi.advanceTimersByTimeAsync(5000)
    await travado.pronto
    expect(WorkerTeste.criados[1].terminate).toHaveBeenCalledTimes(1)
  })
  it("desmontar antes de pronto encerra na mesma tarefa e não cancela a montagem seguinte", async () => {
    const { prepararContextoMapa } = await import("./preparar-contexto")
    const anterior = prepararContextoMapa(), workerAnterior = WorkerTeste.criados[0]
    anterior.cancelar()
    expect(workerAnterior.terminate).toHaveBeenCalledOnce()
    await anterior.pronto
    const seguinte = prepararContextoMapa(), workerSeguinte = WorkerTeste.criados[1]
    anterior.cancelar()
    workerAnterior.onmessage?.({ data: { pronto: true } })
    expect(workerSeguinte.terminate).not.toHaveBeenCalled()
    expect(prepararContextoMapa()).toBe(seguinte)
    workerSeguinte.onmessage?.({ data: { pronto: true } })
    await seguinte.pronto
    seguinte.cancelar()
    expect(workerSeguinte.terminate).toHaveBeenCalledOnce()
  })
  it("libera o contexto principal após preparar os programas no worker, sem disputa pela fila gráfica", async () => {
    const gl = { clearColor: vi.fn(), clear: vi.fn(), finish: vi.fn(), COLOR_BUFFER_BIT: 16384 }
    const getContext = vi.fn(() => gl), postMessage = vi.fn()
    vi.stubGlobal("OffscreenCanvas", class { getContext = getContext })
    vi.stubGlobal("postMessage", postMessage)
    await import("./preparar-contexto.worker")
    expect(getContext).toHaveBeenCalledWith("webgl2", { antialias: false, powerPreference: "high-performance" })
    expect(gl.clear).toHaveBeenCalledWith(gl.COLOR_BUFFER_BIT)
    expect(gl.finish).toHaveBeenCalledOnce()
    expect(postMessage).toHaveBeenCalledWith({ pronto: true })
    const { prepararProgramasGpu } = await import("./preparar-programas-gpu")
    expect(prepararProgramasGpu).toHaveBeenCalledOnce()
    expect(vi.mocked(prepararProgramasGpu).mock.invocationCallOrder[0]).toBeLessThan(postMessage.mock.invocationCallOrder[0])
    Reflect.deleteProperty(globalThis, "contextoMapaInicial")
    Reflect.deleteProperty(globalThis, "programasMapaInicial")
  })
  it("libera o caminho nativo mesmo quando preparar programas falha", async () => {
    const gl = { clearColor: vi.fn(), clear: vi.fn(), finish: vi.fn(), COLOR_BUFFER_BIT: 16384 }
    vi.stubGlobal("OffscreenCanvas", class { getContext = () => gl })
    const postMessage = vi.fn(); vi.stubGlobal("postMessage", postMessage)
    const { prepararProgramasGpu } = await import("./preparar-programas-gpu")
    vi.mocked(prepararProgramasGpu).mockImplementationOnce(() => { throw new Error("contexto perdido") })
    await import("./preparar-contexto.worker")
    expect(postMessage).toHaveBeenCalledOnce()
    expect(postMessage).toHaveBeenCalledWith({ pronto: true })
    Reflect.deleteProperty(globalThis, "contextoMapaInicial")
  })
})
