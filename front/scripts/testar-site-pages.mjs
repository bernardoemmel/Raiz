#!/usr/bin/env node
/** Testa o site compilado como no Pages: só arquivos, /Raiz/ e HTTP Range, sem API nem fallback do Vite.
 * Antes: preparar-teste-site.mjs e construir-site.sh com RAIZ_DADOS/RAIZ_GEO apontando à fixture,
 * RAIZ_BASE=/Raiz/ e VITE_RAIZ_TESTE_MAPA=1. PLAYWRIGHT_CHROMIUM_EXECUTABLE é opcional no ambiente local.
 */
import assert from "node:assert/strict"
import fs from "node:fs"
import http from "node:http"
import { createRequire } from "node:module"
import path from "node:path"
import { CAR, MUNICIPIO, REPO, SEM_DESENHO } from "./preparar-teste-site.mjs"

const require = createRequire(path.join(REPO, "front/globo/package.json"))
const { chromium } = require("playwright")
const { PNG } = require("pngjs")
const site = path.join(REPO, "site")
const resultado = path.join(REPO, "front/.cache/teste-site/resultado")
fs.mkdirSync(resultado, { recursive: true })
const tipos = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json",
  ".geojson": "application/geo+json", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".gz": "application/gzip" }
const ausentes = [], faixas = [], erros = [], pedidos = []
const servidor = http.createServer((req, res) => {
  const url = new URL(req.url, "http://localhost")
  const rel = decodeURIComponent(url.pathname).replace(/^\/Raiz\//, "")
  const arquivo = path.resolve(site, rel || "index.html")
  if (!url.pathname.startsWith("/Raiz/") || !arquivo.startsWith(site + path.sep) || !fs.existsSync(arquivo) || !fs.statSync(arquivo).isFile()) {
    ausentes.push(url.pathname)
    res.writeHead(404).end("Arquivo não encontrado")
    return
  }
  const bytes = fs.readFileSync(arquivo)
  const faixa = /^bytes=(\d+)-(\d*)$/.exec(req.headers.range ?? "")
  const headers = { "Content-Type": tipos[path.extname(arquivo)] ?? "application/octet-stream", "Accept-Ranges": "bytes" }
  if (faixa) {
    const inicio = Number(faixa[1]), fim = Math.min(Number(faixa[2] || bytes.length - 1), bytes.length - 1)
    if (inicio > fim) return res.writeHead(416, { "Content-Range": `bytes */${bytes.length}` }).end()
    faixas.push({ arquivo: rel, inicio, fim })
    res.writeHead(206, { ...headers, "Content-Range": `bytes ${inicio}-${fim}/${bytes.length}`, "Content-Length": fim - inicio + 1 })
    res.end(bytes.subarray(inicio, fim + 1))
  } else {
    res.writeHead(200, { ...headers, "Content-Length": bytes.length })
    res.end(req.method === "HEAD" ? undefined : bytes)
  }
})
await new Promise((resolve) => servidor.listen(0, "127.0.0.1", resolve))
const base = `http://127.0.0.1:${servidor.address().port}/Raiz/`
const navegador = await chromium.launch({
  ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}),
  args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
})
const pagina = await navegador.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" })
pagina.on("request", (r) => pedidos.push(r.url()))
pagina.on("pageerror", (e) => erros.push(e.message))
pagina.on("response", (r) => { if (r.status() >= 400) erros.push(`${r.status()} ${r.url()}`) })
pagina.on("console", (m) => { if (m.type() === "error") erros.push(m.text()) })

async function buscar(texto, destino) {
  const busca = pagina.locator(".topo .busca input")
  await busca.fill(texto)
  await pagina.locator('.busca [role="option"]').first().waitFor()
  await busca.press("Enter")
  await pagina.waitForURL((u) => decodeURIComponent(u.hash) === destino)
}
async function mapaPronto() {
  await pagina.waitForFunction(() => {
    const m = document.querySelector(".mapa-brasil .mapa")?.__mapa
    return m?.loaded() && !m.isMoving()
  }, null, { timeout: 30000 })
}

try {
  console.log("Abrindo o build estático no Chromium...")
  await pagina.goto(base)
  await mapaPronto()
  console.log("Buscando Parauapebas...")
  await buscar("Parauapebas", `#/municipio/${MUNICIPIO}`)
  await pagina.locator(".funil-barras").waitFor()
  await mapaPronto()
  // Usa o controle que o visitante usa; não pula direto para um estado interno do mapa.
  console.log("Aproximando pelo botão do mapa...")
  while (await pagina.evaluate(() => document.querySelector(".mapa-brasil .mapa").__mapa.getZoom()) < 13) {
    await pagina.getByRole("button", { name: "Aproximar", exact: true }).click()
    await mapaPronto()
  }
  await pagina.waitForFunction(() => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    const fazendas = m.queryRenderedFeatures({ layers: ["imoveis"] })
    return new Set(fazendas.map((f) => f.properties.cod_imovel)).size === 2 &&
      fazendas.every((f) => [0, 1].includes(m.getFeatureState({ source: "imoveis", id: f.id }).g)) &&
      m.queryRenderedFeatures({ layers: ["water"] }).length > 0
  }, null, { timeout: 30000 })
  const zoom = await pagina.evaluate(() => document.querySelector(".mapa-brasil .mapa").__mapa.getZoom())
  assert(zoom > 6, "O teste precisa aproximar além do zoom 6 disponível na base.")
  const png = PNG.sync.read(await pagina.locator(".mapa-brasil canvas").screenshot({ path: path.join(resultado, "parauapebas.png") }))
  let verdes = 0, amarelos = 0
  for (let i = 0; i < png.data.length; i += 4) {
    const [r, g, b, a] = png.data.subarray(i, i + 4)
    if (a > 240 && g > r + 30 && g > b + 20 && g < 180) verdes++
    if (a > 240 && r > 180 && g > 110 && g < 210 && b < 100) amarelos++
  }
  assert(verdes > 500 && amarelos > 500, `O canvas precisa pintar as duas situações: ${verdes} pixels verdes, ${amarelos} amarelos.`)
  assert(faixas.some((f) => f.arquivo.endsWith("base_brasil.pmtiles")), "A base precisa ser lida por HTTP Range.")
  console.log(`ok: Parauapebas, zoom ${zoom.toFixed(1)}, duas fazendas coloridas e base visível com overzoom.`)

  await buscar(SEM_DESENHO, `#/municipio/${SEM_DESENHO}`)
  await pagina.getByText("O desenho das fazendas deste município ainda não está disponível.", { exact: false }).waitFor()
  await buscar(MUNICIPIO, `#/municipio/${MUNICIPIO}`)
  await pagina.locator(".funil-barras").waitFor()
  await buscar(CAR.toLowerCase().replaceAll("-", ""), `#/fazenda/${CAR}`)
  await pagina.locator(".ficha h1, main h1").first().waitFor()
  await pagina.waitForLoadState("networkidle")
  assert(!pedidos.some((u) => new URL(u).pathname.endsWith("/busca")), "A busca estática não pode pedir /busca.")
  assert.deepEqual(ausentes, [], "Nenhum arquivo pode responder 404.")
  assert.deepEqual(erros, [], "Nenhum erro de rede, JavaScript ou renderização.")
  console.log("ok: busca por nome, IBGE e CAR; aviso de desenho ausente; zero 404 e zero erro no navegador.")
} catch (erro) {
  await pagina.screenshot({ path: path.join(resultado, "falha.png"), fullPage: true }).catch(() => {})
  console.error(JSON.stringify({ ausentes, erros }, null, 2))
  throw erro
} finally {
  fs.writeFileSync(path.join(resultado, "rede.json"), JSON.stringify({ ausentes, erros, faixas, pedidos }, null, 2))
  await navegador.close()
  await new Promise((resolve) => servidor.close(resolve))
}
