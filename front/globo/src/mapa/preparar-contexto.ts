/** Inicia o processo gráfico fora da interface. O MapLibre continua dono do canvas e dos seus programas. */
let preparacao: Promise<() => void> | undefined

export function prepararContextoMapa(): Promise<() => void> {
  if (preparacao) return preparacao
  const atual = new Promise<() => void>(resolve => {
    if (typeof Worker === "undefined" || typeof OffscreenCanvas === "undefined") { resolve(() => {}); return }
    let worker: Worker
    try { worker = new Worker(new URL("./preparar-contexto.worker.ts", import.meta.url), { type: "module" }) }
    catch { resolve(() => {}); return }
    let concluido = false, liberado = false
    const liberar = () => {
      if (liberado) return
      liberado = true
      worker.terminate()
      if (preparacao === atual) preparacao = undefined
    }
    const falhou = () => {
      if (concluido) return
      concluido = true
      clearTimeout(limite)
      liberar()
      resolve(() => {})
    }
    // Só uma falha/travamento usa o prazo. O caminho normal conclui assim que o driver fica pronto.
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
  preparacao = atual
  return atual
}
