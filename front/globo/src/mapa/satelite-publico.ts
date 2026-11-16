import type { Map, RasterSourceSpecification } from "maplibre-gl"
import { COR } from "../../../compartilhado/cores"

/** Vintage fixo, conferido no WMTS e nos termos de 12/11/2026. Anos 2018+ têm licença não comercial. */
export const SATELITE_PUBLICO = {
  id: "sentinel-publico-2016",
  titulo: "Mosaico Sentinel-2 2016/2017 (histórico)",
  periodo: "2016/2017",
  resolucao: "10 m",
  fonte: "https://cloudless.eox.at",
  licenca: "CC BY 4.0",
  licencaUrl: "https://creativecommons.org/licenses/by/4.0/",
  termosUrl: "https://cloudless.eox.at/license-non-commercial",
  usoComercialUrl: "https://cloudless.eox.at/documentation/faq",
  conferidoEm: "2026-11-12",
  tile: "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/GoogleMapsCompatible/{z}/{y}/{x}.jpg",
  credito: 'EOxCloudless <a href="https://cloudless.eox.at" target="_blank" rel="noreferrer">cloudless.eox.at</a> by <a href="https://eox.at" target="_blank" rel="noreferrer">EOX IT Services GmbH</a> (Contains modified Copernicus Sentinel data 2016 &amp; 2017)',
} as const

export type EstadoSatelitePublico = "carregando" | "disponivel" | "indisponivel"
export const ID_VEU_SATELITE = "sentinel-publico-veu"

export function fonteSatelitePublico(): RasterSourceSpecification {
  return {
    type: "raster", tiles: [SATELITE_PUBLICO.tile], tileSize: 256,
    minzoom: 12, maxzoom: 14,
    // A resolução original é de 10 m. Aproximar além de z14 usa overzoom, sem solicitar outro ano ou imagens falsas.
    attribution: SATELITE_PUBLICO.credito,
  }
}

/** Só requisita tiles visíveis no detalhe. Se o serviço aberto falhar, a base vetorial permanece utilizável. */
export function adicionarSatelitePublico(mapa: Map, antes?: string, estado?: (valor: EstadoSatelitePublico) => void) {
  const id = SATELITE_PUBLICO.id
  let falhou = false
  let ultimo: EstadoSatelitePublico | null = null
  const informar = (valor: EstadoSatelitePublico) => { if (ultimo !== valor) { ultimo = valor; estado?.(valor) } }
  const carregar = (evento: { sourceId?: string; isSourceLoaded?: boolean }) => {
    if (evento.sourceId === id && evento.isSourceLoaded && mapa.getZoom() >= 12 && !falhou) informar("disponivel")
  }
  const erro = (evento: unknown) => {
    if (!evento || typeof evento !== "object" || !("sourceId" in evento) || evento.sourceId !== id) return
    falhou = true
    if (mapa.getLayer(id)) mapa.setLayoutProperty(id, "visibility", "none")
    if (mapa.getLayer(ID_VEU_SATELITE)) mapa.setLayoutProperty(ID_VEU_SATELITE, "visibility", "none")
    informar("indisponivel")
  }
  mapa.on("sourcedata", carregar)
  mapa.on("error", erro)
  mapa.addSource(id, fonteSatelitePublico())
  mapa.addLayer({
    id, type: "raster", source: id, minzoom: 12,
    paint: { "raster-saturation": -0.18, "raster-contrast": -0.05, "raster-fade-duration": 0 },
  }, antes)
  mapa.addLayer({
    id: ID_VEU_SATELITE, type: "background", minzoom: 12,
    paint: { "background-color": COR.papel, "background-opacity": 0.3 },
  }, antes)
  informar("carregando")
  return () => {
    mapa.off("sourcedata", carregar)
    mapa.off("error", erro)
    // O chamador remove o mapa completo. Não há cache separado, prefetch nacional ou cópia dos tiles no Release.
  }
}
