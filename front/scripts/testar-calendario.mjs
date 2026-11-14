#!/usr/bin/env node
/** Teste da agenda no Chromium com páginas de coleta controladas, sem inventar dados no produto. */
import assert from "node:assert/strict"
import fs from "node:fs"
import { createRequire } from "node:module"
import path from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"
import { conferirPaginaAcessivel } from "./conferir-acessibilidade.mjs"

const globo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../globo")
const doGlobo = createRequire(path.join(globo, "package.json"))
const { default: AxeBuilder } = await import(pathToFileURL(doGlobo.resolve("@axe-core/playwright")).href)
const evidencias = process.env.RAIZ_CALENDARIO_EVIDENCIAS || path.resolve(globo, "../.cache/teste-site/resultado/calendario")
fs.mkdirSync(evidencias, { recursive: true })
const { chromium } = (() => {
  try { return doGlobo("playwright") }
  catch { return createRequire(import.meta.url)("playwright") }
})()
const { createServer } = await import(pathToFileURL(doGlobo.resolve("vite")).href)
const servidor = await createServer({ root: globo, configFile: path.join(globo, "vite.config.ts"), server: { port: 0 }, logLevel: "error" })
await servidor.listen()
const executavel = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || process.env.CHROMIUM_PATH || (fs.existsSync("/usr/bin/chromium") ? "/usr/bin/chromium" : undefined)
const navegador = await chromium.launch({ executablePath: executavel, args: ["--no-sandbox", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] })
const base = servidor.resolvedUrls.local[0]
const car = `PA-1504950-${"A".repeat(32)}`
const eventos = [
  { id: "leilao-teste", tipo: "leilao_imovel", titulo: "Leilão de imóvel rural", data: "2099-11-15", prazo: null, uf: "PA", municipio: "1504950", codigos_car: [car], fonte_url: "https://www.in.gov.br/edital", fonte_nome: "DOU", coletado_em: new Date().toISOString(), confianca: 0.9, situacao: "previsto" },
  { id: "verra-teste", tipo: "verra", titulo: "Prazo da Verra", data: "2099-11-16", prazo: "2099-11-18", uf: null, municipio: null, codigos_car: [], fonte_url: "https://verra.org/", fonte_nome: "Verra", coletado_em: new Date().toISOString(), confianca: 1, situacao: "previsto" },
]
try {
  for (const largura of [1440, 768, 360]) {
    const contexto = await navegador.newContext({ viewport: { width: largura, height: 900 } })
    const pagina = await contexto.newPage()
    const erros = []
    pagina.on("pageerror", (e) => erros.push(e.message))
    await pagina.route("**/calendario/eventos.json", (rota) => rota.fulfill({ json: { eventos, total: 2, coletado_em: new Date().toISOString(), fontes: [] } }))
    await pagina.goto(`${base}#/calendario`)
    await pagina.getByRole("heading", { name: "Calendário da Raíz" }).waitFor()
    await pagina.locator(".calendario-evento").first().waitFor()
    await pagina.getByRole("link", { name: "Pular para o conteúdo" }).focus()
    assert.equal(await pagina.locator(":focus").innerText(), "Pular para o conteúdo")
    await pagina.keyboard.press("Enter")
    assert.equal(await pagina.locator(":focus").getAttribute("id"), "conteudo")
    await conferirPaginaAcessivel(pagina, AxeBuilder, `calendario-${largura}`, evidencias)
    if (process.env.RAIZ_CALENDARIO_CAPTURA) await pagina.screenshot({ path: `${process.env.RAIZ_CALENDARIO_CAPTURA}-${largura}.png`, fullPage: true })
    assert.equal(await pagina.locator(".calendario-evento").count(), 2)
    assert.equal(await pagina.getByRole("link", { name: "Baixar agenda completa (.ics)" }).getAttribute("href"), "/calendario/eventos.ics")
    // A navegação secundária V2 fica no menu da conta em todas as larguras.
    const menu = pagina.locator(".topo-conta")
    const abrirMenu = menu.locator("summary")
    await abrirMenu.focus()
    await pagina.keyboard.press("Enter")
    const linkCalendario = menu.getByRole("link", { name: "Calendário", exact: true })
    await linkCalendario.waitFor({ state: "visible" })
    assert.equal(await linkCalendario.getAttribute("aria-current"), "page")
    assert.equal(await linkCalendario.getAttribute("href"), "#/calendario")
    await linkCalendario.focus()
    await pagina.keyboard.press("Enter")
    assert.equal(new URL(pagina.url()).hash, "#/calendario")
    assert.equal(await menu.evaluate(no => no.open), false, "Escolher a rota fecha o menu da conta.")
    await pagina.getByLabel("Tipo", { exact: true }).selectOption("verra")
    await pagina.getByText("1 evento encontrado.", { exact: false }).waitFor()
    assert.equal(await pagina.locator(".calendario-evento").count(), 1)
    await pagina.getByLabel("Tipo", { exact: true }).selectOption("leilao_imovel")
    await pagina.getByLabel("Estado", { exact: true }).selectOption("MT")
    await pagina.getByText("Nenhum evento encontrado neste filtro.", { exact: true }).waitFor()
    await pagina.getByLabel("Estado", { exact: true }).selectOption("PA")
    await pagina.locator(".calendario-evento").first().waitFor()
    assert((await pagina.getByRole("link", { name: /^CAR / }).getAttribute("href")).includes(encodeURIComponent(car)))
    assert((await pagina.evaluate(() => document.documentElement.scrollWidth)) <= largura)
    assert.deepEqual(erros, [])
    await contexto.close()
    console.log(`ok calendário, filtros, feed, teclado, axe e largura ${largura}px`)
  }
  const pagina = await navegador.newPage()
  await pagina.route("**/calendario/eventos.json", (rota) => rota.fulfill({ status: 404, body: "" }))
  await pagina.goto(`${base}#/calendario`)
  await pagina.getByText("A coleta do calendário ainda não está disponível aqui.", { exact: true }).waitFor()
  assert.equal(await pagina.getByRole("link", { name: /\.ics/ }).count(), 0)
  console.log("ok ausência de coleta não aparece como ausência de eventos")
} finally {
  await navegador.close()
  await servidor.close()
}
