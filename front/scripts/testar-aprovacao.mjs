#!/usr/bin/env node
/** Página humana de reserva: toda a rede é interceptada; não envia e-mail, não acessa servidor nem paga.
 * Uso: node front/scripts/testar-aprovacao.mjs (Playwright + Chromium instalados localmente ou no sistema).
 */
import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import fs from "node:fs"
import { createRequire } from "node:module"
import path from "node:path"
import { fileURLToPath } from "node:url"

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const requireGlobo = createRequire(path.join(repo, "front/globo/package.json"))
let playwright
try { playwright = requireGlobo("playwright") } catch {
  const global = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim()
  playwright = createRequire(path.join(global, "resolver.js"))("playwright")
}
const localPython = path.join(repo, ".venv/bin/python")
const python = process.env.RAIZ_PYTHON || (fs.existsSync(localPython) ? localPython : "python")
const render = JSON.parse(execFileSync(python, ["-c", [
  "import json",
  "from raiz.publica.pagina_aprovacao import pagina",
  "r=pagina('aprovacao-sintetica-de-teste')",
  "print(json.dumps({'html':r.body.decode(),'headers':dict(r.headers)}))",
].join("\n")], { cwd: repo, encoding: "utf8" }))
const origem = "https://api.raiz.example"
const base = "/v1/reservas/confirmar/aprovacao-sintetica-de-teste"
const chamadas = []
const externas = []
let cliqueHumano = false
const executablePath = process.env.RAIZ_CHROMIUM || (fs.existsSync("/usr/bin/chromium") ? "/usr/bin/chromium" : undefined)
const browser = await playwright.chromium.launch({ headless: true, executablePath })
try {
  const context = await browser.newContext()
  await context.route("**/*", async route => {
    const req = route.request()
    const u = new URL(req.url())
    if (u.origin !== origem) {
      externas.push(req.url())
      await route.abort()
      return
    }
    const registro = { caminho: u.pathname, metodo: req.method(), corpo: req.postDataJSON(), headers: req.headers() }
    chamadas.push(registro)
    const json = async (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) })
    if (u.pathname === base && req.method() === "GET") {
      await route.fulfill({ status: 200, headers: render.headers, body: render.html })
    } else if (u.pathname === base + "/entrar") {
      assert.equal(req.method(), "POST")
      assert.deepEqual(registro.corpo, { email: "pessoa@empresa.example" })
      await json({ enviado: true })
    } else if (u.pathname === "/entrar/confirmar") {
      assert.equal(req.method(), "POST")
      if (registro.corpo.token === "link-invalido") {
        await json({ detail: { mensagem: "Link inválido ou vencido; peça outro." } }, 401)
      } else {
        assert.equal(registro.corpo.token, "link-login-sintetico")
        await json({ token: "sessao-sintetica", email: "pessoa@empresa.example" })
      }
    } else if (u.pathname === base + "/resumo") {
      assert.equal(req.method(), "GET")
      assert.equal(registro.headers.authorization, "Bearer sessao-sintetica")
      await json({ valor_brl: 1500, preco_valido_ate: "2026-11-13T15:00:00-03:00", exclusividade: { dias: 30 } })
    } else if (u.pathname === base && req.method() === "POST") {
      assert.ok(cliqueHumano, "A página tentou aprovar sem o clique explícito")
      assert.equal(registro.headers.authorization, "Bearer sessao-sintetica")
      await json({ modo_teste: true, recibo_aprovacao: "recibo-sintetico", pix: {
        copia_e_cola: "PIX-SINTETICO-NAO-PAGA", expira_em: "2026-11-13T16:00:00-03:00",
        qr_svg: '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><path d="M0 0H40V40H0Z"/></svg>',
      } })
    } else {
      externas.push(req.url())
      await route.abort()
    }
  })
  const pagina = await context.newPage()
  const erros = []
  pagina.on("pageerror", erro => erros.push(erro.message))
  await pagina.goto(origem + base)
  await pagina.locator("#login").waitFor({ state: "visible" })
  assert.equal(chamadas.filter(c => c.metodo === "POST").length, 0)
  await pagina.locator("#email").fill("pessoa@empresa.example")
  await pagina.locator("#login button").click()
  await pagina.locator("#aviso").filter({ hasText: "você receberá um link" }).waitFor()
  assert.equal(chamadas.filter(c => c.caminho === base && c.metodo === "POST").length, 0)

  // A pessoa abre o link de entrada em uma nova aba. Autenticar mostra condições, sem aprová-las.
  const autenticada = await context.newPage()
  autenticada.on("pageerror", erro => erros.push(erro.message))
  await autenticada.goto(origem + base + "#/entrar/link-login-sintetico")
  await autenticada.locator("#resumo").waitFor({ state: "visible" })
  assert.equal(new URL(autenticada.url()).hash, "")
  assert.match(await autenticada.locator("#condicoes").textContent(), /1\.500,00/)
  assert.match(await autenticada.locator("#condicoes").textContent(), /30 dias após o pagamento confirmado/)
  assert.equal(chamadas.filter(c => c.caminho === base && c.metodo === "POST").length, 0)
  cliqueHumano = true
  await autenticada.locator("#aprovar").click()
  await autenticada.locator("#pagamento").waitFor({ state: "visible" })
  assert.equal(chamadas.filter(c => c.caminho === base && c.metodo === "POST").length, 1)
  assert.equal(await autenticada.locator("#pix").inputValue(), "PIX-SINTETICO-NAO-PAGA")
  assert.equal(await autenticada.locator("#qr svg").count(), 1)
  assert.match(await autenticada.locator("#recibo").getAttribute("href"), /^blob:/)
  assert.match(await autenticada.locator("#aviso").textContent(), /não efetua pagamento/)

  const invalida = await context.newPage()
  await invalida.goto(origem + base + "#/entrar/link-invalido")
  await invalida.locator("#aviso").filter({ hasText: "Link inválido ou vencido" }).waitFor()
  assert.equal(await invalida.locator("#resumo").isVisible(), false)
  assert.equal(await invalida.locator("#pagamento").isVisible(), false)
  assert.equal(chamadas.filter(c => c.caminho === base && c.metodo === "POST").length, 1)
  assert.deepEqual(erros, [])
  assert.deepEqual(externas, [])
  console.log("Aprovação humana: login, condições, clique explícito, Pix de teste, recibo e link inválido conferidos; zero acesso externo.")
} finally {
  await browser.close()
}
