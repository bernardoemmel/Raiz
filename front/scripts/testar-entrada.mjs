#!/usr/bin/env node
/**
 * Teste da tela de entrada no navegador (front/globo): sobe o Vite com a amostra, abre o Chromium e confere
 *
 *   1. a entrada é o mapa do Brasil, sem baixar o cobe nem mostrar abertura;
 *   2. busca por município leva ao mapa do município, com o funil em barras;
 *   3. tocar num município no mapa faz o mesmo que buscar por ele;
 *   4. busca por código do CAR leva direto à ficha;
 *   5. município de estado ainda não processado abre no mapa com o aviso certo;
 *   6. no celular (360 px): busca no topo, mapa no resto, painel como gaveta que sobe com o município.
 *
 * Uso (de front/globo): npm run test:e2e
 * Precisa do Playwright com o Chromium (npx playwright install chromium) e de front/geo/ gerado (python front/scripts/geo.py).
 */
import { execSync } from "node:child_process"
import { createRequire } from "node:module"
import path from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"

const GLOBO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../globo")
const doGlobo = createRequire(path.join(GLOBO, "package.json"))

function playwright() {
  try {
    return doGlobo("playwright")
  } catch {
    // instalado no sistema (fora do projeto)
    return createRequire(path.join(execSync("npm root -g").toString().trim(), "x.js"))("playwright")
  }
}

const { createServer } = await import(pathToFileURL(doGlobo.resolve("vite")).href)
const { chromium } = playwright()

const SFX = "1507300"
const CAR = "PA-1504950-508C67099D164E0581650983A8CC2059"
const ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]

let falhas = 0
const conferir = (ok, frase) => {
  console.log(`${ok ? "ok  " : "FALHOU"} ${frase}`)
  if (!ok) falhas++
}

const servidor = await createServer({ root: GLOBO, configFile: path.join(GLOBO, "vite.config.ts"), server: { port: 0 }, logLevel: "error" })
await servidor.listen()
const URL_BASE = servidor.resolvedUrls.local[0]
const navegador = await chromium.launch({ args: ARGS })

async function pagina(opcoes) {
  const ctx = await navegador.newContext(opcoes)
  const p = await ctx.newPage()
  const pedidos = []
  const erros = []
  p.on("request", (r) => pedidos.push(r.url()))
  p.on("pageerror", (e) => erros.push(e.message))
  return { p, pedidos, erros }
}

async function buscar(p, texto, opcao) {
  const caixa = p.locator(".topo .busca input")
  await caixa.fill(texto)
  const item = opcao ? p.locator(".busca li[role=option]", { hasText: opcao }).first() : p.locator(".busca li[role=option]").first()
  await item.waitFor({ timeout: 20000 })
  await caixa.press("Enter")
}

try {
  // 1. entrada
  {
    const { p, pedidos, erros } = await pagina({ viewport: { width: 1440, height: 900 } })
    await p.goto(URL_BASE)
    await p.locator(".mapa-brasil canvas").waitFor({ timeout: 30000 })
    await p.locator('aside[aria-label="O Brasil na Raíz"] h1').waitFor()
    await p.waitForFunction(() => document.querySelector(".mapa-brasil .mapa")?.__mapa?.loaded(), null, { timeout: 30000 })
    conferir(!pedidos.some((u) => /cobe/i.test(u)), "a entrada não baixa o cobe")
    conferir((await p.getByText("Pular abertura").count()) === 0, "não há abertura nem botão de pular")
    conferir(new URL(p.url()).hash === "", "a entrada abre sem nada no endereço")
    conferir(await p.locator(".topo .busca input").isVisible(), "a busca está no topo")
    const processados = await p.evaluate(
      () =>
        document
          .querySelector(".mapa-brasil .mapa")
          .__mapa.querySourceFeatures("brasil-municipios")
          .filter((f) => f.properties.p > 0).length,
    )
    conferir(processados > 0, `municípios processados pintados em mata no mapa (${processados} pedaços)`)

    // 2. busca por município
    await buscar(p, "são félix", "São Félix do Xingu")
    await p.waitForURL(new RegExp(`#/municipio/${SFX}$`), { timeout: 20000 })
    await p.locator(".funil-barras").waitFor({ timeout: 60000 })
    conferir((await p.locator(".painel-conteudo h1").textContent()) === "São Félix do Xingu", "busca de município abre o painel dele")
    conferir((await p.locator(".fb-dentro").count()) === 4, "o funil tem as 4 barras")
    await p.waitForFunction(() => document.querySelector(".mapa-brasil .mapa").__mapa.querySourceFeatures("imoveis").length > 0, null, { timeout: 30000 })
    conferir(true, "as fazendas do município estão no mapa")

    // tocar na barra deixa no mapa só quem chegou ali
    await p.locator(".fb-dentro").nth(2).click()
    const pressionada = await p.locator(".fb-dentro").nth(2).getAttribute("aria-pressed")
    const rodape = await p.locator(".tabela-fazendas tfoot th").first().textContent()
    conferir(pressionada === "true" && /seleção/.test(rodape ?? ""), "a barra do funil filtra o mapa e a tabela")

    // 3. tocar num município no mapa (Santarém, sem grupos de pontos por cima)
    await p.goto(URL_BASE + "#/")
    await p.waitForFunction(() => !document.querySelector(".funil-barras"))
    const alvo = await p.evaluate(async () => {
      const m = document.querySelector(".mapa-brasil .mapa").__mapa
      m.jumpTo({ center: [-54.7, -2.6], zoom: 7 })
      await new Promise((r) => m.once("idle", r))
      const c = m.project([-54.7, -2.6])
      const f = m.queryRenderedFeatures(c, { layers: ["brasil-mun"] })[0]
      const r = m.getCanvas().getBoundingClientRect()
      return { x: r.left + c.x, y: r.top + c.y, cod: f && String(f.properties.cod_ibge) }
    })
    await p.mouse.click(alvo.x, alvo.y)
    await p.waitForURL(/#\/municipio\/\d{7}$/, { timeout: 10000 }).catch(() => {})
    conferir(!!alvo.cod && p.url().endsWith(`#/municipio/${alvo.cod}`), `tocar no município ${alvo.cod} abre o mesmo que buscar por ele`)

    // 4. busca por código do CAR
    await buscar(p, CAR)
    await p.waitForURL(/#\/fazenda\//, { timeout: 20000 })
    conferir(decodeURIComponent(p.url()).endsWith(`#/fazenda/${CAR}`), "busca do código do CAR vai direto para a ficha")
    await p.locator(".ficha h1, main h1").first().waitFor({ timeout: 30000 })
    conferir(true, "a ficha abriu")

    // 5. estado ainda não processado
    await buscar(p, "sinop", "Ainda não processado")
    await p.waitForURL(/#\/municipio\/5107909$/, { timeout: 20000 })
    await p.getByText("ainda não foi processado").first().waitFor({ timeout: 20000 })
    conferir(true, "Sinop (MT) abre no mapa com o aviso de que ainda não foi processado")

    conferir(!pedidos.some((u) => /cobe/i.test(u)), "nada do cobe foi baixado em todo o caminho")
    conferir(erros.length === 0, `sem erro de JavaScript${erros.length ? ": " + erros[0] : ""}`)
  }

  // 6. celular
  {
    const { p, erros } = await pagina({ viewport: { width: 360, height: 780 }, isMobile: true, hasTouch: true })
    await p.goto(URL_BASE)
    await p.locator(".mapa-brasil canvas").waitFor({ timeout: 30000 })
    const busca = await p.locator(".topo .busca input").boundingBox()
    const mapa = await p.locator(".mapa-brasil").boundingBox()
    const gaveta = await p.locator(".painel-lateral").boundingBox()
    conferir(busca.y < 140 && busca.x + busca.width <= 360, "celular: busca no topo, sem passar da tela")
    conferir(mapa.y >= busca.y + busca.height && mapa.y + mapa.height >= 760, "celular: o mapa ocupa o resto da tela")
    conferir(gaveta.y > 780 * 0.7, "celular: sem município, a gaveta fica baixa")
    const largura = await p.evaluate(() => document.documentElement.scrollWidth)
    conferir(largura <= 360, `celular: sem rolagem para o lado (${largura} px)`)
    await buscar(p, "nova esperança", "Nova Esperança do Piriá")
    await p.waitForURL(/#\/municipio\/1504950$/, { timeout: 20000 })
    await p.locator(".funil-barras").waitFor({ timeout: 60000 })
    await p.waitForTimeout(400)
    const subiu = await p.locator(".painel-lateral").boundingBox()
    conferir(subiu.y < 780 * 0.6 && subiu.y > 780 * 0.3, "celular: com município, a gaveta sobe até a metade")
    await p.locator(".gaveta-alca").click()
    await p.waitForTimeout(400)
    const alta = await p.locator(".painel-lateral").boundingBox()
    conferir(alta.y < subiu.y, "celular: tocar na alça sobe a gaveta")
    conferir(erros.length === 0, `celular: sem erro de JavaScript${erros.length ? ": " + erros[0] : ""}`)
  }
} catch (e) {
  falhas++
  console.error("FALHOU", e.message.split("\n")[0])
} finally {
  await navegador.close()
  await servidor.close()
}
console.log(falhas ? `\n${falhas} conferência(s) falharam.` : "\nTudo certo.")
process.exit(falhas ? 1 : 0)
