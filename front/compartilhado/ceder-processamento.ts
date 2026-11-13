/** Continua o trabalho em outra tarefa, deixando o navegador atender entrada e pintar entre etapas. */
export function cederProcessamento(): Promise<void> {
  const agendador = (globalThis as typeof globalThis & { scheduler?: { yield?: () => Promise<void> } }).scheduler
  if (agendador?.yield) return agendador.yield()
  // Firefox e Safari também cooperam, sem depender de um temporizador ou de o navegador ficar ocioso.
  return new Promise(resolve => {
    const canal = new MessageChannel()
    canal.port1.onmessage = () => { canal.port1.close(); canal.port2.close(); resolve() }
    canal.port2.postMessage(null)
  })
}
