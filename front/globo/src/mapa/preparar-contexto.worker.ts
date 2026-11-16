import { programasNacionais } from "virtual:raiz-programas-nacionais"
import { prepararProgramasGpu } from "./preparar-programas-gpu"

/** Preparação do contexto e dos programas reais fora da interface, sem transferir dados ou handles. */
let contexto: WebGL2RenderingContext | null = null
try {
  contexto = new OffscreenCanvas(1, 1).getContext("webgl2", { antialias: false, powerPreference: "high-performance" })
  // O dono encerra o worker na desmontagem; contexto e programas permanecem vivos até lá.
  Object.assign(globalThis, { contextoMapaInicial: contexto })
  if (contexto) {
    contexto.clearColor(0, 0, 0, 0)
    contexto.clear(contexto.COLOR_BUFFER_BIT)
    contexto.finish()
  }
} catch { /* Sem WebGL no worker, o MapLibre conserva o caminho nativo. */ }
// Abrir o contexto principal enquanto o worker compila faz getContext aguardar a mesma
// fila da GPU na interface. Concluímos o trabalho real aqui; DOM e dados seguem independentes.
try {
  if (contexto) Object.assign(globalThis, { programasMapaInicial: prepararProgramasGpu(contexto, programasNacionais) })
} catch { /* Driver/worker sem suporte mantém integralmente o caminho nativo. */ }
postMessage({ pronto: true })
