/** No celular o controle nativo começa no botão de informação; todos os créditos continuam
 * disponíveis por toque ou teclado. Aplica uma vez, inclusive se a atribuição chegar com os tiles. */
export function recolherAtribuicaoInicialNoCelular(container: HTMLElement): () => void {
  const celular = window.matchMedia("(max-width: 700px)")
  const atribuicao = container.querySelector<HTMLElement>(".maplibregl-ctrl-attrib")
  if (!atribuicao) return () => {}
  const observador = new MutationObserver(recolher)
  function recolher() {
    if (!celular.matches || !atribuicao?.classList.contains("maplibregl-compact") || atribuicao.classList.contains("maplibregl-attrib-empty")) return
    const botao = atribuicao.querySelector<HTMLElement>("summary.maplibregl-ctrl-attrib-button")
    if (!botao) return
    limpar()
    // Aciona o comportamento público do próprio controle, preservando seu estado e seus eventos.
    if (atribuicao.classList.contains("maplibregl-compact-show")) botao.click()
  }
  function limpar() { observador.disconnect(); celular.removeEventListener("change", recolher) }
  observador.observe(atribuicao, { attributes: true, attributeFilter: ["class"] })
  celular.addEventListener("change", recolher)
  recolher()
  return limpar
}
