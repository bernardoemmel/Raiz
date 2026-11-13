import assert from "node:assert/strict"

/** Exercita a desmontagem entre etapas cooperativas, fallback e entrada direta sem instâncias órfãs. */
export async function conferirCicloMapa(navegador, base) {
  const erros = []
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
  for (const hash of ["#/estado/PA", "#/municipio/1505536", "#/"]) {
    await direta.goto(base + hash)
    await direta.waitForFunction(() => document.querySelector(".mapa-brasil .mapa")?.__mapa?.loaded())
    if (hash === "#/") await direta.locator("button.cartografia-grupo").first().waitFor()
    else if (hash.includes("municipio")) await direta.locator(".lista-basica").waitFor()
    assert.equal(await direta.locator("canvas.maplibregl-canvas").count(), 1)
  }
  const estavel = await direta.evaluate(async () => {
    const mapa = document.querySelector(".mapa-brasil .mapa").__mapa
    let idles = 0
    const contar = () => idles++
    mapa.on("idle", contar)
    // Inserir os botões do mapa já carregado não pode alimentar um ciclo infinito de idle/render.
    for (let i = 0; i < 6; i++) await new Promise(resolve => requestAnimationFrame(resolve))
    mapa.off("idle", contar)
    return { idles, grupos: document.querySelectorAll("button.cartografia-grupo").length }
  })
  assert(estavel.grupos > 0)
  assert(estavel.idles <= 1, "Os marcadores não podem manter o mapa renderizando sem interação.")
  assert.deepEqual(erros, [])
  await fallback.close()
}
