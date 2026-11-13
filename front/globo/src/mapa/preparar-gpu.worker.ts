/** Prepara o contexto gráfico para o canvas real do MapLibre fora da thread da interface. */
import { aquecerSimbolo } from "./aquecer-simbolo"

try {
  const contexto = new OffscreenCanvas(1, 1).getContext("webgl2", { antialias: false, powerPreference: "high-performance" })
  // A referência também sobrevive quando uma etapa opcional do aquecimento falha.
  Object.assign(globalThis, { contextoInicial: contexto })
  if (contexto) {
    // Concluir uma limpeza real garante que a inicialização do driver não fique pendente para a interface.
    contexto.clearColor(0, 0, 0, 0)
    contexto.clear(contexto.COLOR_BUFFER_BIT)
    contexto.finish()
    // Mesmo symbolSDF do mapa nacional: aquece o cache do driver sem consultar o link na interface.
    // O MapLibre continua dono de seus programas; nenhum handle é transferido entre contextos.
    Object.assign(globalThis, { programaInicial: aquecerSimbolo(contexto) })
  }
  // O contexto e o programa ficam retidos até o MapLibre assumir e terminar este worker.
} catch { /* O mapa usa seu caminho normal quando OffscreenCanvas/WebGL não está disponível no worker. */ }
postMessage({ pronto: true })
