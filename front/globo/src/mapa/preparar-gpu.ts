/** Inicia o contexto gráfico fora da thread da interface enquanto o módulo do mapa é baixado.
 * O MapLibre conserva seu próprio canvas e contexto; o contexto de 1 px só aquece o processo gráfico do navegador.
 */
let preparacao: Promise<() => void> | undefined
export function prepararGpu(): Promise<() => void> {
  preparacao ??= new Promise((resolve) => {
    if (typeof Worker === "undefined" || typeof OffscreenCanvas === "undefined") return resolve(() => {})
    let worker: Worker
    try { worker = new Worker(new URL("./preparar-gpu.worker.ts", import.meta.url), { type: "module" }) }
    catch { resolve(() => {}); return }
    const liberar = () => worker.terminate()
    worker.onmessage = () => resolve(liberar)
    worker.onerror = () => { liberar(); resolve(() => {}) }
  })
  return preparacao
}
