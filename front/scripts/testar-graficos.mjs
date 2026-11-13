#!/usr/bin/env node
/** Harness isolado, somente dados sintéticos. Confere o bundle real sem publicar fixtures no site. */
import fs from "node:fs/promises"
import http from "node:http"
import os from "node:os"
import path from "node:path"
import assert from "node:assert/strict"
import { createRequire } from "node:module"
import { fileURLToPath } from "node:url"

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const globo = path.join(repo, "front/globo"), require = createRequire(path.join(globo, "package.json"))
const { build } = await import(require.resolve("vite"))
const { default: react } = await import(require.resolve("@vitejs/plugin-react"))
const { chromium } = require("playwright")
const { default: AxeBuilder } = await import(require.resolve("@axe-core/playwright"))
const temporario = await fs.mkdtemp(path.join(globo, ".teste-graficos-"))
const evidencias = process.env.RAIZ_GRAFICOS_EVIDENCIAS || path.join(os.tmpdir(), "raiz-graficos-e2e")
await fs.mkdir(evidencias, { recursive: true })
let servidor, navegador
try {
  await fs.writeFile(path.join(temporario, "index.html"), '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="icon" href="data:,"><title>Ensaio sintético dos gráficos</title></head><body><main id="root"></main><script type="module" src="/entrada.tsx"></script></body></html>')
  await fs.writeFile(path.join(temporario, "entrada.tsx"), `
import { createRoot } from "react-dom/client"
import "../src/index.css"
import "../src/raiz.css"
import { GraficosLote } from "../src/partes/graficos/GraficosLote"
import dados from "../../../testes/fixtures/resultados_graficos_sinteticos.json"
const ausente = new URLSearchParams(location.search).has("ausente")
createRoot(document.getElementById("root")!).render(<div className="pagina"><h1>Ensaio sintético dos gráficos</h1><GraficosLote dados={ausente ? null : dados} demonstracao={!ausente} /></div>)
`)
  const construido = await build({ root: temporario, configFile: false, base: "/", plugins: [react()], logLevel: "warn", build: { outDir: path.join(temporario, "dist"), emptyOutDir: true } })
  const saidas = (Array.isArray(construido) ? construido : [construido]).flatMap((r) => r.output)
  const chunks = new Map(saidas.filter((s) => s.type === "chunk").map((s) => [s.fileName, s]))
  const iniciais = new Set()
  function dependencias(nome) { if (iniciais.has(nome)) return; iniciais.add(nome); for (const imp of chunks.get(nome)?.imports ?? []) dependencias(imp) }
  for (const [nome, chunk] of chunks) if (chunk.isEntry) dependencias(nome)
  const modulosIniciais = [...iniciais].flatMap((nome) => Object.keys(chunks.get(nome)?.modules ?? {}))
  assert.equal(modulosIniciais.some((m) => /node_modules\/(echarts|zrender|vega[^/]*)\//.test(m)), false, "biblioteca gráfica entrou na árvore estática da ficha")
  const dist = path.join(temporario, "dist")
  servidor = http.createServer(async (req, res) => {
    const caminho = new URL(req.url, "http://local").pathname
    const arquivo = path.resolve(dist, `.${caminho === "/" ? "/index.html" : caminho}`)
    if (!arquivo.startsWith(`${dist}${path.sep}`)) { res.writeHead(403).end(); return }
    try {
      const tipos = { ".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".woff2": "font/woff2" }
      res.setHeader("Content-Type", tipos[path.extname(arquivo)] ?? "application/octet-stream")
      res.end(await fs.readFile(arquivo))
    } catch { res.writeHead(404).end() }
  })
  await new Promise((resolve) => servidor.listen(0, "127.0.0.1", resolve))
  const origem = `http://127.0.0.1:${servidor.address().port}`
  const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || process.env.CHROME_PATH
    || await fs.access("/usr/bin/chromium").then(() => "/usr/bin/chromium", () => chromium.executablePath())
  navegador = await chromium.launch({ executablePath, headless: true, args: ["--no-sandbox"] })
  const resultados = []
  for (const largura of [360, 1280]) {
    const contexto = await navegador.newContext({ viewport: { width: largura, height: 900 }, reducedMotion: "reduce" })
    const pagina = await contexto.newPage(), requisicoes = [], erros = []
    pagina.on("request", (r) => requisicoes.push(r.url()))
    pagina.on("pageerror", (e) => erros.push(e.message))
    pagina.on("response", (r) => { if (r.status() >= 400) erros.push(`${r.status()} ${r.url()}`) })
    await pagina.goto(origem)
    await pagina.getByText("Demonstração sintética.", { exact: true }).waitFor()
    assert.equal(requisicoes.some((u) => /ContratosECharts|FaixasVega/.test(u)), false, "bibliotecas carregadas antes de abrir")
    const contrato = pagina.getByRole("button", { name: "Abrir gráfico: contratado, emitido e entregue" })
    await contrato.focus(); await pagina.keyboard.press("Enter")
    await pagina.locator(".contratos-grafico svg").waitFor()
    assert.equal(requisicoes.some((u) => /FaixasVega/.test(u)), false, "Vega carregou antes de abrir seu painel")
    const faixa = pagina.getByRole("button", { name: "Abrir gráfico: faixa prevista e resultado real" })
    await faixa.focus(); await pagina.keyboard.press("Enter")
    await pagina.locator(".faixas-grafico svg").waitFor()
    assert.equal(await pagina.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, "a página transborda no celular")
    const axe = await new AxeBuilder({ page: pagina }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze()
    assert.deepEqual(axe.violations.map(({ id, nodes }) => ({ id, elementos: nodes.map((n) => n.target) })), [])
    await pagina.screenshot({ path: path.join(evidencias, `graficos-${largura}.png`), fullPage: true })
    assert.deepEqual(erros, [])
    await pagina.goto(`${origem}/?ausente=1`)
    await pagina.getByText("A série ainda não foi fornecida pela API autorizada.", { exact: false }).waitFor()
    assert.equal(await pagina.getByRole("button", { name: /Abrir gráfico/ }).count(), 0)
    resultados.push({ largura, teclado: true, violacoes_wcag: axe.violations.length, erros, bibliotecas_sob_demanda: true })
    await contexto.close()
  }
  await fs.writeFile(path.join(evidencias, "resultado.json"), JSON.stringify(resultados, null, 2))
  process.stdout.write(`Gráficos: 360 e 1280 px, teclado, SVG, WCAG AA e carregamento sob demanda aprovados. Evidências: ${evidencias}\n`)
} finally {
  await navegador?.close()
  if (servidor) await new Promise((resolve) => servidor.close(resolve))
  await fs.rm(temporario, { recursive: true, force: true })
}
