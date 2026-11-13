/** Prepara o contexto gráfico para o canvas real do MapLibre fora da thread da interface. */
try {
  const contexto = new OffscreenCanvas(1, 1).getContext("webgl2", { antialias: false, powerPreference: "high-performance" })
  // Manter a referência até o MapLibre assumir evita destruir o último contexto durante a inicialização.
  Object.assign(globalThis, { contextoInicial: contexto })
} catch { /* O mapa usa seu caminho normal quando OffscreenCanvas/WebGL não está disponível no worker. */ }
postMessage({ pronto: true })
