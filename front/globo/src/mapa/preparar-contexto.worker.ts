/** Preparação real de contexto; nenhum shader do produto, dado do mapa ou handle é transferido. */
try {
  const contexto = new OffscreenCanvas(1, 1).getContext("webgl2", { antialias: false, powerPreference: "high-performance" })
  // Retém o contexto até o canvas real assumir, evitando encerrar o processo gráfico entre os dois.
  Object.assign(globalThis, { contextoMapaInicial: contexto })
  if (contexto) {
    contexto.clearColor(0, 0, 0, 0)
    contexto.clear(contexto.COLOR_BUFFER_BIT)
    contexto.finish()
  }
} catch { /* Sem WebGL no worker, o MapLibre conserva o caminho nativo. */ }
postMessage({ pronto: true })
