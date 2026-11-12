import { useMemo } from "react"
import { svgMiniBrasil } from "../../../compartilhado/mini-brasil"

/** Onde fica: mini mapa do Brasil em SVG (estados em névoa, o estado destacado e o ponto do município em urucum). */
export function MiniBrasil({ uf, lon, lat, titulo, className }: { uf?: string | null; lon?: number | null; lat?: number | null; titulo: string; className?: string }) {
  const svg = useMemo(() => svgMiniBrasil({ uf, lon, lat, titulo }), [uf, lon, lat, titulo])
  return <div className={"mini-brasil" + (className ? " " + className : "")} dangerouslySetInnerHTML={{ __html: svg }} />
}
