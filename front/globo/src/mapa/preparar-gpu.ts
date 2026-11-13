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
    let concluido = false
    const liberar = () => worker.terminate()
    const falhou = () => {
      if (concluido) return
      concluido = true
      clearTimeout(limite)
      liberar()
      resolve(() => {})
    }
    // Limite de falha, nunca uma espera de sucesso: driver travado não pode impedir a abertura do mapa.
    const limite = setTimeout(falhou, 5000)
    worker.onmessage = evento => {
      if (concluido || evento.data?.pronto !== true) return
      concluido = true
      clearTimeout(limite)
      resolve(liberar)
    }
    worker.onerror = falhou
    worker.onmessageerror = falhou
  })
  return preparacao
}
