import { useCallback, useRef, useState } from "react"
import { fonte, useCarga } from "./dados"
import type { MapaApi } from "./mapa/MapaMunicipio"
import { Abertura } from "./partes/Abertura"
import { useRota } from "./rota"
import { Fazenda } from "./telas/Fazenda"
import { Principal } from "./telas/Principal"

type EstadoAbertura = "nunca" | "rodando" | "revelando" | "fim"

/** A abertura roda uma vez por sessão, só na tela do mapa, e nunca com "reduzir movimento" ligado. */
function deveAbrir(): boolean {
  const q = new URLSearchParams(location.search)
  if (q.has("abertura")) return true
  if (q.has("sem-abertura")) return false
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return false
  try {
    return !sessionStorage.getItem("raiz:abertura")
  } catch {
    return true
  }
}

export default function App() {
  const rota = useRota()
  const [estado, setEstado] = useState<EstadoAbertura>(() => (rota.tela === "mapa" && deveAbrir() ? "rodando" : "nunca"))
  const [codAbertura] = useState(() => (rota.tela === "mapa" ? rota.municipio : ""))
  const [mapaPronto, setMapaPronto] = useState(false)
  const mapa = useRef<MapaApi>(null)

  const alvo = useCarga(async () => {
    if (estado === "nunca") return null
    const [g, f] = await Promise.all([fonte.geo.camada(codAbertura, "municipio"), fonte.municipio(codAbertura)])
    let x0 = Infinity,
      y0 = Infinity,
      x1 = -Infinity,
      y1 = -Infinity
    const andar = (c: unknown): void => {
      if (Array.isArray(c) && typeof c[0] === "number") {
        x0 = Math.min(x0, c[0])
        x1 = Math.max(x1, c[0])
        y0 = Math.min(y0, c[1] as number)
        y1 = Math.max(y1, c[1] as number)
      } else if (Array.isArray(c)) c.forEach(andar)
    }
    g?.features.forEach((ft) => andar(ft.geometry.coordinates))
    const local: [number, number] = Number.isFinite(x0) ? [(y0 + y1) / 2, (x0 + x1) / 2] : [-10, -52]
    return { local, nome: f?.municipio ?? "Brasil", uf: f?.uf ?? "", imoveis: f?.imoveis ?? null }
  }, [])

  const revelar = useCallback(() => {
    setEstado("revelando")
    mapa.current?.voar(2600)
  }, [])
  const terminar = useCallback(() => {
    setEstado("fim")
    try {
      sessionStorage.setItem("raiz:abertura", "1")
    } catch {
      /* sem armazenamento: a abertura volta na próxima visita, sem problema */
    }
  }, [])
  const aoMapaPronto = useCallback(() => setMapaPronto(true), [])

  if (rota.tela === "fazenda") return <Fazenda key={rota.car} car={rota.car} />

  const comAbertura = estado !== "nunca" && rota.municipio === codAbertura
  const emCurso = estado === "rodando" || estado === "revelando"
  return (
    <>
      {/* durante a abertura o painel fica por baixo e inerte: a busca que vale é a da abertura */}
      <div inert={emCurso && comAbertura}>
        <Principal
          key={rota.municipio}
          municipio={rota.municipio}
          abertura={comAbertura ? { mapa, revelado: estado !== "rodando", aoMapaPronto } : undefined}
        />
      </div>
      {emCurso && comAbertura && alvo.dado && (
        <Abertura
          local={alvo.dado.local}
          nome={alvo.dado.nome}
          uf={alvo.dado.uf}
          imoveis={alvo.dado.imoveis}
          mapaPronto={mapaPronto}
          aoRevelar={revelar}
          aoTerminar={terminar}
        />
      )}
      {emCurso && comAbertura && !alvo.dado && <div className="abertura abertura-fundo" />}
    </>
  )
}
