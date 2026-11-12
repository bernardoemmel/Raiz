import { useEffect, useState } from "react"

/** São Félix do Xingu (PA): o primeiro município da abertura. */
export const MUNICIPIO_INICIAL = "1507300"

export type Rota = { tela: "mapa"; municipio: string } | { tela: "fazenda"; car: string }

export function lerRota(hash: string): Rota {
  const partes = hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent)
  if (partes[0] === "fazenda" && partes[1]) return { tela: "fazenda", car: partes[1] }
  if (partes[0] === "municipio" && /^\d{7}$/.test(partes[1] ?? "")) return { tela: "mapa", municipio: partes[1] }
  return { tela: "mapa", municipio: MUNICIPIO_INICIAL }
}

export const linkMunicipio = (cod: string) => `#/municipio/${cod}`
export const linkFazenda = (car: string) => `#/fazenda/${encodeURIComponent(car)}`

export function useRota(): Rota {
  const [rota, setRota] = useState(() => lerRota(location.hash))
  useEffect(() => {
    const mudou = () => {
      setRota(lerRota(location.hash))
      window.scrollTo({ top: 0 })
    }
    window.addEventListener("hashchange", mudou)
    return () => window.removeEventListener("hashchange", mudou)
  }, [])
  return rota
}
