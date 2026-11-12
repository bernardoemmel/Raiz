/** Ícones: Lucide (ISC), importados um a um, 20 px ao lado do texto e na cor do texto (guia, item 1.5). A marca da
 * Raíz é desenho próprio até a etapa de identidade (guia, item 10). */

export { CircleAlert, Download, Info, User } from "lucide-react"
import { Check, TriangleAlert, X } from "lucide-react"

export function IconeRaiz({ tamanho = 26 }: { tamanho?: number }) {
  return (
    <svg width={tamanho} height={tamanho} viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <path d="M16 29V12" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" />
      <path d="M16 15c0-5 3-8.5 9-9 0 5.5-3.5 9-9 9Z" fill="currentColor" />
      <path d="M16 19c0-4.5-3-7.5-8.5-8 0 5 3.3 8 8.5 8Z" fill="currentColor" opacity=".72" />
      <path d="M16 25.5c-2 .2-4 1.2-5.5 3M16 25.5c2 .2 4 1.2 5.5 3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

/** Situação de um item: forma diferente para cada estado (certo, alerta, x), nunca só a cor. */
export function IconeSituacao({ ok, bloqueia }: { ok: boolean; bloqueia: boolean }) {
  const Icone = ok ? Check : bloqueia ? X : TriangleAlert
  return <Icone size={20} aria-hidden="true" className="motivo-icone" />
}
