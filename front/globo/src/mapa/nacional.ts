/** Cartografia nacional preparada em um único estilo; as fontes recebem dados quando chegarem. */
import type { ExpressionSpecification, LayerSpecification, SourceSpecification } from "maplibre-gl"
import type { Geo } from "../../../compartilhado/dados"
import { COR } from "../../../compartilhado/cores"
import { ZOOM_IMOVEIS } from "./cartografia"

const ZOOM_FAZENDAS = ZOOM_IMOVEIS
const ZOOM_ROTULO_ESTADO = 6.5

export interface DadosNacionais { areas: Geo | string; rotulos: Geo; processadas: string[] }

/** Cobertura muda pelos códigos, sem copiar nem reenviar os contornos dos estados. */
export function filtroEstadosProcessados(ufs: readonly string[]): ExpressionSpecification {
  return ["in", ["get", "uf"], ["literal", [...ufs]]]
}

export function fontesNacionais(dados?: DadosNacionais): Record<string, SourceSpecification> {
  const data = { type: "FeatureCollection" as const, features: [] }
  return {
    "brasil-estados": { type: "geojson", data: (dados?.areas ?? data) as never, promoteId: "uf" },
    "estados-rotulos": { type: "geojson", data: (dados?.rotulos ?? data) as never },
  }
}

export function camadasNacionais(processadas: readonly string[] = []): LayerSpecification[] {
  const camadas: LayerSpecification[] = []
  const add = (camada: LayerSpecification) => { camadas.push(camada) }
  // As cores constantes reutilizam os programas gráficos do fundo. Os filtros são mutuamente exclusivos.
  const processado = filtroEstadosProcessados(processadas)
  add({ id: "estados-preenchimento", type: "fill", source: "brasil-estados", filter: processado as never,
    paint: { "fill-antialias": false, "fill-color": COR.restaurar, "fill-opacity": 0.35 } })
  add({ id: "estados-sem-dados", type: "fill", source: "brasil-estados", filter: ["!", processado] as never,
    paint: { "fill-antialias": false, "fill-color": COR.nevoa, "fill-opacity": 0.8 } })
  // divisa dos estados; o estado sob o dedo ou o mouse (na escala do país) e o escolhido ganham o contorno em tinta
  add({
    id: "estados-linha",
    type: "line",
    source: "brasil-estados",
    paint: {
      "line-color": COR.pedra,
      "line-width": 0.6,
      "line-opacity": ["interpolate", ["linear"], ["zoom"], 4, 0.9, ZOOM_FAZENDAS, 0.5],
    },
  })
  add({ id: "estado-sobre", type: "line", source: "brasil-estados", filter: ["==", ["get", "uf"], ""],
    paint: { "line-color": COR.tinta, "line-width": 2, "line-opacity": ["interpolate", ["linear"], ["zoom"], 4, 0.9, ZOOM_FAZENDAS, 0.5] } })
  add({
    id: "estado-escolhido",
    type: "line",
    source: "brasil-estados",
    filter: ["==", ["get", "uf"], ""],
    paint: { "line-color": COR.tinta, "line-width": ["interpolate", ["linear"], ["zoom"], 4, 1.5, 8, 2.5] },
  })
  // nome do estado e o que a Raíz já leu dele; o que ainda não foi processado em pedra
  for (const semDados of [true, false]) add(
    {
      id: semDados ? "estados-rotulo-sem-dados" : "estados-rotulo",
      type: "symbol",
      source: "estados-rotulos",
      filter: [semDados ? "==" : "!=", ["get", "s"], 0],
      maxzoom: ZOOM_ROTULO_ESTADO,
      layout: {
        "text-field": [
          "format",
          ["get", "nome"],
          { "font-scale": 1 },
          "\n",
          {},
          ["get", "linha"],
          { "font-scale": 0.85 },
        ],
        "text-font": ["Noto Sans Regular"],
        "text-size": ["interpolate", ["linear"], ["zoom"], 3, 11, 6, 14],
        "text-max-width": 9,
        "text-padding": 2,
        "symbol-sort-key": ["get", "ordem"],
      },
      paint: {
        "text-color": semDados ? COR.pedra : COR.tinta,
        "text-halo-color": COR.superficie,
        "text-halo-width": 1.5,
      },
    },
  )
  return camadas
}
