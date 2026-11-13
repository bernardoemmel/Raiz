#!/usr/bin/env node
/** CI: 360 px, teclado, axe WCAG 2.1 AA e Lighthouse mobile com rede/CPU simuladas. */
import assert from "node:assert/strict"
import { configurarPublicacao } from "./configurar-publicacao.mjs"
import fs from "node:fs"
import { createRequire } from "node:module"
import path from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"
import { conferirSerieLighthouseCelular, conferirPaginaAcessivel } from "./conferir-acessibilidade.mjs"
import { servirPublicacao } from "./servidor-publicacao.mjs"

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const require = createRequire(path.join(repo, "front/globo/package.json"))
const { chromium } = require("playwright")
const { default: AxeBuilder } = await import(pathToFileURL(require.resolve("@axe-core/playwright")).href)
const { default: lighthouse } = await import(pathToFileURL(require.resolve("lighthouse")).href)
const { launch } = await import(pathToFileURL(require.resolve("chrome-launcher")).href)
const base = configurarPublicacao(process.env).base
assert(base.startsWith("/") && base.endsWith("/"), "RAIZ_BASE deve começar e terminar em /.")
const saida = path.join(repo, "front/.cache/teste-acessibilidade")
fs.mkdirSync(saida, { recursive: true })
fs.rmSync(path.join(saida, "resumo.json"), { force: true })
const servidor = await servirPublicacao(path.join(repo, "site"), base)
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || (fs.existsSync("/usr/bin/chromium") ? "/usr/bin/chromium" : chromium.executablePath())
const args = ["--no-sandbox", "--disable-dev-shm-usage", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
const browser = await chromium.launch({ executablePath, args })
const contexto = await browser.newContext({ viewport: { width: 360, height: 800 }, reducedMotion: "reduce" })
const page = await contexto.newPage()
const resumo = { axe: [], lighthouse: [] }
let chrome
try {
  const erros = []
  page.on("pageerror", (erro) => erros.push(erro.message))
  await page.goto(servidor.url)
  await page.getByRole("group", { name: "Mapa do Brasil por estado" }).waitFor()
  await page.getByRole("heading", { level: 1 }).waitFor()
  // Tab chega ao atalho e Enter transfere o foco para o conteúdo, sem mudar a rota.
  await page.keyboard.press("Tab")
  assert.equal(await page.locator(":focus").innerText(), "Pular para o conteúdo")
  await page.keyboard.press("Enter")
  assert.equal(await page.locator(":focus").getAttribute("id"), "conteudo")
  // A gaveta responde ao teclado e deixa todas as informações alcançáveis na tela estreita.
  const alca = page.getByRole("button", { name: "Abrir mais o painel" })
  await alca.focus()
  await page.keyboard.press("Enter")
  assert(await page.locator(".gaveta-meia").count())
  await page.keyboard.press("Space")
  assert(await page.locator(".gaveta-alta").count())
  resumo.axe.push(await conferirPaginaAcessivel(page, AxeBuilder, "brasil-360", saida))
  // Busca inteira pelo teclado, sem clique em resultado nem acesso direto à rota do município.
  await page.keyboard.press("/")
  await page.keyboard.type("Parauapebas")
  await page.getByRole("option").first().waitFor()
  await page.keyboard.press("ArrowDown")
  await page.keyboard.press("ArrowUp")
  await page.keyboard.press("Enter")
  await page.waitForURL((url) => url.hash === "#/municipio/1505536")
  await page.locator(".lista-basica").waitFor()
  resumo.axe.push(await conferirPaginaAcessivel(page, AxeBuilder, "municipio-360", saida))

  await page.goto(servidor.url + "#/entrar")
  await page.getByRole("heading", { name: "Entrar na Raíz" }).waitFor()
  await page.getByRole("button", { name: "Mandar o link" }).click()
  await page.getByRole("alert").waitFor()
  assert.equal(await page.getByLabel("Seu e-mail").getAttribute("aria-invalid"), "true")
  resumo.axe.push(await conferirPaginaAcessivel(page, AxeBuilder, "entrada-erro-360", saida))

  await page.evaluate(() => { localStorage.setItem("raiz.sessao", JSON.stringify({ token: "teste-acessibilidade", email: "teste@raiz.invalid" })); window.dispatchEvent(new Event("raiz-sessao")) })
  await page.goto(servidor.url + "#/pedidos/novo")
  await page.getByRole("heading", { name: "Novo pedido" }).waitFor()
  resumo.axe.push(await conferirPaginaAcessivel(page, AxeBuilder, "novo-pedido-360", saida))
  await page.getByText("Mais filtros", { exact: false }).first().click()
  resumo.axe.push(await conferirPaginaAcessivel(page, AxeBuilder, "novo-pedido-filtros-360", saida))
  await page.goto(servidor.url + "#/prospeccao")
  await page.getByRole("heading", { name: "Prospectar terras no Brasil", exact: true }).waitFor()
  resumo.axe.push(await conferirPaginaAcessivel(page, AxeBuilder, "prospeccao-publica-360", saida))
  await page.goto(servidor.url + "produtor/")
  await page.getByRole("heading", { level: 1 }).waitFor()
  resumo.axe.push(await conferirPaginaAcessivel(page, AxeBuilder, "produtor-360", saida))
  const semJs = await browser.newContext({ viewport: { width: 360, height: 800 }, javaScriptEnabled: false })
  const paginaSemJs = await semJs.newPage()
  await paginaSemJs.goto(servidor.url + "produtor/")
  await paginaSemJs.getByRole("heading", { name: "Ficha da sua fazenda", exact: true }).waitFor()
  await paginaSemJs.getByLabel("Código do CAR", { exact: false }).fill("CAR-TESTE-DE-NAVEGACAO")
  await paginaSemJs.getByRole("button", { name: "Ver a ficha", exact: true }).click()
  await paginaSemJs.waitForURL((url) => url.searchParams.get("car") === "CAR-TESTE-DE-NAVEGACAO")
  await semJs.close()
  assert.deepEqual(erros, [], "Erros de execução durante o teste de acessibilidade.")
  await browser.close()

  chrome = await launch({ chromePath: executablePath, chromeFlags: ["--headless", ...args] })
  for (const [nome, caminho] of [["brasil", ""], ["entrar", "#/entrar"], ["novo-pedido", "#/pedidos/novo"], ["prospeccao", "#/prospeccao"], ["acerto", "#/acerto"], ["produtor", "produtor/"]]) {
    const amostras = []
    for (let rodada = 1; rodada <= 3; rodada++) {
      const resultado = await lighthouse(servidor.url + caminho, {
        port: chrome.port, onlyCategories: ["performance", "accessibility"], output: ["json", "html"], logLevel: "error",
        locale: "pt-BR", formFactor: "mobile", screenEmulation: { mobile: true, width: 360, height: 800, deviceScaleFactor: 1, disabled: false },
        throttlingMethod: "simulate",
      })
      assert(resultado, `${nome}: Lighthouse não entregou relatório.`)
      fs.writeFileSync(path.join(saida, `${nome}-${rodada}-lighthouse.json`), resultado.report[0])
      fs.writeFileSync(path.join(saida, `${nome}-${rodada}-lighthouse.html`), resultado.report[1])
      amostras.push(resultado.lhr)
    }
    const notas = conferirSerieLighthouseCelular(amostras)
    resumo.lighthouse.push({ pagina: nome, ...notas })
    console.log(`Lighthouse mobile ${nome}: mediana de desempenho ${notas.performance}, acessibilidade mínima ${notas.accessibility}.`)
  }
  fs.writeFileSync(path.join(saida, "resumo.json"), JSON.stringify(resumo, null, 2) + "\n")
  console.log("360 px, teclado, axe WCAG 2.1 AA e Lighthouse >= 90 aprovados. Relatórios em front/.cache/teste-acessibilidade.")
} finally { await browser.close(); await chrome?.kill(); await servidor.fechar() }
