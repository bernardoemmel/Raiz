import { useEffect, useRef, useState } from "react"
import { Globe, type GlobeMarker } from "../components/ui/cobe-globe"
import { fmtInt } from "../../../compartilhado/formato"
import { IconeRaiz } from "./Icones"

/**
 * Abertura: o globo (componente aprovado, sem alteração) gira rápido, freia e para com o município no centro, e
 * depois aproxima até o mapa do painel, que voa até o município.
 *
 * O componente não deixa mexer no ângulo do globo, só na velocidade (speed) e na inclinação (theta), que ele lê a
 * cada quadro. Então a freada é feita de fora, olhando onde o marcador está: o cobe põe uma âncora com left/top em %
 * na posição do marcador e escreve --cobe-visible-<id> quando ele está na frente do globo. Um controle proporcional
 * diminui a velocidade conforme o marcador se aproxima do centro e zera quando chega.
 */

const ID = "raiz-alvo"
const VEL_MAX = 0.032 // rad por quadro de 60 Hz (o padrão do globo é 0,003)
const VEL_MIN = 0.0007
const GANHO = 0.11
const GIRO_MINIMO_MS = 1300

interface Props {
  local: [number, number]
  nome: string
  uf: string
  imoveis: number | null
  /** o mapa do painel está pronto para receber o voo */
  mapaPronto: boolean
  aoRevelar: () => void
  aoTerminar: () => void
}

type Fase = "girando" | "freando" | "parado" | "aproximando"

export function Abertura({ local, nome, uf, imoveis, mapaPronto, aoRevelar, aoTerminar }: Props) {
  const [velocidade, setVelocidade] = useState(VEL_MAX)
  const [theta, setTheta] = useState(0.25)
  const [fase, setFase] = useState<Fase>("girando")
  const globo = useRef<HTMLDivElement>(null)
  const fundo = useRef<HTMLDivElement>(null)
  const pronto = useRef(mapaPronto)
  useEffect(() => {
    pronto.current = mapaPronto
  }, [mapaPronto])
  const terminou = useRef(false)
  const thetaAlvo = (local[0] * Math.PI) / 180 - 0.04

  // freada pelo marcador
  useEffect(() => {
    let raf = 0
    const t0 = performance.now()
    let sentido = 0
    let xAntes: number | null = null
    let estilo: HTMLStyleElement | null = null
    let th = 0.25
    let ultimo = t0

    const ancora = () =>
      [...(globo.current?.querySelectorAll<HTMLDivElement>(".cg-stage div") ?? [])].find((d) => d.style.width === "1px")
    const visivel = () => {
      if (!estilo || !estilo.textContent?.includes(":root"))
        estilo = [...document.head.querySelectorAll("style")].find((s) => s.textContent?.startsWith(":root{")) ?? null
      return !!estilo?.textContent?.includes(ID + ":N")
    }

    const passo = (agora: number) => {
      raf = requestAnimationFrame(passo)
      const k = Math.min(agora - ultimo, 50) / (1000 / 60)
      ultimo = agora
      // inclinação: vai suave até deixar o município na altura do centro
      th += (thetaAlvo - th) * (1 - Math.pow(0.965, k))
      setTheta(th)

      const a = ancora()
      if (!a) return
      const x = parseFloat(a.style.left) / 100
      const ve = visivel()
      // em que sentido o marcador anda na tela quando o globo gira (na frente do globo)
      if (ve && xAntes !== null && Math.abs(x - xAntes) > 1e-4 && sentido === 0) sentido = Math.sign(x - xAntes)
      xAntes = ve ? x : null
      if (agora - t0 < GIRO_MINIMO_MS || !ve || sentido === 0) return

      const falta = (0.5 - x) * sentido // > 0: ainda vem vindo para o centro
      if (falta < -0.02) return // passou do centro: dá a volta de novo
      if (falta <= 0.0015) {
        setVelocidade(0)
        cancelAnimationFrame(raf)
        setFase("parado")
        return
      }
      setFase("freando")
      setVelocidade(Math.max(VEL_MIN, Math.min(VEL_MAX, (GANHO * falta) / 0.4)))
    }
    raf = requestAnimationFrame(passo)
    return () => cancelAnimationFrame(raf)
  }, [thetaAlvo])

  // parado: mostra o nome, espera o mapa e aproxima
  useEffect(() => {
    if (fase !== "parado") return
    let vivo = true
    const t = setTimeout(async () => {
      const limite = performance.now() + 5000
      while (vivo && !pronto.current && performance.now() < limite) await new Promise((r) => setTimeout(r, 100))
      if (vivo) setFase("aproximando")
    }, 900)
    return () => {
      vivo = false
      clearTimeout(t)
    }
  }, [fase])

  useEffect(() => {
    if (fase !== "aproximando" || !globo.current || !fundo.current) return
    const a = [...globo.current.querySelectorAll<HTMLDivElement>(".cg-stage div")].find((d) => d.style.width === "1px")
    const caixa = globo.current.getBoundingClientRect()
    const r = a?.getBoundingClientRect()
    const px = r ? r.left - caixa.left : caixa.width / 2
    const py = r ? r.top - caixa.top : caixa.height / 2
    const alvo = document.querySelector(".mapa-caixa")?.getBoundingClientRect()
    const dx = alvo ? alvo.left + alvo.width / 2 - (caixa.left + px) : 0
    const dy = alvo ? alvo.top + alvo.height / 2 - (caixa.top + py) : 0
    globo.current.style.transformOrigin = `${px}px ${py}px`
    aoRevelar()
    const zoom = globo.current.animate(
      [
        { transform: "translate(0, 0) scale(1)", opacity: 1, filter: "blur(0)" },
        { offset: 0.55, opacity: 1, filter: "blur(0)" },
        { transform: `translate(${dx}px, ${dy}px) scale(9)`, opacity: 0, filter: "blur(6px)" },
      ],
      { duration: 1300, easing: "cubic-bezier(.5,0,.75,.2)", fill: "forwards" },
    )
    fundo.current.animate([{ opacity: 1 }, { opacity: 1, offset: 0.3 }, { opacity: 0 }], {
      duration: 1300,
      easing: "ease-in",
      fill: "forwards",
    })
    zoom.onfinish = () => {
      if (!terminou.current) {
        terminou.current = true
        aoTerminar()
      }
    }
  }, [fase, aoRevelar, aoTerminar])

  const pular = () => {
    if (terminou.current) return
    terminou.current = true
    aoRevelar()
    aoTerminar()
  }

  const marcadores: GlobeMarker[] = [{ id: ID, location: local, label: nome }]
  const legenda =
    fase === "girando" || fase === "freando" ? (
      <>
        <strong>O Brasil inteiro, fazenda por fazenda</strong>
        <span>só com dados públicos: CAR, PRODES, MapBiomas, Ibama, SIGEF</span>
      </>
    ) : (
      <>
        <strong>
          {nome}, {uf}
        </strong>
        <span>{imoveis !== null ? `${fmtInt(imoveis)} imóveis do CAR cruzados com tudo isso` : " "}</span>
      </>
    )

  return (
    <div className={"abertura fase-" + fase} role="dialog" aria-label="Abertura da Raíz" aria-live="polite">
      <div className="abertura-fundo" ref={fundo} />
      <div className="abertura-marca">
        <IconeRaiz /> Raíz
      </div>
      <div className="abertura-globo" ref={globo}>
        <Globe
          markers={marcadores}
          speed={velocidade}
          theta={theta}
          markerColor={[0.11, 0.35, 0.22]}
          baseColor={[1, 1, 1]}
          glowColor={[0.92, 0.94, 0.9]}
          dark={0}
          mapBrightness={10}
          markerSize={0.03}
          markerElevation={0.01}
        />
      </div>
      <p className="abertura-legenda">{legenda}</p>
      <button type="button" className="abertura-pular" onClick={pular}>
        Pular abertura
      </button>
    </div>
  )
}
