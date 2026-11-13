import assert from "node:assert/strict"

/** Exercita a desmontagem entre etapas cooperativas, fallback e entrada direta sem instâncias órfãs. */
export async function conferirCicloMapa(navegador, base) {
  const erros = []
  const ausentes = []
  const contexto = await navegador.newContext({ viewport: { width: 360, height: 800 } })
  await contexto.addInitScript(() => {
    const Original = Worker, ativos = new Set()
    window.__ativos = ativos
    window.__pendentes = []
    window.Worker = class extends Original {
      constructor(...args) { super(...args); ativos.add(this) }
      terminate() { ativos.delete(this); super.terminate() }
    }
    Object.defineProperty(globalThis, "scheduler", { configurable: true,
      value: { yield: () => new Promise(resolve => window.__pendentes.push(resolve)) } })
  })
  const pagina = await contexto.newPage()
  pagina.on("pageerror", erro => erros.push(erro.message))
  pagina.on("response", resposta => { if (resposta.status() === 404) ausentes.push(resposta.url()) })
  await pagina.goto(base)
  await pagina.waitForFunction(() => window.__pendentes.length === 1)
  assert.equal(await pagina.locator("canvas").count(), 0)
  await pagina.evaluate(() => { location.hash = "#/entrar" })
  await pagina.getByRole("heading", { name: "Entrar na Raíz" }).waitFor()
  await pagina.evaluate(() => window.__pendentes.splice(0).forEach(resolve => resolve()))
  assert.equal(await pagina.locator("canvas").count(), 0)
  assert.equal(await pagina.evaluate(() => window.__ativos.size), 0)

  await pagina.evaluate(() => { location.hash = "#/" })
  await pagina.waitForFunction(() => window.__pendentes.length === 1)
  await pagina.evaluate(() => window.__pendentes.shift()())
  await pagina.waitForFunction(() => window.__pendentes.length === 1 && document.querySelector(".maplibregl-canvas"))
  await pagina.evaluate(() => { location.hash = "#/entrar" })
  await pagina.getByRole("heading", { name: "Entrar na Raíz" }).waitFor()
  await pagina.evaluate(() => window.__pendentes.splice(0).forEach(resolve => resolve()))
  assert.equal(await pagina.locator("canvas").count(), 0)
  assert.equal(await pagina.evaluate(() => window.__ativos.size), 0)
  assert.deepEqual(erros, [])
  await contexto.close()

  const fallback = await navegador.newContext({ viewport: { width: 360, height: 800 } })
  await fallback.addInitScript(() => Object.defineProperty(globalThis, "scheduler", { configurable: true, value: undefined }))
  const direta = await fallback.newPage()
  direta.on("pageerror", erro => erros.push(erro.message))
  direta.on("response", resposta => { if (resposta.status() === 404) ausentes.push(resposta.url()) })
  for (const hash of ["#/estado/PA", "#/municipio/1505536", "#/"]) {
    await direta.goto(base + hash)
    await direta.waitForFunction(() => document.querySelector(".mapa-brasil .mapa")?.__mapa?.loaded())
    if (hash === "#/") await direta.waitForFunction(() => document.querySelector(".mapa-brasil .mapa")?.__hexagonos?.length > 0)
    else if (hash.includes("municipio")) {
      await direta.getByRole("button", { name: "Sobre os dados" }).click()
      await direta.locator("dialog[open] .lista-basica").waitFor()
      await direta.getByRole("button", { name: "Fechar dados" }).click()
    }
    assert.equal(await direta.locator("canvas.maplibregl-canvas").count(), 1)
    assert.equal(await direta.locator(".painel-lateral").count(), 0, "O mapa V2 não pode recriar a coluna lateral.")
    const dimensoes = await direta.locator(".mapa-brasil").boundingBox()
    assert(dimensoes && dimensoes.width >= 359 && dimensoes.height >= 799, "O mapa deve ocupar a tela inteira por baixo dos controles.")
  }
  // Os primeiros hexágonos podem aparecer antes de outras fontes e fontes tipográficas terminarem.
  // Observa a estabilidade somente depois da rede quieta e de um frame completo do mapa.
  await direta.waitForLoadState("networkidle")
  await direta.waitForFunction(() => document.querySelector(".mapa-brasil .mapa").__mapa.loaded())
  await direta.evaluate(() => new Promise(resolve => {
    const mapa = document.querySelector(".mapa-brasil .mapa").__mapa
    mapa.once("idle", resolve)
    mapa.triggerRepaint()
  }))
  const estavel = await direta.evaluate(async () => {
    const mapa = document.querySelector(".mapa-brasil .mapa").__mapa
    let idles = 0
    const contar = () => idles++
    mapa.on("idle", contar)
    // Atualizar a fonte GeoJSON já carregada não pode alimentar um ciclo infinito de idle/render.
    for (let i = 0; i < 6; i++) await new Promise(resolve => requestAnimationFrame(resolve))
    mapa.off("idle", contar)
    const caixa = document.querySelector(".mapa-brasil .mapa")
    return { idles, hexagonos: caixa.__hexagonos.length,
      camada: mapa.getLayer("hexagonos").type,
      cores: Array.from({ length: 6 }, (_, i) => mapa.getPaintProperty(`hexagonos-faixa-${i}`, "fill-color")),
      antigas: document.querySelectorAll("button.cartografia-grupo").length }
  })
  assert(estavel.hexagonos > 0)
  assert.equal(estavel.camada, "fill")
  assert.equal(new Set(estavel.cores).size, 6, "As seis faixas preservam a escala com cores constantes, compartilhando o shader da base.")
  assert.equal(estavel.antigas, 0, "A navegação nacional usa polígonos H3; as bolas antigas não podem voltar.")
  assert(estavel.idles <= 1, "Os hexágonos não podem manter o mapa renderizando sem interação.")
  // O mesmo enquadramento uma volta adiante conserva células e medidas, sem duplicar no antimeridiano.
  // Os centros H3 continuam canônicos: a cópia visual do mundo pertence ao MapLibre.
  const original = await direta.evaluate(() => {
    const caixa = document.querySelector(".mapa-brasil .mapa"), mapa = caixa.__mapa
    const centro = mapa.getCenter().toArray()
    const hexagonos = caixa.__hexagonos.map(h => [h.h3, h.fazendas, h.hectares, h.semMedida])
    window.__hexagonosAnteriores = caixa.__hexagonos
    mapa.jumpTo({ center: [centro[0] + 360, centro[1]] })
    return { centro, hexagonos }
  })
  await direta.waitForFunction(() => document.querySelector(".mapa-brasil .mapa").__hexagonos !== window.__hexagonosAnteriores)
  assert.deepEqual(await direta.evaluate(() => document.querySelector(".mapa-brasil .mapa").__hexagonos.map(h => [h.h3, h.fazendas, h.hectares, h.semMedida])), original.hexagonos)
  await direta.evaluate(centro => {
    const caixa = document.querySelector(".mapa-brasil .mapa")
    window.__hexagonosAnteriores = caixa.__hexagonos
    caixa.__mapa.jumpTo({ center: centro })
  }, original.centro)
  await direta.waitForFunction(() => document.querySelector(".mapa-brasil .mapa").__hexagonos !== window.__hexagonosAnteriores)
  assert.deepEqual(await direta.evaluate(() => document.querySelector(".mapa-brasil .mapa").__hexagonos.map(h => [h.h3, h.fazendas, h.hectares, h.semMedida])), original.hexagonos)
  // A alternativa de teclado continua operável sem marcadores DOM sobre a cartografia.
  await direta.getByText("Como ler o mapa", { exact: true }).click()
  await direta.getByText("Explorar hexágonos com teclado", { exact: true }).click()
  const botaoHexagono = direta.locator(".cartografia-hexagonos-lista button").first()
  await botaoHexagono.waitFor()
  await botaoHexagono.focus()
  assert(await botaoHexagono.evaluate(botao => document.activeElement === botao), "A lista acessível precisa receber foco.")
  const zoomAntes = await direta.evaluate(() => document.querySelector(".mapa-brasil .mapa").__mapa.getZoom())
  await botaoHexagono.press("Enter")
  await direta.waitForFunction(zoom => {
    const caixa = document.querySelector(".mapa-brasil .mapa")
    return caixa.__mapa.getZoom() > zoom && !caixa.__mapa.isMoving() && caixa.__hexagonos?.some(h => h.resolucao === 5)
  }, zoomAntes)
  await direta.evaluate(({ centro, zoom }) => document.querySelector(".mapa-brasil .mapa").__mapa.jumpTo({ center: centro, zoom }), { centro: original.centro, zoom: zoomAntes })
  await direta.waitForFunction(() => document.querySelector(".mapa-brasil .mapa").__hexagonos?.some(h => h.resolucao === 4))
  // Um evento tardio da lista do índice anterior não pode mover o mapa recém-aberto.
  await direta.evaluate(() => { window.__botaoAntigo = document.querySelector(".cartografia-hexagonos-lista button"); location.hash = "#/entrar" })
  await direta.getByRole("heading", { name: "Entrar na Raíz" }).waitFor()
  await direta.evaluate(() => { location.hash = "#/" })
  await direta.waitForFunction(() => document.querySelector(".mapa-brasil .mapa")?.__hexagonos?.length > 0)
  await direta.waitForFunction(() => {
    const mapa = document.querySelector(".mapa-brasil .mapa")?.__mapa
    return mapa?.loaded() && !mapa.isMoving()
  })
  const zoomNovo = await direta.evaluate(() => document.querySelector(".mapa-brasil .mapa").__mapa.getZoom())
  await direta.evaluate(async () => {
    window.__botaoAntigo.click()
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
  })
  assert.equal(await direta.evaluate(() => document.querySelector(".mapa-brasil .mapa").__mapa.getZoom()), zoomNovo)
  assert.deepEqual(erros, [])
  assert.deepEqual(ausentes, [], "A navegação direta e a troca de mapa devem terminar sem 404.")
  await fallback.close()
}
