import type { LayerSpecification, Map as MapaGL, StyleSpecification } from "maplibre-gl"
import { cederProcessamento } from "../../../compartilhado/ceder-processamento"

/** A primeira criação de cada classe de camada compila suas expressões padrão. */
export function separarEstiloNacional(estilo: StyleSpecification): {
  inicial: StyleSpecification
  ordem: LayerSpecification[]
  etapas: LayerSpecification[][]
} {
  return {
    inicial: { ...estilo, layers: estilo.layers.filter(camada => camada.type !== "line" && camada.type !== "symbol") },
    ordem: estilo.layers,
    etapas: ["line", "symbol"].map(tipo => estilo.layers.filter(camada => camada.type === tipo)),
  }
}

/** Instala exatamente as mesmas camadas e a mesma ordem, cedendo entre classes, sem timers. */
export async function completarEstiloNacional(
  mapa: Pick<MapaGL, "addLayer" | "getLayer">,
  plano: ReturnType<typeof separarEstiloNacional>,
  cancelado: () => boolean,
): Promise<boolean> {
  for (const etapa of plano.etapas) {
    if (!etapa.length) continue
    await cederProcessamento()
    if (cancelado()) return false
    for (const camada of etapa) {
      // Fontes e posições são as do estilo original; as camadas já existentes delimitam a inserção.
      const indice = plano.ordem.findIndex(candidata => candidata.id === camada.id)
      const antes = plano.ordem.slice(indice + 1).find(candidata => mapa.getLayer(candidata.id))?.id
      mapa.addLayer(camada, antes)
    }
  }
  return !cancelado()
}
