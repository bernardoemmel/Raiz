import { useEffect, useState } from "react"

/**
 * Número que conta de 0 até o valor. "zero": ainda escondido pela abertura; "contar": conta (depois da abertura);
 * "final": já mostra o valor. Com "reduzir movimento" ligado no sistema, mostra o valor direto.
 */
export type ModoContagem = "final" | "zero" | "contar"

export function useContagem(valor: number, modo: ModoContagem, ms = 1400) {
  const [v, setV] = useState(0)
  const reduzido = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches
  const contando = modo === "contar" && !reduzido
  useEffect(() => {
    if (!contando) return
    let raf = 0
    const t0 = performance.now()
    const passo = (t: number) => {
      const p = Math.min(1, (t - t0) / ms)
      setV(valor * (1 - Math.pow(1 - p, 3)))
      if (p < 1) raf = requestAnimationFrame(passo)
    }
    raf = requestAnimationFrame(passo)
    return () => cancelAnimationFrame(raf)
  }, [valor, contando, ms])
  if (modo === "zero" && !reduzido) return 0
  return contando ? v : valor
}
