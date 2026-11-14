import assert from "node:assert/strict"

/** Exercita o controle nativo: começa compacto no celular, revela todas as fontes e conserva teclado/links. */
export async function conferirAtribuicaoCompacta(pagina) {
  const botao = pagina.getByLabel("Mostrar ou recolher créditos do mapa")
  const creditos = pagina.locator(".maplibregl-ctrl-attrib-inner")
  await botao.waitFor({ state: "visible", timeout: 30000 })
  await creditos.waitFor({ state: "hidden" })
  const area = await botao.boundingBox()
  assert(area.width >= 48 && area.height >= 48, "O botão dos créditos precisa de alvo de toque de 48 px.")
  await botao.focus()
  await pagina.keyboard.press("Enter")
  await creditos.waitFor({ state: "visible" })
  assert.match(await creditos.textContent(), /OpenStreetMap.*Protomaps.*CAR\/SICAR.*INPE.*IBGE/s, "Abrir os créditos mantém todas as fontes do mapa.")
  await pagina.keyboard.press("Tab")
  assert(await creditos.locator("a").first().evaluate(el => el === document.activeElement), "Tab deve alcançar o primeiro link de atribuição.")
  await botao.focus()
  await pagina.keyboard.press("Enter")
  await creditos.waitFor({ state: "hidden" })
  assert(await botao.evaluate(el => el === document.activeElement), "Recolher os créditos preserva o foco no controle.")
}
