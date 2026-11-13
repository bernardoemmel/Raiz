#!/usr/bin/env node
/** HTML real da ficha datada: fixture isolada, navegação por teclado e axe em 360/1440 px. */
import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"
import { spawn } from "node:child_process"
import { once } from "node:events"
import { createRequire } from "node:module"
import { fileURLToPath, pathToFileURL } from "node:url"
import { conferirPaginaAcessivel } from "./conferir-acessibilidade.mjs"

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const require = createRequire(path.join(repo, "front/globo/package.json"))
const { chromium } = require("playwright")
const { default: AxeBuilder } = await import(pathToFileURL(require.resolve("@axe-core/playwright")).href)
const saida = path.join(repo, "front/.cache/teste-ficha-publica")
fs.mkdirSync(saida, { recursive: true })
fs.rmSync(path.join(saida, "resumo.json"), { force: true })
const servidor = spawn(process.env.RAIZ_PYTHON || "python", ["-m", "scripts.fixture_ficha_publica"], { cwd: repo, stdio: ["ignore", "pipe", "pipe"] })
let diagnostico = "", navegador
servidor.stderr.on("data", (dado) => { diagnostico += dado.toString() })
const resumo = { cenario: "Fixture sintética; rotas e HTML reais; sem banco ou Release.", axe: [], erros: [], recusas_esperadas: [], teclado: [] }
try {
  const fixture = await new Promise((resolve, reject) => {
    let recebido = ""
    const limite = setTimeout(() => reject(new Error(`A fixture não iniciou: ${diagnostico}`)), 15_000)
    servidor.once("error", (erro) => { clearTimeout(limite); reject(erro) })
    servidor.once("exit", (codigo) => { clearTimeout(limite); reject(new Error(`A fixture encerrou (${codigo}): ${diagnostico}`)) })
    servidor.stdout.on("data", (dado) => {
      recebido += dado.toString()
      if (recebido.includes("\n")) {
        clearTimeout(limite)
        try { resolve(JSON.parse(recebido.split("\n")[0])) } catch (erro) { reject(erro) }
      }
    })
  })
  const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || (fs.existsSync("/usr/bin/chromium") ? "/usr/bin/chromium" : chromium.executablePath())
  navegador = await chromium.launch({ executablePath, args: ["--no-sandbox", "--disable-dev-shm-usage"] })
  for (const largura of [360, 1440]) {
    const contexto = await navegador.newContext({ viewport: { width: largura, height: 900 }, reducedMotion: "reduce" })
    const pagina = await contexto.newPage()
    let recusaEsperada = false
    pagina.on("pageerror", (erro) => resumo.erros.push(erro.message))
    pagina.on("requestfailed", (pedido) => resumo.erros.push(`Falha de rede: ${pedido.url()}`))
    pagina.on("response", (resposta) => {
      if (resposta.status() < 400) return
      if (recusaEsperada && resposta.status() === 404 && resposta.request().isNavigationRequest() && new URL(resposta.url()).pathname === fixture.antiga)
        resumo.recusas_esperadas.push({ largura, status: 404, caminho: fixture.antiga })
      else resumo.erros.push(`${resposta.status()} ${resposta.url()}`)
    })
    await contexto.request.post(fixture.origem + "/__teste/aceite/aceito")
    const primeira = await pagina.goto(fixture.origem + fixture.antiga)
    assert.equal(primeira.status(), 200)
    await pagina.getByRole("heading", { name: "Ficha básica AB23CD · 10/01/2026", exact: true }).waitFor()
    const aviso = pagina.getByRole("complementary", { name: "Atualização" })
    await aviso.getByRole("link", { name: "dados até 10/02/2026, rodada 2", exact: true }).waitFor()
    resumo.axe.push(await conferirPaginaAcessivel(pagina, AxeBuilder, `ficha-antiga-aviso-${largura}`, saida))
    await pagina.keyboard.press("Tab")
    assert.equal(await pagina.locator(":focus").getAttribute("href"), fixture.origem + fixture.atual)
    assert.equal(await pagina.locator(":focus").evaluate((el) => getComputedStyle(el).outlineStyle), "solid")
    assert(await pagina.locator(":focus").evaluate((el) => parseFloat(getComputedStyle(el).outlineWidth) >= 3))
    await pagina.keyboard.press("Enter")
    await pagina.waitForURL(fixture.origem + fixture.atual)
    await pagina.getByRole("heading", { name: "Ficha básica AB23CD · 10/02/2026", exact: true }).waitFor()
    assert.equal(await pagina.getByRole("complementary", { name: "Atualização" }).count(), 0)
    resumo.axe.push(await conferirPaginaAcessivel(pagina, AxeBuilder, `ficha-atual-${largura}`, saida))
    await pagina.keyboard.press("Tab")
    assert.equal(await pagina.locator(":focus").innerText(), "Link desta versão")
    await pagina.keyboard.press("Tab")
    assert.equal(await pagina.locator(":focus").innerText(), "Ler em Markdown")
    const markdown = pagina.waitForResponse((r) => r.url() === fixture.origem + fixture.atual + ".md")
    await pagina.keyboard.press("Enter")
    assert.equal((await markdown).status(), 200, "O link Markdown não pode terminar em 404")
    await pagina.waitForURL(fixture.origem + fixture.atual + ".md", { waitUntil: "load" })
    resumo.teclado.push({ largura, aviso_para_nova_versao: true, markdown: true, foco_visivel: true })

    await contexto.request.post(fixture.origem + "/__teste/aceite/cancelado")
    recusaEsperada = true
    const recusada = await pagina.goto(fixture.origem + fixture.antiga)
    assert.equal(recusada.status(), 404, "O aceite retirado conserva a recusa da rota real")
    assert.equal(recusada.headers()["cache-control"], "private, no-store")
    assert.equal(await pagina.locator("main, a, img").count(), 0, "A página bloqueada não conserva a ficha ou seus links")
    await pagina.screenshot({ path: path.join(saida, `aceite-bloqueado-${largura}.png`), fullPage: true })
    await contexto.close()
  }
  assert.equal(resumo.recusas_esperadas.length, 2)
  assert.deepEqual(resumo.erros, [], "As páginas consentidas e seus recursos exigem zero erro HTTP/JavaScript")
  fs.writeFileSync(path.join(saida, "resumo.json"), JSON.stringify(resumo, null, 2) + "\n")
  console.log("Ficha pública datada: 360/1440 px, axe, teclado, links sem 404 e recusa esperada após retirar o aceite.")
} finally {
  await navegador?.close()
  if (servidor.pid && servidor.exitCode === null && servidor.signalCode === null) {
    servidor.kill("SIGTERM"); await once(servidor, "exit")
  }
}
