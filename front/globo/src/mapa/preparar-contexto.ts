/** Inicia o processo gráfico fora da interface. O MapLibre continua dono do canvas e dos seus programas. */
export interface PreparoContextoMapa {
  pronto: Promise<void>
  cancelar(): void
}

let preparacao: PreparoContextoMapa | undefined

export function prepararContextoMapa(): PreparoContextoMapa {
  if (preparacao) return preparacao
  let concluir!: () => void
  const pronto = new Promise<void>(resolve => { concluir = resolve })
  let worker: Worker | undefined
  let limite: ReturnType<typeof setTimeout> | undefined
  let liberado = false
  const atual: PreparoContextoMapa = {
    pronto,
    cancelar() {
      if (liberado) return
      liberado = true
      clearTimeout(limite)
      worker?.terminate()
      if (preparacao === atual) preparacao = undefined
      concluir()
    },
  }
  preparacao = atual
  if (typeof Worker === "undefined" || typeof OffscreenCanvas === "undefined") { atual.cancelar(); return atual }
  try { worker = new Worker(new URL("./preparar-contexto.worker.ts", import.meta.url), { type: "module" }) }
  catch { atual.cancelar(); return atual }
  // Só uma falha/travamento usa o prazo. Desmontar cancela imediatamente, mesmo antes de pronto.
  limite = setTimeout(atual.cancelar, 5000)
  worker.onmessage = evento => {
    if (liberado || evento.data?.pronto !== true) return
    clearTimeout(limite)
    concluir()
  }
  worker.onerror = atual.cancelar
  worker.onmessageerror = atual.cancelar
  return atual
}
