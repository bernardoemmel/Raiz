import { useEffect, useState } from "react"

/** Conta de 0 até o valor quando `animar` liga (depois da abertura); sem animação se o sistema pede menos movimento. */
export function useContagem(valor: number, animar: boolean, ms = 1400) {
  const [v, setV] = useState(0)
  const parado = !animar || matchMedia("(prefers-reduced-motion: reduce)").matches
  useEffect(() => {
    if (parado) return
    let raf = 0
    const t0 = performance.now()
    const passo = (t: number) => {
      const p = Math.min(1, (t - t0) / ms)
      setV(valor * (1 - Math.pow(1 - p, 3)))
      if (p < 1) raf = requestAnimationFrame(passo)
    }
    raf = requestAnimationFrame(passo)
    return () => cancelAnimationFrame(raf)
  }, [valor, parado, ms])
  return parado ? valor : v
}
