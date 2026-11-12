/** Ícones desenhados para a Raíz (traço simples, sem biblioteca). */

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

export function IconePessoa() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="8.5" r="4" stroke="currentColor" strokeWidth="1.8" />
      <path d="M4.5 20c1.2-3.6 4.2-5.5 7.5-5.5s6.3 1.9 7.5 5.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}

export function IconeBaixar() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 4v11m0 0-4.5-4.5M12 15l4.5-4.5M5 19.5h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
