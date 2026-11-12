import assert from "node:assert/strict"

/** Nenhuma categoria ausente, erro de coleta ou nota nula vale como aprovação. */
function conferirColetaCelular(lhr) {
  assert(!lhr.runtimeError, `Lighthouse não concluiu: ${lhr.runtimeError?.message}`)
  const notas = {}
  for (const id of ["performance", "accessibility"]) {
    const nota = lhr.categories?.[id]?.score
    assert(typeof nota === "number" && Number.isFinite(nota) && nota >= 0 && nota <= 1,
      `${id}: Lighthouse recebeu nota inválida ${nota}.`)
    notas[id] = Math.round(nota * 100)
  }
  assert.equal(lhr.configSettings?.formFactor, "mobile", "O portão precisa usar Lighthouse em celular.")
  assert.equal(lhr.configSettings?.screenEmulation?.width, 360, "O portão precisa medir a largura de 360 px.")
  assert.equal(lhr.configSettings?.throttlingMethod, "simulate", "Conservar a simulação de rede e CPU móvel do Lighthouse.")
  return notas
}

export function conferirLighthouseCelular(lhr) {
  const notas = conferirColetaCelular(lhr)
  for (const id of ["performance", "accessibility"])
    assert(lhr.categories[id].score >= 0.9, `${id}: Lighthouse exige pelo menos 90; recebeu ${notas[id]}.`)
  return notas
}

/** Três execuções fixas reduzem ruído do runner. Todas ficam no artefato; nenhum retry escolhe a melhor nota. */
export function conferirSerieLighthouseCelular(amostras) {
  assert.equal(amostras.length, 3, "O portão usa exatamente três medições por página.")
  const notas = amostras.map(conferirColetaCelular)
  for (const lhr of amostras)
    assert(lhr.categories.accessibility.score >= 0.9, "Acessibilidade precisa chegar a 90 em todas as medições.")
  const desempenho = amostras.map((lhr) => lhr.categories.performance.score).sort((a, b) => a - b)[1]
  assert(desempenho >= 0.9, `A mediana de desempenho precisa chegar a 90; recebeu ${Math.round(desempenho * 100)}.`)
  return { performance: Math.round(desempenho * 100), accessibility: Math.min(...notas.map((n) => n.accessibility)), amostras: notas }
}

/** Verificação do fluxo visível: a tabela pode rolar, a página inteira não. */
export async function conferirPaginaAcessivel(page, AxeBuilder, nome, saida) {
  await page.evaluate(() => document.fonts.ready)
  const resultado = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze()
  const fs = await import("node:fs")
  fs.writeFileSync(`${saida}/${nome}-axe.json`, JSON.stringify(resultado, null, 2))
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: `${saida}/${nome}.png`, fullPage: true })
  assert.deepEqual(resultado.violations.map(({ id, nodes }) => ({ id, elementos: nodes.map((n) => n.target) })), [], `${nome}: violações de WCAG 2.1 A/AA.`)
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${nome}: a página excede a largura da tela.`)
  return { pagina: nome, regras: resultado.passes.length, violacoes: 0 }
}
