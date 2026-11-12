"use client"

import { Globe, type GlobeArc, type GlobeMarker } from "./ui/cobe-globe"

/**
 * O globo numa página branca: nove cidades com rótulo e dois arcos (São Francisco → Tóquio e Nova York → Londres).
 * Arraste para girar.
 */

const markers: GlobeMarker[] = [
  { id: "sf", location: [37.7595, -122.4367], label: "São Francisco" },
  { id: "nyc", location: [40.7128, -74.006], label: "Nova York" },
  { id: "tokyo", location: [35.6762, 139.6503], label: "Tóquio" },
  { id: "london", location: [51.5074, -0.1278], label: "Londres" },
  { id: "sydney", location: [-33.8688, 151.2093], label: "Sydney" },
  { id: "capetown", location: [-33.9249, 18.4241], label: "Cidade do Cabo" },
  { id: "dubai", location: [25.2048, 55.2708], label: "Dubai" },
  { id: "paris", location: [48.8566, 2.3522], label: "Paris" },
  { id: "saopaulo", location: [-23.5505, -46.6333], label: "São Paulo" },
]

const arcs: GlobeArc[] = [
  { id: "sf-tokyo", from: [37.7595, -122.4367], to: [35.6762, 139.6503], label: "SF → Tóquio" },
  { id: "nyc-london", from: [40.7128, -74.006], to: [51.5074, -0.1278], label: "NY → Londres" },
]

export default function GlobeDemo() {
  return (
    <div className="cg-demo">
      <style dangerouslySetInnerHTML={{ __html: DEMO_CSS }} />
      <div className="cg-demo__globe">
        <Globe
          markers={markers}
          arcs={arcs}
          markerColor={[0.3, 0.45, 0.85]}
          baseColor={[1, 1, 1]}
          arcColor={[0.3, 0.45, 0.85]}
          glowColor={[0.94, 0.93, 0.91]}
          dark={0}
          mapBrightness={10}
          markerSize={0.025}
          markerElevation={0.01}
        />
      </div>
    </div>
  )
}

const DEMO_CSS = `
.cg-demo {
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  width: 100%;
  min-height: 100svh;
  padding: 32px;
  overflow: hidden;
  background: #fff;
}
.cg-demo__globe { width: 100%; max-width: 512px; }
`
