import { afterEach, describe, expect, it, vi } from "vitest"

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })
async function iniciar() {
  vi.resetModules()
  vi.useFakeTimers()
  class WorkerTeste {
    static criado: WorkerTeste
    onmessage?: (evento: { data: unknown }) => void
    onerror?: () => void
    onmessageerror?: () => void
    terminate = vi.fn()
    constructor() { WorkerTeste.criado = this }
  }
  vi.stubGlobal("Worker", WorkerTeste)
  vi.stubGlobal("OffscreenCanvas", class {})
  const { prepararGpu } = await import("./preparar-gpu")
  const pronto = prepararGpu()
  return { worker: WorkerTeste.criado, pronto }
}

describe("aquecimento gráfico não bloqueia a abertura em caso de falha", () => {
  it("resolve imediatamente ao concluir e conserva contexto até o mapa assumir", async () => {
    const { worker, pronto } = await iniciar()
    worker.onmessage?.({ data: { pronto: true } })
    const liberar = await pronto
    expect(vi.getTimerCount()).toBe(0)
    expect(worker.terminate).not.toHaveBeenCalled()
    liberar()
    expect(worker.terminate).toHaveBeenCalledOnce()
  })
  it.each(["onerror", "onmessageerror"] as const)("libera o caminho normal e cancela o limite em %s", async erro => {
    const { worker, pronto } = await iniciar()
    worker[erro]?.()
    await pronto
    expect(vi.getTimerCount()).toBe(0)
    expect(worker.terminate).toHaveBeenCalledOnce()
  })
  it("ignora mensagens incompletas e abandona um worker que nunca responde", async () => {
    const { worker, pronto } = await iniciar()
    worker.onmessage?.({ data: { parcial: true } })
    expect(worker.terminate).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(5000)
    await pronto
    expect(worker.terminate).toHaveBeenCalledOnce()
    worker.onmessage?.({ data: { pronto: true } })
    expect(worker.terminate).toHaveBeenCalledOnce()
  })
})
