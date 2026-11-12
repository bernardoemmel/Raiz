"use client"

import * as React from "react"
import createGlobe from "cobe"

/**
 * Cobe Globe — um globo 3D em WebGL que gira sozinho, com pontos nas cidades, arcos entre elas e rótulos presos aos
 * pontos, que somem com um desfoque quando o ponto passa para trás do globo.
 *
 * O desenho é do cobe (WebGL, uns 5 KB): o mapa em pontos, o brilho e os marcadores. Arraste para girar: solto, o globo
 * segue no embalo e desacelera; na vertical ele inclina até um limite e volta. Os rótulos usam CSS Anchor Positioning
 * (Chrome, Edge, Safari 26+); nos navegadores sem ele, o globo aparece sem os rótulos.
 *
 * O giro, o embalo e a volta da inclinação andam pelo tempo, não por quadro: o globo gira na mesma velocidade a 60 e a
 * 120 Hz. Fora da tela ele para de desenhar; com "reduzir movimento" ligado no sistema, só gira quando é arrastado.
 *
 * O canvas nasce aqui dentro, fora do React: o cobe embrulha o canvas numa div dele, e um canvas do React mudaria de
 * lugar debaixo dele. Os nomes das âncoras levam um id deste globo, então dois globos na mesma página não trocam os
 * rótulos entre si.
 */

export interface GlobeMarker {
  id: string
  location: [number, number]
  label: string
}

export interface GlobeArc {
  id: string
  from: [number, number]
  to: [number, number]
  label?: string
}

type RGB = [number, number, number]

export interface GlobeProps {
  markers?: GlobeMarker[]
  arcs?: GlobeArc[]
  className?: string
  style?: React.CSSProperties
  markerColor?: RGB
  baseColor?: RGB
  arcColor?: RGB
  glowColor?: RGB
  dark?: number
  mapBrightness?: number
  markerSize?: number
  markerElevation?: number
  arcWidth?: number
  arcHeight?: number
  speed?: number
  theta?: number
  diffuse?: number
  mapSamples?: number
}

type Settings = Required<Omit<GlobeProps, "className" | "style">>

// o cobe cria, para cada ponto e arco com id, uma âncora (--cobe-<id>, --cobe-arc-<id>) e uma variável de visibilidade
// (--cobe-visible-<id>, --cobe-visible-arc-<id>), as duas valendo para a página inteira. O id leva o deste globo na
// frente e só letras, números, - e _
const anchorId = (uid: string, id: string) => uid + "-" + id.replace(/[^a-zA-Z0-9_-]/g, "-")

// cada rótulo preso à âncora do ponto (ou do arco) e apagado, com desfoque, quando ele passa para trás do globo
const labelStyle = (name: string) =>
  ({
    positionAnchor: "--cobe-" + name,
    opacity: "var(--cobe-visible-" + name + ", 0)",
    filter: "blur(calc((1 - var(--cobe-visible-" + name + ", 0)) * 8px))",
  }) as React.CSSProperties

export function Globe({
  markers = [],
  arcs = [],
  className,
  style,
  markerColor = [0.3, 0.45, 0.85],
  baseColor = [1, 1, 1],
  arcColor = [0.3, 0.45, 0.85],
  glowColor = [0.94, 0.93, 0.91],
  dark = 0,
  mapBrightness = 10,
  markerSize = 0.025,
  markerElevation = 0.01,
  arcWidth = 0.5,
  arcHeight = 0.25,
  speed = 0.003,
  theta = 0.2,
  diffuse = 1.5,
  mapSamples = 16000,
}: GlobeProps) {
  const uid = "g" + React.useId().replace(/[^a-zA-Z0-9_-]/g, "")
  const stageRef = React.useRef<HTMLDivElement>(null)

  // o globo nasce uma vez; a cada quadro ele lê daqui as props mais novas (arrays escritos no JSX mudam a cada render)
  const settings: Settings = {
    markers,
    arcs,
    markerColor,
    baseColor,
    arcColor,
    glowColor,
    dark,
    mapBrightness,
    markerSize,
    markerElevation,
    arcWidth,
    arcHeight,
    speed,
    theta,
    diffuse,
    mapSamples,
  }
  const settingsRef = React.useRef(settings)
  React.useEffect(() => {
    settingsRef.current = settings
  })

  React.useEffect(() => {
    const stage = stageRef.current
    if (!stage) return
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    const canvas = document.createElement("canvas")
    canvas.className = "cg-canvas"
    stage.append(canvas)

    let globe: ReturnType<typeof createGlobe> | null = null
    let raf = 0
    let last = 0
    let size = 0
    let visible = true
    let phi = 0
    let phiOffset = 0
    let thetaOffset = 0
    let drag = { phi: 0, theta: 0 }
    let velocity = { phi: 0, theta: 0 }
    let pointer: { x: number; y: number } | null = null
    let lastPointer: { x: number; y: number; t: number } | null = null

    const points = (s: Settings) => ({
      markers: s.markers.map((m) => ({ location: m.location, size: s.markerSize, id: anchorId(uid, m.id) })),
      arcs: s.arcs.map((a) => ({ from: a.from, to: a.to, id: anchorId(uid, a.id) })),
    })

    const frame = (now: number) => {
      raf = requestAnimationFrame(frame)
      // o passo, em quadros de 60 Hz, pelo tempo que passou: um quadro perdido conta no máximo como três
      const k = last ? Math.min(now - last, 50) / (1000 / 60) : 1
      last = now
      if (!globe || !visible) return
      const s = settingsRef.current
      if (!pointer) {
        if (!reduced) phi += s.speed * k
        if (Math.abs(velocity.phi) > 0.0001 || Math.abs(velocity.theta) > 0.0001) {
          phiOffset += velocity.phi * k
          thetaOffset += velocity.theta * k
          const decay = Math.pow(0.95, k)
          velocity.phi *= decay
          velocity.theta *= decay
        }
        // inclinado além do limite, volta devagar para dentro dele
        const pull = 1 - Math.pow(0.9, k)
        if (thetaOffset < -0.4) thetaOffset += (-0.4 - thetaOffset) * pull
        else if (thetaOffset > 0.4) thetaOffset += (0.4 - thetaOffset) * pull
      }
      globe.update({
        phi: phi + phiOffset + drag.phi,
        theta: s.theta + thetaOffset + drag.theta,
        dark: s.dark,
        mapBrightness: s.mapBrightness,
        markerColor: s.markerColor,
        baseColor: s.baseColor,
        arcColor: s.arcColor,
        markerElevation: s.markerElevation,
        ...points(s),
      })
    }

    const init = () => {
      size = canvas.offsetWidth
      if (!size) return
      const s = settingsRef.current
      globe = createGlobe(canvas, {
        devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2),
        width: size,
        height: size,
        phi: 0,
        theta: s.theta,
        dark: s.dark,
        diffuse: s.diffuse,
        mapSamples: s.mapSamples,
        mapBrightness: s.mapBrightness,
        baseColor: s.baseColor,
        markerColor: s.markerColor,
        glowColor: s.glowColor,
        markerElevation: s.markerElevation,
        ...points(s),
        arcColor: s.arcColor,
        arcWidth: s.arcWidth,
        arcHeight: s.arcHeight,
        opacity: 0.7,
      })
      raf = requestAnimationFrame(frame)
      setTimeout(() => (canvas.style.opacity = "1"))
    }

    // o globo nasce quando o canvas ganha largura e acompanha a largura dele depois
    const ro = new ResizeObserver(() => {
      if (!globe) return init()
      const width = canvas.offsetWidth
      if (width && width !== size) {
        size = width
        globe.update({ width, height: width })
      }
    })
    ro.observe(canvas)
    const io = new IntersectionObserver(([e]) => {
      visible = e.isIntersecting
    })
    io.observe(stage)

    // arrastar: o globo segue a mão; solto, continua no embalo da última velocidade dela
    const down = (e: PointerEvent) => {
      pointer = { x: e.clientX, y: e.clientY }
      canvas.style.cursor = "grabbing"
    }
    const move = (e: PointerEvent) => {
      if (!pointer) return
      drag = { phi: (e.clientX - pointer.x) / 300, theta: (e.clientY - pointer.y) / 1000 }
      const now = performance.now()
      if (lastPointer) {
        const dt = Math.max(now - lastPointer.t, 1)
        const max = 0.15
        velocity = {
          phi: Math.max(-max, Math.min(max, ((e.clientX - lastPointer.x) / dt) * 0.3)),
          theta: Math.max(-max, Math.min(max, ((e.clientY - lastPointer.y) / dt) * 0.08)),
        }
      }
      lastPointer = { x: e.clientX, y: e.clientY, t: now }
    }
    const up = () => {
      if (pointer) {
        phiOffset += drag.phi
        thetaOffset += drag.theta
        drag = { phi: 0, theta: 0 }
        lastPointer = null
      }
      pointer = null
      canvas.style.cursor = "grab"
    }
    canvas.addEventListener("pointerdown", down)
    window.addEventListener("pointermove", move, { passive: true })
    window.addEventListener("pointerup", up, { passive: true })
    window.addEventListener("pointercancel", up, { passive: true })

    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
      io.disconnect()
      canvas.removeEventListener("pointerdown", down)
      window.removeEventListener("pointermove", move)
      window.removeEventListener("pointerup", up)
      window.removeEventListener("pointercancel", up)
      if (globe) {
        globe.destroy()
        // o contexto sai na hora (o navegador segura uns 16 por página), e o canvas e a div do cobe saem junto
        const gl = canvas.getContext("webgl2") ?? canvas.getContext("webgl")
        gl?.getExtension("WEBGL_lose_context")?.loseContext()
      }
      stage.replaceChildren()
    }
  }, [uid])

  return (
    <div className={"cg-root" + (className ? " " + className : "")} style={style}>
      {/* o CSS cru: como filho de texto, o SSR do React 18 escaparia as aspas e quebraria os seletores */}
      <style dangerouslySetInnerHTML={{ __html: CG_CSS }} />
      <div ref={stageRef} className="cg-stage" />
      {markers.map((m) => (
        <div key={m.id} className="cg-label cg-label--marker" style={labelStyle(anchorId(uid, m.id))}>
          {m.label}
          <span className="cg-label__tip" />
        </div>
      ))}
      {arcs
        .filter((a) => a.label)
        .map((a) => (
          <div key={a.id} className="cg-label cg-label--arc" style={labelStyle("arc-" + anchorId(uid, a.id))}>
            {a.label}
            <span className="cg-label__tip" />
          </div>
        ))}
    </div>
  )
}

const CG_CSS = `
/* o que o projeto pode trocar com uma classe (largura, posição, margem): na camada base, que vem antes das classes de
   componente e dos utilitários (Tailwind v4) e perde para o CSS fora de camada (Tailwind v3, CSS Modules, CSS comum) */
@layer base {
  .cg-root { position: relative; width: 100%; margin: 0; }
}
.cg-root {
  aspect-ratio: 1;
  -webkit-user-select: none;
  user-select: none;
  -webkit-tap-highlight-color: transparent;
}
.cg-stage { position: absolute; inset: 0; }
/* o arraste na horizontal gira o globo; no toque, o gesto vertical continua rolando a página */
.cg-canvas {
  display: block;
  width: 100%;
  height: 100%;
  border-radius: 50%;
  cursor: grab;
  opacity: 0;
  transition: opacity 1.2s ease;
  touch-action: pan-y;
}

/* os rótulos: nada de texto herdado da página, para ficarem iguais em qualquer projeto */
.cg-label {
  display: none;
  position: absolute;
  box-sizing: border-box;
  margin: 0 0 8px;
  padding: 2px 6px;
  font-family: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 9.6px;
  font-weight: 400;
  font-style: normal;
  font-variant: normal;
  font-feature-settings: normal;
  line-height: 1.5;
  letter-spacing: .08em;
  word-spacing: normal;
  text-align: left;
  text-indent: 0;
  text-transform: uppercase;
  text-shadow: none;
  white-space: nowrap;
  pointer-events: none;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  transition: opacity .8s, filter .8s;
}
.cg-label--marker { background: #1a1a2e; color: #fff; }
.cg-label--arc { background: #fff; color: #1a1a2e; box-shadow: 0 1px 4px rgba(0, 0, 0, .1); }
.cg-label__tip {
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translate3d(-50%, -1px, 0);
  border: 5px solid transparent;
}
.cg-label--marker .cg-label__tip { border-top-color: #1a1a2e; }
.cg-label--arc .cg-label__tip { border-top-color: #fff; }
/* presos aos pontos por CSS Anchor Positioning; sem ele, os rótulos ficam escondidos em vez de empilhados num canto */
@supports (position-anchor: --a) {
  .cg-label { display: block; bottom: anchor(top); left: anchor(center); translate: -50% 0; }
}
`
